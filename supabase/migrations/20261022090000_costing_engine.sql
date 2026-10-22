-- MR-25: the costing engine (09 section 2.4, 03 C.5-C.6; money rules in fixtures/README.md).
--
-- dish_cost_snapshot is a derived cache: one row per dish, location and day, recomputed when a
-- price, recipe or batch changes (09 section 4.2). app.compute_dish_costs rewrites it for a tenant
-- and a date range; the backend (service_role) runs it, clients only read the snapshots.
--
-- Rules:
-- - Price of record for an ingredient on a day: the latest price in effect that day; among prices
--   that start the same day, the stronger source wins (cfdi > nota > sr_import > manual, 03 "Data
--   model needs"). A benchmark price is "never the cost of record" (03 C.4): it counts only for
--   an ingredient with no other price in effect.
-- - Recipe of record (for a dish, or for the ingredient a sub-recipe produces): among recipes in
--   effect that day (a null effective_from means always), confirmed ones first, then the highest
--   recipe_version. A draft never overrides a confirmed recipe.
-- - Dish cost per portion = (sum over the recipe of qty_base x price per base unit / yield) /
--   yield_qty (1 when unset); a sub-recipe line costs qty_base x the cost per unit of what its
--   ingredient's recipe of record yields. Centavos, rounded once per dish, half away from zero.
--   Purchase prices are without IVA.
-- - Net price = price_gross - IVA inside it (tax_rate, 16% when unknown); margin = net - cost;
--   food_cost_pct = cost / net in percent points (MR-11 D20).
-- - Confidence (03 C.5): confirmed = every recipe in the chain confirmed and every price from a
--   CFDI (or a nota whose price row is marked confirmed) less than 30 days old; otherwise
--   estimated. A food cost above 999.9999 % (a near-free item) is stored as null, never an error. A dish with any line unpriced, or
--   without a menu price at the location, gets no snapshot (it is "missing": RPCs flag it).
-- - Recipes cannot use themselves, form cycles, or use a dish recipe as a sub-recipe (MR-53
--   item 6): a trigger on recipe_line rejects it, and the cost walk stops at depth 8.

-- Recipe structure guard -------------------------------------------------------------------
create function app.check_recipe_line() returns trigger
language plpgsql set search_path = ''
as $$
begin
  if new.sub_recipe_id is null then
    return new;
  end if;
  -- serialize structure changes per tenant, so two concurrent lines cannot close a cycle
  perform pg_advisory_xact_lock(hashtextextended('recipe_structure:' || new.tenant_id::text, 0));
  if new.sub_recipe_id = new.recipe_id then
    raise exception 'a recipe cannot use itself' using errcode = '23514';
  end if;
  if not exists (select 1 from public.recipe r
                 where r.tenant_id = new.tenant_id and r.id = new.sub_recipe_id and r.produces_ingredient_id is not null) then
    raise exception 'a sub-recipe must produce an ingredient (not be a dish recipe)' using errcode = '23514';
  end if;
  if exists (
    with recursive below(id) as (
      select new.sub_recipe_id
      union
      select rl.sub_recipe_id from public.recipe_line rl join below b on rl.recipe_id = b.id
      where rl.tenant_id = new.tenant_id and rl.sub_recipe_id is not null
    )
    select 1 from below where id = new.recipe_id
  ) then
    raise exception 'sub-recipe % would make a cycle with recipe %', new.sub_recipe_id, new.recipe_id
      using errcode = '23514';
  end if;
  return new;
end
$$;

create trigger recipe_line_structure before insert or update of recipe_id, sub_recipe_id on public.recipe_line
  for each row execute function app.check_recipe_line();

-- A recipe used as a sub-recipe must keep producing an ingredient.
create function app.check_recipe_kind() returns trigger
language plpgsql set search_path = ''
as $$
begin
  if new.produces_ingredient_id is null and exists (
    select 1 from public.recipe_line rl where rl.tenant_id = new.tenant_id and rl.sub_recipe_id = new.id
  ) then
    raise exception 'recipe % is used as a sub-recipe and must produce an ingredient', new.id
      using errcode = '23514';
  end if;
  return new;
end
$$;

create trigger recipe_kind before update of produces_ingredient_id, menu_item_id on public.recipe
  for each row execute function app.check_recipe_kind();

-- Price and recipe of record ---------------------------------------------------------------
create function app.price_of_record(ingredient uuid, on_date date)
returns table (unit_price_net numeric, source app.ingredient_price_source, effective_from date, confidence text)
language sql stable set search_path = ''
as $$
  select p.unit_price_net, p.source, p.effective_from, p.confidence
  from public.ingredient_price p
  where p.ingredient_id = ingredient
    and p.effective_from <= on_date and (p.effective_to is null or p.effective_to >= on_date)
  order by p.source = 'benchmark',
           p.effective_from desc,
           array_position(array['cfdi', 'nota', 'sr_import', 'manual', 'benchmark']::app.ingredient_price_source[], p.source),
           p.created_at desc
  limit 1
$$;

create function app.recipe_of_record(item uuid, produces uuid, on_date date) returns uuid
language sql stable set search_path = ''
as $$
  select r.id from public.recipe r
  where ((item is not null and r.menu_item_id = item) or (produces is not null and r.produces_ingredient_id = produces))
    and (r.effective_from is null or r.effective_from <= on_date)
    and (r.effective_to is null or r.effective_to >= on_date)
  order by r.status = 'confirmed' desc, r.recipe_version desc
  limit 1
$$;

-- Unrounded cost of one recipe in centavos, whether every line was priced, and whether it is
-- "confirmed" grade (03 C.5).
create function app.recipe_cost(recipe uuid, on_date date, depth int default 0)
returns table (cost numeric, complete boolean, firm boolean)
language plpgsql stable set search_path = ''
as $$
declare
  l record;
  p record;
  s record;
  total numeric := 0;
  all_priced boolean := true;
  all_firm boolean;
  portions numeric;
begin
  if depth > 8 then
    raise exception 'recipe % nests more than 8 levels', recipe using errcode = '54001';
  end if;
  select r.status = 'confirmed', r.yield_qty into all_firm, portions from public.recipe r where r.id = recipe;
  for l in
    select rl.qty_base, rl.ingredient_id, rl.sub_recipe_id,
           coalesce(rl.yield_override_pct, i.default_yield_pct) as yield_pct,
           -- the sub-recipe in effect for the ingredient this line's sub-recipe produces
           app.recipe_of_record(null, sr.produces_ingredient_id, on_date) as sub_id
    from public.recipe_line rl
    left join public.ingredient i on i.id = rl.ingredient_id
    left join public.recipe sr on sr.id = rl.sub_recipe_id
    where rl.recipe_id = recipe
  loop
    if l.sub_recipe_id is not null then
      if l.sub_id is null then
        all_priced := false;
        continue;
      end if;
      -- cost per unit of what the sub-recipe yields: its total cost / its yield_qty
      select * into s from app.recipe_cost(l.sub_id, on_date, depth + 1);
      if not s.complete then
        all_priced := false;
        continue;
      end if;
      total := total + l.qty_base * s.cost;
      all_firm := all_firm and s.firm;
    else
      select * into p from app.price_of_record(l.ingredient_id, on_date);
      if not found or coalesce(l.yield_pct, 0) <= 0 then
        all_priced := false;
        continue;
      end if;
      -- pesos per base unit x 100 = centavos; / (yield / 100) for the usable share
      total := total + l.qty_base * p.unit_price_net * 100 * 100 / l.yield_pct;
      all_firm := all_firm and p.effective_from > on_date - 30
                  and (p.source = 'cfdi' or (p.source = 'nota' and p.confidence = 'confirmed'));
    end if;
  end loop;
  -- per unit of yield: a portion for a dish recipe, a base unit for a sub-recipe
  if coalesce(portions, 1) <= 0 then
    all_priced := false;
  else
    total := total / coalesce(portions, 1);
  end if;
  return query select total, all_priced, coalesce(all_firm, false);
end
$$;

-- Snapshots --------------------------------------------------------------------------------
-- Rewrites dish_cost_snapshot for the tenant over [from_date, to_date] (at most 400 days).
-- Returns the number of snapshots written.
create function app.compute_dish_costs(tenant uuid, from_date date, to_date date) returns int
language plpgsql set search_path = ''
as $$
declare
  d date;
  item record;
  c record;
  written int := 0;
  n int;
begin
  if from_date > to_date or to_date - from_date > 400 then
    raise exception 'invalid range % .. %', from_date, to_date using errcode = '22023';
  end if;
  -- one recompute per tenant at a time (a price job and a batch job may overlap)
  perform pg_advisory_xact_lock(hashtextextended('dish_cost_snapshot:' || tenant::text, 0));
  delete from public.dish_cost_snapshot s
  where s.tenant_id = tenant and s.date between from_date and to_date;

  for d in select g::date from generate_series(from_date, to_date, interval '1 day') g loop
    for item in
      select m.id as menu_item_id, app.recipe_of_record(m.id, null, d) as recipe_id
      from public.menu_item m
      where m.tenant_id = tenant
    loop
      continue when item.recipe_id is null;
      begin
        select * into c from app.recipe_cost(item.recipe_id, d);
      exception when sqlstate '54001' then
        continue;  -- a recipe nested too deep (a cycle that slipped in) costs this dish nothing
      end;
      continue when not c.complete;
      insert into public.dish_cost_snapshot
        (tenant_id, menu_item_id, location_id, date, cost, price_net, margin, food_cost_pct, confidence)
      select tenant, item.menu_item_id, mp.location_id, d, x.cost, x.price_net, x.price_net - x.cost,
             -- numeric(7,4): a near-free item (cost over ~10x its price) has no food cost %
             case when x.price_net > 0 and 100.0 * x.cost / x.price_net < 1000
                  then round(100.0 * x.cost / x.price_net, 4) end,
             (case when c.firm then 'confirmed' else 'estimated' end)::app.cost_confidence
      from (
        select distinct on (p.location_id) p.location_id, p.price_gross, p.tax_rate
        from public.menu_item_price p
        where p.tenant_id = tenant and p.menu_item_id = item.menu_item_id
          and p.effective_from <= d and (p.effective_to is null or p.effective_to >= d)
        order by p.location_id, p.effective_from desc, p.created_at desc
      ) mp
      cross join lateral (
        select round(c.cost)::bigint as cost,
               (mp.price_gross - round(mp.price_gross * coalesce(mp.tax_rate, 0.16) / (1 + coalesce(mp.tax_rate, 0.16))))::bigint
                 as price_net
      ) x;
      get diagnostics n = row_count;
      written := written + n;
    end loop;
  end loop;
  return written;
end
$$;

revoke all on function app.check_recipe_line(), app.check_recipe_kind(), app.price_of_record(uuid, date),
  app.recipe_of_record(uuid, uuid, date),
  app.recipe_cost(uuid, date, int), app.compute_dish_costs(uuid, date, date) from public, anon, authenticated;
grant execute on function app.compute_dish_costs(uuid, date, date) to service_role;
