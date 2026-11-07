-- MR-86: the costing engine recomputes only on change days, and a tap or backfill only the dishes
-- the change can move. Same dish_cost_snapshot rows and values as MR-25's engine; every existing
-- function keeps its signature and meaning.
--
-- 1. Change days. A dish's snapshots on day d are a function of what is in effect on d: its recipe
--    of record, the sub-recipes of record, the price of record of each ingredient (and whether it is
--    under 30 days old, for the confirmed grade), and its menu price at each location. Those can
--    only change on a boundary: effective_from or effective_to + 1 of a recipe of the dish, of a
--    recipe producing an ingredient the dish can reach, of a price of such an ingredient or of a
--    menu price of the dish, and effective_from + 30 of such a price. app.compute_dish_costs_for
--    runs MR-25's per-day code once per dish and boundary and copies that day's rows up to the next
--    boundary. Reachability walks every recipe version, so the boundary set is a superset of the
--    real one (an extra boundary costs time, never a different row). The pgTAP test
--    97_costing_change_days checks it against MR-25's engine row by row.
-- 2. Affected dishes. A price can only move the dishes whose recipes (any version, through
--    sub-recipes) reach its ingredient; a menu price or a recipe change only moves its dish.
--    app.dish_cost_items(pending_change) names them; the tap and backfill_dish_costs rewrite only
--    those (other dishes' snapshots keep their rows), compute_dish_costs still rewrites every dish.
-- 3. Per-location today (P6). The tap recomputes from the change's date (or the earliest business
--    day among the tenant's locations) to the latest one, and the backfill ends the day before the
--    earliest, so a tenant in two time zones gets each location's own today. app.tenant_today is
--    unchanged.
-- 4. The tap still costs every dish on today (J1). Until a nightly cost job exists, only taps write
--    snapshots, and MR-32's tap rewrote today for every dish. It now fills each location's own
--    today for every active dish that has no row there yet (insert only: existing rows keep their
--    ids), after recomputing the dishes the change moves.
-- 5. The dishes a tap or backfill rewrites are named after it takes the per-tenant lock, so a
--    recipe committed by a tap it waited for is seen.

-- 1. Change days ------------------------------------------------------------------------------
-- The days in [from_date, to_date] on which the dish's inputs may change, from_date first, sorted.
create function app.dish_cost_change_days(item uuid, from_date date, to_date date) returns date[]
language sql stable set search_path = ''
as $$
  with recursive reach(ingredient) as (  -- every ingredient any recipe version of the dish can use
    select coalesce(rl.ingredient_id, sr.produces_ingredient_id)
    from public.recipe r
    join public.recipe_line rl on rl.recipe_id = r.id
    left join public.recipe sr on sr.id = rl.sub_recipe_id
    where r.menu_item_id = item
    union
    select coalesce(rl.ingredient_id, sr.produces_ingredient_id)
    from reach
    join public.recipe r on r.produces_ingredient_id = reach.ingredient
    join public.recipe_line rl on rl.recipe_id = r.id
    left join public.recipe sr on sr.id = rl.sub_recipe_id
  ),
  boundary(d) as (
    select v.d from public.recipe r, lateral (values (r.effective_from), (r.effective_to + 1)) v (d)
    where r.menu_item_id = item
    union all
    select v.d from reach join public.recipe r on r.produces_ingredient_id = reach.ingredient,
      lateral (values (r.effective_from), (r.effective_to + 1)) v (d)
    union all
    select v.d from reach join public.ingredient_price p on p.ingredient_id = reach.ingredient,
      lateral (values (p.effective_from), (p.effective_to + 1), (p.effective_from + 30)) v (d)
    union all
    select v.d from public.menu_item_price mp, lateral (values (mp.effective_from), (mp.effective_to + 1)) v (d)
    where mp.menu_item_id = item
  )
  select array_agg(x.d order by x.d)
  from (select from_date as d union select b.d from boundary b where b.d > from_date and b.d <= to_date) x
$$;

-- One recompute per tenant at a time (a price job and a batch job may overlap); held to commit.
create function app.lock_dish_costs(tenant uuid) returns void
language sql set search_path = ''
as $$
  select pg_advisory_xact_lock(hashtextextended('dish_cost_snapshot:' || tenant::text, 0))
$$;

-- MR-25's per-day code for one item: cost its recipe of record on `d` and write that row at each
-- location with a menu price on `d` (only `locations`, when given) for every day d .. last_day.
-- A row that already exists is kept. Returns the number written.
create function app.write_dish_cost_rows(tenant uuid, item uuid, d date, last_day date, locations uuid[]) returns int
language plpgsql set search_path = ''
as $$
declare
  rid uuid := app.recipe_of_record(item, null, d);
  c record;
  n int;
begin
  if rid is null then
    return 0;
  end if;
  begin
    select * into c from app.recipe_cost(rid, d);
  exception when sqlstate '54001' then
    return 0;  -- a recipe nested too deep (a cycle that slipped in) costs this dish nothing
  end;
  if not c.complete then
    return 0;
  end if;
  insert into public.dish_cost_snapshot
    (tenant_id, menu_item_id, location_id, date, cost, price_net, margin, food_cost_pct, confidence)
  select tenant, item, mp.location_id, d + k, x.cost, x.price_net, x.price_net - x.cost,
         -- numeric(7,4): a near-free item (cost over ~10x its price) has no food cost %; the
         -- rounded value is tested, since 999.99996 rounds to 1000.0000
         case when x.price_net > 0 and round(100.0 * x.cost / x.price_net, 4) < 1000
              then round(100.0 * x.cost / x.price_net, 4) end,
         (case when c.firm then 'confirmed' else 'estimated' end)::app.cost_confidence
  from (
    select distinct on (p.location_id) p.location_id, p.price_gross, p.tax_rate
    from public.menu_item_price p
    where p.tenant_id = tenant and p.menu_item_id = item
      and p.effective_from <= d and (p.effective_to is null or p.effective_to >= d)
      and (locations is null or p.location_id = any (locations))
    order by p.location_id, p.effective_from desc, p.created_at desc
  ) mp
  cross join lateral (
    select round(c.cost)::bigint as cost,
           (mp.price_gross - round(mp.price_gross * coalesce(mp.tax_rate, 0.16) / (1 + coalesce(mp.tax_rate, 0.16))))::bigint
             as price_net
  ) x
  cross join generate_series(0, last_day - d) k
  on conflict (tenant_id, menu_item_id, location_id, date) do nothing;
  get diagnostics n = row_count;
  return n;
end
$$;

-- compute_dish_costs for the listed menu items only (null: every item of the tenant, as
-- compute_dish_costs). Rewrites their dish_cost_snapshot rows over [from_date, to_date] (at most
-- 400 days) and returns the number written. Each change day runs MR-25's per-day code unchanged.
create function app.compute_dish_costs_for(tenant uuid, items uuid[], from_date date, to_date date) returns int
language plpgsql set search_path = ''
as $$
declare
  item uuid;
  days date[];
  written int := 0;
begin
  if from_date > to_date or to_date - from_date >= 400 then  -- at most 400 days
    raise exception 'invalid range % .. %', from_date, to_date using errcode = '22023';
  end if;
  perform app.lock_dish_costs(tenant);
  delete from public.dish_cost_snapshot s
  where s.tenant_id = tenant and s.date between from_date and to_date
    and (items is null or s.menu_item_id = any (items));

  for item in
    select m.id from public.menu_item m
    where m.tenant_id = tenant and m.is_active  -- any kind with a recipe (dish, drink, modifier, combo)
      and (items is null or m.id = any (items))
  loop
    days := app.dish_cost_change_days(item, from_date, to_date);
    for i in 1 .. cardinality(days) loop
      -- the inputs hold until the next change day
      written := written + app.write_dish_cost_rows(tenant, item, days[i], coalesce(days[i + 1] - 1, to_date), null);
    end loop;
  end loop;
  return written;
end
$$;

-- Same signature and rows as MR-25: every item of the tenant.
create or replace function app.compute_dish_costs(tenant uuid, from_date date, to_date date) returns int
language sql set search_path = ''
as $$
  select app.compute_dish_costs_for(tenant, null, from_date, to_date)
$$;

-- 2. Affected dishes --------------------------------------------------------------------------
-- The tenant's menu items whose recipes (any version, through sub-recipes) can use `target`.
create function app.dish_cost_items_using(tenant uuid, target uuid) returns uuid[]
language sql stable set search_path = ''
as $$
  with recursive uses as (  -- (recipe, ingredient one of its lines costs) in the tenant
    select rl.recipe_id, coalesce(rl.ingredient_id, sr.produces_ingredient_id) as ingredient
    from public.recipe_line rl
    left join public.recipe sr on sr.id = rl.sub_recipe_id
    where rl.tenant_id = tenant
  ),
  up(ingredient) as (  -- target and every ingredient made (by any recipe version) from it
    select target
    union
    select r.produces_ingredient_id
    from up
    join uses u on u.ingredient = up.ingredient
    join public.recipe r on r.id = u.recipe_id
    where r.produces_ingredient_id is not null
  )
  select coalesce(array_agg(distinct r.menu_item_id), '{}')
  from up
  join uses u on u.ingredient = up.ingredient
  join public.recipe r on r.id = u.recipe_id
  where r.menu_item_id is not null
$$;

-- The menu items whose snapshots an applied change can move (null: any, every item).
create function app.dish_cost_items(pc public.pending_change) returns uuid[]
language sql stable set search_path = ''
as $$
  select case pc.kind
           when 'ingredient_price.set' then app.dish_cost_items_using(pc.tenant_id, pc.target_id)
           when 'menu_item_price.set' then array[pc.target_id]
           when 'recipe.upsert' then array[pc.target_id]
         end
$$;

-- 3. Per-location today (P6) ------------------------------------------------------------------
-- The earliest and latest business day among the tenant's locations (app.tenant_today for a
-- tenant without locations).
create function app.tenant_days(tenant uuid, out first_day date, out last_day date)
language sql stable set search_path = ''
as $$
  select coalesce(min(x.d), app.tenant_today(tenant)), coalesce(max(x.d), app.tenant_today(tenant))
  from (select app.business_today(l.id) as d from public.location l where l.tenant_id = tenant) x
