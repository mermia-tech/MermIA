-- MR-32 part 2: apply_pending_change applies recipe.upsert (09 sections 4-5; MR-25 decision 3).
--
-- An approved recipe change becomes a new confirmed recipe version of the dish:
-- - recipe_version = the dish's highest version + 1, status confirmed, effective_from = the
--   tenant's business day of the approval (app.tenant_today), so days already costed keep the
--   recipe they had. Earlier versions are not touched: the recipe of record (highest confirmed
--   version in effect) picks the new one from today on.
-- - The lines come from diff.after.lines, which the MR-25 importer (mermia_api.ingestion.recipes)
--   writes with the matched ids: ingredient_id, sub_recipe_id (with ingredient_id = what it
--   produces) or new_ingredient. payload.values (the C5 RecipeUpsert) has no ids, so it is only
--   checked to describe the same recipe (names, quantities, units, yields, yield_qty).
-- - A new_ingredient line reuses the tenant's ingredient with the same normalized name (the
--   importer's keys.normalize_name: case, accents, parentheses, spaces) and base unit (another
--   approval may have created it since the proposal), or creates it with the line's unit as
--   base_unit. The same name in another unit, or two ingredients with that name and unit, fail.
-- - A line resolved by id (an existing ingredient or a sub-recipe) must carry that ingredient's
--   catalog name, so what the approver saw is what is written.
-- - Quantities must be finite and positive at the precision they are stored with.
-- - Every line's unit must be its ingredient's base unit (so a line is never costed in the wrong
--   unit); a sub-recipe line must point at a recipe that produces an ingredient. The recipe_line
--   triggers (MR-25) stay the backstop against self-use and cycles.
-- - Recipes are tenant-wide: only an all-locations member may approve one (D1), on top of
--   can_approve (the MR-30 defaults give it to the owner only) and required_role.
-- - Today's dish costs are recomputed in the tap (D3). The recipe starts today, so there is no
--   backfill; the shared helper still records one should a recipe ever start earlier.
-- Any failure raises, so apply_pending_change rolls the whole write back and marks the change
-- failed with the reason in the pending_change.fail audit row.

-- mermia_contracts.keys.normalize_name in SQL: NFKD, drop what is not ASCII (accents, ñ -> n),
-- lower case, parentheses as spaces, runs of Python's ASCII whitespace as one space, trimmed.
-- Immutable (normalize, regexp_replace, translate and lower on ASCII are), so it can be indexed.
-- A test checks it against the Python function on a table of tricky names.
create function app.normalize_name(name text) returns text
language sql immutable strict parallel safe set search_path = ''
as $$
  select pg_catalog.btrim(pg_catalog.regexp_replace(
           pg_catalog.translate(
             pg_catalog.lower(pg_catalog.regexp_replace(pg_catalog.normalize(name, 'NFKD'), '[^\x01-\x7f]', '', 'g')),
             '()', '  '),
           '[\t\n\v\f\r\x1c-\x1f ]+', ' ', 'g'), ' ')
$$;

-- the index below runs it on every write to ingredient, so the backend role needs it
grant execute on function app.normalize_name(text) to service_role;

-- new_ingredient lines look ingredients up by normalized name within the tenant
create index ingredient_tenant_normalized_name_idx on public.ingredient (tenant_id, app.normalize_name(name));

-- x is a finite number above 0 once rounded to the `places` decimals of the column it goes in.
create function app.stored_positive(x numeric, places int) returns boolean
language sql immutable parallel safe set search_path = ''
as $$
  select case when x is null or x in ('NaN', 'Infinity', '-Infinity') then false
              else pg_catalog.round(x, places) > 0 end
$$;

-- D1, with recipes tenant-wide. Same as part 1 plus the recipe.upsert location rule.
create or replace function app.pending_change_denial(pc public.pending_change, m public.membership) returns text
language plpgsql stable set search_path = ''
as $$
declare
  locs uuid[];
  payload_location uuid;