$$;

-- D3: the days a change effective from `effective_from` leaves to the backfill: from its date, at
-- most 400 days back counting the earliest location's today, to the day before it. Empty
-- (from_date > to_date) when it starts on that day or later.
create or replace function app.dish_cost_backfill_range(tenant uuid, effective_from date, out from_date date, out to_date date)
language sql stable set search_path = ''
as $$
  select greatest(effective_from, t.first_day - 399), t.first_day - 1 from app.tenant_days(tenant) t
$$;

-- J1: each location's own today, for every active item with a menu price there and no snapshot
-- yet. Insert only: rows that exist keep their ids. Returns the number written.
create function app.fill_dish_costs_today(tenant uuid) returns int
language plpgsql set search_path = ''
as $$
declare
  t record;
  item uuid;
  written int := 0;
begin
  perform app.lock_dish_costs(tenant);
  for t in
    select x.d, array_agg(x.id) as locations
    from (select l.id, app.business_today(l.id) as d from public.location l where l.tenant_id = tenant) x
    group by x.d
  loop
    for item in
      select m.id from public.menu_item m
      where m.tenant_id = tenant and m.is_active
        and exists (
          select 1 from public.menu_item_price p
          where p.tenant_id = tenant and p.menu_item_id = m.id and p.location_id = any (t.locations)
            and p.effective_from <= t.d and (p.effective_to is null or p.effective_to >= t.d)
            and not exists (select 1 from public.dish_cost_snapshot s
                            where s.tenant_id = tenant and s.menu_item_id = m.id
                              and s.location_id = p.location_id and s.date = t.d))
    loop
      written := written + app.write_dish_cost_rows(tenant, item, t.d, t.d, t.locations);
    end loop;
  end loop;
  return written;
end
$$;

-- D3, in the tap: under the tenant lock, rewrite the snapshots of the dishes the change can move
-- (a null change: every dish) from its date, or the earliest location's today, to the latest
-- location's today, then fill each location's today for the other dishes (J1). Nothing when the
-- change starts after every today. Returns {snapshots, backfill} as MR-32's recompute_after_change.
create function app.recompute_after_change(tenant uuid, effective_from date, pc public.pending_change) returns jsonb
language plpgsql set search_path = ''
as $$
declare
  t record;
  r record;
  n int;
begin
  select * into t from app.tenant_days(tenant);
  if effective_from > t.last_day then
    return jsonb_build_object('snapshots', null, 'backfill', null);
  end if;
  -- A2: name the dishes only once the lock is held, so a change committed meanwhile is seen
  perform app.lock_dish_costs(tenant);
  n := app.compute_dish_costs_for(tenant, case when pc is null then null else app.dish_cost_items(pc) end,
                                  greatest(effective_from, t.first_day), t.last_day)
       + app.fill_dish_costs_today(tenant);
  select * into r from app.dish_cost_backfill_range(tenant, effective_from);
  return jsonb_build_object(
    'snapshots', n,
    'backfill', case when r.from_date <= r.to_date then
      jsonb_build_object('from', r.from_date, 'to', r.to_date, 'requested_from', effective_from,
                         'capped', effective_from < r.from_date) end);