begin
  if m.role = 'support' then
    return 'support';  -- MermIA staff propose but never approve
  end if;
  if not (pc.kind = any (m.can_approve)) then
    return 'can_approve';
  end if;
  if pc.required_role = 'owner' and m.role <> 'owner' then
    return 'required_role';
  end if;
  if m.all_locations then
    return null;
  end if;
  if pc.kind = 'recipe.upsert' then
    return 'location';  -- a recipe is the same at every location: all-locations members only
  end if;
  if pc.kind = 'menu_item_price.set' then
    if not coalesce((pc.payload ->> 'location_id') ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$', false) then
      return 'location';  -- no readable location: only an all-locations member may go on
    end if;
    payload_location := (pc.payload ->> 'location_id')::uuid;
    locs := array[payload_location];
  end if;
  if pc.target_type = 'menu_item' then
    locs := locs || (select m2.location_id from public.menu_item m2 where m2.id = pc.target_id and m2.tenant_id = pc.tenant_id);
  elsif pc.target_type = 'import_batch' then
    locs := array[(select b.location_id from public.import_batch b where b.id = pc.target_id and b.tenant_id = pc.tenant_id)];
  end if;
  if not (array_remove(locs, null) <@ coalesce(m.location_ids, '{}')) then
    return 'location';
  end if;
  return null;
end
$$;

-- payload.values (what the proposer filed, C5 RecipeUpsert) and diff.after (the resolved lines
-- the approver was shown) must describe the same recipe, line by line.
create function app.recipe_upsert_check(pc public.pending_change) returns void
language plpgsql stable set search_path = ''
as $$
declare
  vals jsonb := pc.payload -> 'values';
  after jsonb := pc.diff -> 'after';
begin
  if jsonb_typeof(after -> 'lines') is distinct from 'array' or jsonb_array_length(after -> 'lines') = 0 then
    raise exception 'recipe.upsert needs the resolved lines in diff.after.lines' using errcode = '22023';
  end if;
  if not app.stored_positive((after ->> 'yield_qty')::numeric, 6) then  -- recipe.yield_qty numeric(18,6)
    raise exception 'recipe.upsert needs a positive diff.after.yield_qty' using errcode = '22023';
  end if;
  if pc.payload ? 'target_id' and (pc.payload ->> 'target_id')::uuid is distinct from pc.target_id then
    raise exception 'the payload names another dish than the change' using errcode = '22023';
  end if;
  if jsonb_typeof(vals -> 'lines') is distinct from 'array'
     or (vals ->> 'yield_qty')::numeric is distinct from (after ->> 'yield_qty')::numeric
     or jsonb_array_length(vals -> 'lines') <> jsonb_array_length(after -> 'lines')
     or exists (
       select 1
       from jsonb_array_elements(vals -> 'lines') with ordinality as p (v, n)
       join jsonb_array_elements(after -> 'lines') with ordinality as d (v, n) using (n)
       where p.v ->> 'ingredient_name' is distinct from d.v ->> 'ingredient_name'
          or (p.v ->> 'qty_base')::numeric is distinct from (d.v ->> 'qty_base')::numeric
          or p.v ->> 'unit' is distinct from d.v ->> 'unit'
          or (p.v ->> 'yield_override_pct')::numeric is distinct from (d.v ->> 'yield_override_pct')::numeric)
  then
    raise exception 'payload.values and diff.after describe different recipes' using errcode = '22023';
  end if;
end
$$;

-- A line resolved by id names that ingredient as the catalog has it: the approver saw the name.
create function app.recipe_line_name_check(line jsonb, n bigint, catalog_name text) returns void
language plpgsql immutable set search_path = ''
as $$
begin
  if line ->> 'ingredient_name' is distinct from catalog_name then
    raise exception 'line %: the line says "%" but its ingredient is "%" in the catalog', n, line ->> 'ingredient_name', catalog_name
      using errcode = '22023';
  end if;
end
$$;

-- What one diff.after line points at: an ingredient (existing, reused by name or created) or a
-- sub-recipe. `how` is existing | sub_recipe | reused | created. Raises with the line number.
create function app.recipe_line_target(tenant uuid, line jsonb, n bigint,
                                       out ingredient_id uuid, out sub_recipe_id uuid, out how text)
language plpgsql set search_path = ''
as $$
declare
  unit app.base_unit := (line ->> 'unit')::app.base_unit;
  line_name text := btrim(line ->> 'ingredient_name');
  pct numeric := (line ->> 'yield_override_pct')::numeric;
  measured app.base_unit;
  catalog_name text;
  produced uuid;
  same uuid[];
  existing text;
  other_units text;
begin
  -- recipe_line.qty_base numeric(18,6), yield_override_pct numeric(7,4); over 100 % is allowed
  if unit is null or not app.stored_positive((line ->> 'qty_base')::numeric, 6)
     or (pct is not null and not app.stored_positive(pct, 4)) then
    raise exception 'line %: needs a unit, a positive qty_base and a positive yield_override_pct (or none)', n
      using errcode = '22023';
  end if;
  if line ->> 'sub_recipe_id' is not null then
    sub_recipe_id := (line ->> 'sub_recipe_id')::uuid;
    select r.produces_ingredient_id into produced from public.recipe r where r.id = sub_recipe_id and r.tenant_id = tenant;
    if not found then
      raise exception 'line %: sub-recipe % not found in the tenant', n, sub_recipe_id using errcode = 'P0002';
    end if;
    if produced is null then
      raise exception 'line %: recipe % is a dish recipe and cannot be a sub-recipe (a dish cannot use itself or another dish)',
        n, sub_recipe_id using errcode = '23514';
    end if;
    if (line ->> 'ingredient_id')::uuid is distinct from produced then  -- the importer names what it produces
      raise exception 'line %: sub-recipe % does not produce ingredient %', n, sub_recipe_id, line ->> 'ingredient_id'
        using errcode = '22023';
    end if;
    select i.base_unit, i.name into measured, catalog_name from public.ingredient i where i.id = produced;
    perform app.recipe_line_name_check(line, n, catalog_name);
    if measured <> unit then
      raise exception 'line %: % is measured in %, not %', n, line_name, measured, unit using errcode = '22023';
    end if;
    how := 'sub_recipe';
    return;
  end if;
  if line ->> 'ingredient_id' is not null then
    ingredient_id := (line ->> 'ingredient_id')::uuid;
    select i.base_unit, i.name into measured, catalog_name from public.ingredient i where i.id = ingredient_id and i.tenant_id = tenant;
    if not found then
      raise exception 'line %: ingredient % not found in the tenant', n, ingredient_id using errcode = 'P0002';
    end if;
    perform app.recipe_line_name_check(line, n, catalog_name);
    if measured <> unit then
      raise exception 'line %: % is measured in %, not %', n, line_name, measured, unit using errcode = '22023';
    end if;
    how := 'existing';
    return;
  end if;
  if not coalesce((line ->> 'new_ingredient')::boolean, false) or coalesce(line_name, '') = '' then
    raise exception 'line %: needs an ingredient_id, a sub_recipe_id or a named new_ingredient', n using errcode = '22023';
  end if;
  if app.normalize_name(line_name) = '' then
    raise exception 'line %: the new ingredient name "%" needs at least one letter or digit', n, line_name using errcode = '22023';
  end if;
  -- one creator per tenant at a time, so two approvals cannot both create the same name
  perform pg_advisory_xact_lock(hashtextextended('ingredient_name:' || tenant::text, 0));
  select array_agg(i.id order by i.id) filter (where i.base_unit = unit),
         min(i.name),
         string_agg(distinct i.base_unit::text, ', ') filter (where i.base_unit <> unit)
  into same, existing, other_units
  from public.ingredient i
  where i.tenant_id = tenant and app.normalize_name(i.name) = app.normalize_name(line_name);
  if cardinality(same) = 1 then
    ingredient_id := same[1];
    how := 'reused';
    return;
  elsif cardinality(same) > 1 then
    raise exception 'line %: % ingredients are named "%" in %; cannot tell which one', n, cardinality(same), line_name, unit
      using errcode = '22023';
  elsif other_units is not null then
    raise exception 'line %: the new ingredient "%" already exists as "%" in %, not %', n, line_name, existing, other_units, unit
      using errcode = '22023';
  end if;
  insert into public.ingredient (tenant_id, name, base_unit) values (tenant, line_name, unit)
  returning id into ingredient_id;
  how := 'created';
end
$$;

-- A recipe's lines as the apply audit row records them (the importer's diff format, with ids).
create function app.recipe_lines_json(recipe uuid) returns jsonb
language sql stable set search_path = ''
as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'recipe_line_id', rl.id, 'ingredient_name', i.name,
           'ingredient_id', coalesce(rl.ingredient_id, sr.produces_ingredient_id), 'sub_recipe_id', rl.sub_recipe_id,
           'qty_base', rl.qty_base, 'unit', i.base_unit, 'yield_override_pct', rl.yield_override_pct)
         order by rl.created_at, rl.id), '[]')
  from public.recipe_line rl
  left join public.recipe sr on sr.id = rl.sub_recipe_id
  join public.ingredient i on i.id = coalesce(rl.ingredient_id, sr.produces_ingredient_id)
  where rl.recipe_id = recipe