end
$$;

create or replace function app.recompute_after_change(tenant uuid, effective_from date) returns jsonb
language sql set search_path = ''
as $$
  select app.recompute_after_change(tenant, effective_from, null::public.pending_change)
$$;

-- The writes recompute only the dishes their change can move (the rest of each body is MR-32's).

create or replace function app.apply_ingredient_price(pc public.pending_change) returns jsonb
language plpgsql set search_path = ''
as $$
declare
  unit app.base_unit;
  eff date := (pc.payload ->> 'effective_from')::date;
  previous numeric;
  p public.ingredient_price;
begin
  select i.base_unit into unit from public.ingredient i where i.id = pc.target_id and i.tenant_id = pc.tenant_id;
  if not found then
    raise exception 'ingredient % not found in the tenant', pc.target_id using errcode = 'P0002';
  end if;
  if eff is null or not coalesce((pc.payload ->> 'unit_price')::numeric > 0, false) then
    raise exception 'ingredient_price.set needs a positive unit_price and an effective_from' using errcode = '22023';
  end if;
  select r.unit_price_net into previous from app.price_of_record(pc.target_id, eff) r;
  insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source, pending_change_id)
  values (pc.tenant_id, pc.target_id, (pc.payload ->> 'unit_price')::numeric, eff,
          coalesce(pc.payload ->> 'source', 'manual')::app.ingredient_price_source, pc.id)
  returning * into p;
  return jsonb_build_object(
    'before', jsonb_build_object('unit_price_net', previous),
    -- D4: the unit the price is per, so a $/kg figure stored as $/g is visible on record
    'after', jsonb_build_object('ingredient_price_id', p.id, 'unit_price_net', p.unit_price_net, 'base_unit', unit,
                                'effective_from', p.effective_from, 'source', p.source)
             || app.recompute_after_change(pc.tenant_id, eff, pc));
end
$$;

create or replace function app.apply_menu_item_price(pc public.pending_change) returns jsonb
language plpgsql set search_path = ''
as $$
declare
  loc uuid := (pc.payload ->> 'location_id')::uuid;
  eff date := (pc.payload ->> 'effective_from')::date;
  gross bigint := (pc.payload ->> 'price_gross')::bigint;
  previous public.menu_item_price;
  tax numeric;
  p public.menu_item_price;
begin
  if loc is null or eff is null or not coalesce(gross > 0, false) then
    raise exception 'menu_item_price.set needs a positive price_gross, a location_id and an effective_from' using errcode = '22023';
  end if;
  -- the price in effect that day at that location; the new row keeps its tax rate
  select * into previous from public.menu_item_price x
  where x.tenant_id = pc.tenant_id and x.menu_item_id = pc.target_id and x.location_id = loc
    and x.effective_from <= eff and (x.effective_to is null or x.effective_to >= eff)
  order by x.effective_from desc, x.created_at desc
  limit 1;
  -- no tax rate on it (no price covers the date): the latest known one for the item there
  tax := coalesce(previous.tax_rate,
                  (select x.tax_rate from public.menu_item_price x
                   where x.tenant_id = pc.tenant_id and x.menu_item_id = pc.target_id and x.location_id = loc
                     and x.tax_rate is not null
                   order by x.effective_from desc, x.created_at desc
                   limit 1));
  if tax is null then
    raise exception 'no tax rate known for menu item % at location %: it has no earlier price there', pc.target_id, loc
      using errcode = '22023';
  end if;
  insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from, source)
  values (pc.tenant_id, loc, pc.target_id, gross, tax, eff, 'manual')
  returning * into p;
  return jsonb_build_object(
    'before', jsonb_build_object('price_gross', previous.price_gross),
    'after', jsonb_build_object('menu_item_price_id', p.id, 'price_gross', p.price_gross, 'location_id', p.location_id,
                                'effective_from', p.effective_from, 'tax_rate', p.tax_rate)
             || app.recompute_after_change(pc.tenant_id, eff, pc));
end
$$;

create or replace function app.apply_recipe(pc public.pending_change) returns jsonb
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
             || app.recompute_after_change(pc.tenant_id, r.effective_from, pc));
end
$$;


-- D3, after commit: MR-32's backfill_dish_costs, rewriting only the dishes the change can move.
create or replace function app.backfill_dish_costs(pending_change_id uuid, max_days int default 7)
returns jsonb
language plpgsql security invoker set search_path = ''
as $$
declare
  b public.dish_cost_backfill;
  pc public.pending_change;
  st app.pending_change_status;
  hi date;
  lo date;
  n int;
  nothing constant jsonb := jsonb_build_object('from', null, 'to', null, 'snapshots', 0, 'next_before', null);
begin
  if max_days is null or max_days not between 1 and 31 then
    raise exception 'max_days must be between 1 and 31' using errcode = '22023';
  end if;
  select * into b from public.dish_cost_backfill x where x.pending_change_id = backfill_dish_costs.pending_change_id for update;
  if not found then
    select p.status into st from public.pending_change p where p.id = backfill_dish_costs.pending_change_id;
    if not found then
      raise exception 'pending change % not found', backfill_dish_costs.pending_change_id using errcode = 'P0002';
    end if;
    if st <> 'applied' then
      raise exception 'pending change % is %, not applied', backfill_dish_costs.pending_change_id, st using errcode = '55000';
    end if;
    return nothing;
  end if;
  if b.done_at is not null then
    return nothing;
  end if;
  hi := b.next_before - 1;  -- an unfinished record has next_before > from_date, so hi >= from_date
  lo := greatest(b.from_date, hi - (max_days - 1));
  -- only the dishes the change can move (app.dish_cost_items), named under the tenant lock (A2)
  select * into pc from public.pending_change p where p.id = b.pending_change_id;
  perform app.lock_dish_costs(b.tenant_id);
  n := app.compute_dish_costs_for(b.tenant_id, app.dish_cost_items(pc), lo, hi);
  update public.dish_cost_backfill x
  set next_before = lo, done_at = case when lo = b.from_date then now() end
  where x.id = b.id;
  return jsonb_build_object('from', lo, 'to', hi, 'snapshots', n, 'next_before', case when lo > b.from_date then lo end);
end
$$;

revoke all on function app.dish_cost_change_days(uuid, date, date), app.compute_dish_costs_for(uuid, uuid[], date, date),
  app.lock_dish_costs(uuid), app.write_dish_cost_rows(uuid, uuid, date, date, uuid[]),
  app.dish_cost_items_using(uuid, uuid), app.dish_cost_items(public.pending_change), app.tenant_days(uuid),
  app.fill_dish_costs_today(uuid), app.recompute_after_change(uuid, date, public.pending_change)
  from public, anon, authenticated;
-- the backend runs the engine and the backfill as service_role (invoker rights): it needs the helpers
grant execute on function app.dish_cost_change_days(uuid, date, date), app.compute_dish_costs_for(uuid, uuid[], date, date),
  app.lock_dish_costs(uuid), app.write_dish_cost_rows(uuid, uuid, date, date, uuid[]),
  app.dish_cost_items_using(uuid, uuid), app.dish_cost_items(public.pending_change)
  to service_role;