$$;

create function app.apply_recipe(pc public.pending_change) returns jsonb
language plpgsql set search_path = ''
as $$
declare
  after jsonb := pc.diff -> 'after';
  today date := app.tenant_today(pc.tenant_id);
  previous public.recipe;
  r public.recipe;
  l record;
  t record;
  created jsonb := '[]';
  reused jsonb := '[]';
begin
  perform 1 from public.menu_item m where m.id = pc.target_id and m.tenant_id = pc.tenant_id;
  if not found then
    raise exception 'menu item % not found in the tenant', pc.target_id using errcode = 'P0002';
  end if;
  perform app.recipe_upsert_check(pc);
  select * into previous from public.recipe x where x.id = app.recipe_of_record(pc.target_id, null, today);
  insert into public.recipe (tenant_id, menu_item_id, recipe_version, effective_from, yield_qty, status)
  values (pc.tenant_id, pc.target_id,
          (select coalesce(max(x.recipe_version), 0) + 1 from public.recipe x
           where x.tenant_id = pc.tenant_id and x.menu_item_id = pc.target_id),
          today, (after ->> 'yield_qty')::numeric, 'confirmed')
  returning * into r;
  for l in select x.v, x.n from jsonb_array_elements(after -> 'lines') with ordinality as x (v, n) order by x.n loop
    t := app.recipe_line_target(pc.tenant_id, l.v, l.n);
    insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, sub_recipe_id, qty_base, yield_override_pct)
    values (pc.tenant_id, r.id, t.ingredient_id, t.sub_recipe_id, (l.v ->> 'qty_base')::numeric,
            (l.v ->> 'yield_override_pct')::numeric);
    if t.how = 'created' then
      created := created || to_jsonb(t.ingredient_id);
    elsif t.how = 'reused' and not reused @> to_jsonb(t.ingredient_id) then
      reused := reused || to_jsonb(t.ingredient_id);
    end if;
  end loop;
  return jsonb_build_object(
    'before', jsonb_build_object('recipe_id', previous.id, 'recipe_version', previous.recipe_version,
                                 'yield_qty', previous.yield_qty,
                                 'lines', case when previous.id is not null then app.recipe_lines_json(previous.id) end),
    'after', jsonb_build_object('recipe_id', r.id, 'recipe_version', r.recipe_version, 'effective_from', r.effective_from,
                                'yield_qty', r.yield_qty, 'lines', app.recipe_lines_json(r.id),
                                'created_ingredient_ids', created, 'reused_ingredient_ids', reused)
             || app.recompute_after_change(pc.tenant_id, r.effective_from));
end
$$;

-- Part 1's dispatcher with the recipe branch.
create or replace function app.pending_change_write(pc public.pending_change, actor uuid) returns jsonb
language plpgsql set search_path = ''
as $$
begin
  case pc.kind
    when 'ingredient_price.set' then
      return app.apply_ingredient_price(pc);
    when 'menu_item_price.set' then
      return app.apply_menu_item_price(pc);
    when 'recipe.upsert' then
      return app.apply_recipe(pc);
    when 'import_batch.approve', 'import_batch.rollback' then
      return app.apply_batch_change(pc, actor);
    else
      raise exception 'unknown kind %', pc.kind using errcode = '22023';
  end case;
end
$$;

revoke all on function app.normalize_name(text), app.stored_positive(numeric, int),
  app.recipe_line_name_check(jsonb, bigint, text), app.recipe_upsert_check(public.pending_change),
  app.recipe_line_target(uuid, jsonb, bigint), app.recipe_lines_json(uuid),
  app.apply_recipe(public.pending_change)
  from public, anon, authenticated;
