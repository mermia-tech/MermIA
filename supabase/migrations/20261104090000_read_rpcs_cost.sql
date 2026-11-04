-- MR-24 (1 of 2): the cost read RPCs (09 section 4.1; C3 shapes in packages/contracts rpc.py):
-- get_dish_margin, get_food_cost_pct, get_menu_engineering, get_cost_alerts, and the cost helpers
-- the sales RPCs of 20261104090100_read_rpcs_sales.sql also use.
--
-- Same pattern as MR-17 (20261019200000_read_rpcs_first4.sql): SECURITY INVOKER functions in
-- `api`, so RLS decides the tenant and the locations; the MR-17 envelope, periods, location scope,
-- formatting and unified-grain views are reused as they are.
--
-- Cost figures read dish_cost_snapshot only, which the MR-25 engine (app.compute_dish_costs)
-- writes; cost drivers re-walk the recipe of record with the engine's own read-only helpers.
--
-- Choices the contract leaves open (documented here and in the PR; open to change):
-- - Confidence (03 C.5). get_dish_margin returns the snapshot's `confidence`. The other answers
--   with cost figures have no field for it, so they carry exactly one flag, `cost_confirmed` or
--   `cost_estimated` (the weakest snapshot used), and `uncosted_sales` when sold dishes without a
--   cost were left out.
-- - Target food cost: 32.0 % (app.food_cost_target, 03 "Food cost % targets"); no table holds a
--   per-tenant target yet and tenant.settings is backend-only. A dish breaches the target when its
--   food cost is above target + 3 pts (03 alert table).
-- - Food cost and margin take IVA out as MR-17 does (net - round(net x 16 / 116)), so
--   get_food_cost_pct and compare_periods('food_cost_pct') agree.

-- Cost helpers -----------------------------------------------------------------------------
create function app.food_cost_target() returns numeric
language sql immutable set search_path = ''
as $$ select 32.0 $$;

-- {raw, text} of a calculated percentage, four decimals (C3 Pct).
create function app.pct(x numeric, signed boolean default false) returns jsonb
language sql immutable set search_path = ''
as $$
  select jsonb_build_object('raw', trim_scale(round(x, 4)), 'text', app.fmt_pct(x, signed))
$$;

create function app.money(cents numeric) returns jsonb
language sql immutable set search_path = ''
as $$
  select jsonb_build_object('raw', round(cents)::bigint, 'text', app.fmt_money(round(cents)))
$$;

-- The one confidence flag of an answer that quotes costs: estimated as soon as one snapshot is.
create function app.confidence_flag(levels app.cost_confidence[]) returns jsonb
language sql immutable set search_path = ''
as $$
  select case
    when coalesce(cardinality(levels), 0) = 0 then null
    when levels <@ array['confirmed']::app.cost_confidence[] then
      app.flag('cost_confirmed', 'Costos confirmados: precios de CFDI recientes y recetas confirmadas.')
    else app.flag('cost_estimated', 'Costos estimados: hay precios de más de 30 días o sin CFDI, o recetas sin confirmar.')
  end
$$;

-- Items sold over [f, t] with the dish cost snapshot of that day and its confidence (as
-- app.item_rows, plus the confidence).
create function app.item_cost_rows(locs uuid[], f date, t date)
returns table (location_id uuid, day date, menu_item_id uuid, units numeric, net bigint, discount bigint,
               cost bigint, confidence app.cost_confidence)
language sql stable set search_path = ''
as $$
  select v.location_id, v.business_date, v.menu_item_id, v.units, v.net, v.discount, c.cost, c.confidence
  from app.v_item_sales_daily v
  left join public.dish_cost_snapshot c
    on c.tenant_id = v.tenant_id and c.menu_item_id = v.menu_item_id
   and c.location_id = v.location_id and c.date = v.business_date
  where v.location_id = any (locs) and v.business_date between f and t
$$;

-- The menu price in effect on a day at a location (the engine's rule).
create function app.menu_price_on(item uuid, loc uuid, on_date date) returns bigint
language sql stable set search_path = ''
as $$
  select p.price_gross from public.menu_item_price p
  where p.menu_item_id = item and p.location_id = loc
    and p.effective_from <= on_date and (p.effective_to is null or p.effective_to >= on_date)
  order by p.effective_from desc, p.created_at desc
  limit 1
$$;

-- Top 3 cost drivers of a dish on a day: each top-level recipe line's share of the recipe cost
-- (a sub-recipe line counts as the ingredient it produces), with the engine's formulas.
create function app.cost_drivers(item uuid, on_date date) returns table (ingredient text, share numeric)
language sql stable set search_path = ''
as $$
  with l as (
    select coalesce(made.name, i.name) as name,
      case when rl.sub_recipe_id is not null then
        rl.qty_base * (select c.cost from app.recipe_cost(
          app.recipe_of_record(null, sr.produces_ingredient_id, on_date), on_date) c where c.complete)
      else
        rl.qty_base * (select p.unit_price_net from app.price_of_record(rl.ingredient_id, on_date) p) * 10000
          / nullif(coalesce(rl.yield_override_pct, i.default_yield_pct), 0)
      end as cost
    from public.recipe_line rl
    left join public.ingredient i on i.id = rl.ingredient_id
    left join public.recipe sr on sr.id = rl.sub_recipe_id
    left join public.ingredient made on made.id = sr.produces_ingredient_id
    where rl.recipe_id = app.recipe_of_record(item, null, on_date)
  ), g as (
    select l.name, sum(l.cost) as cost from l group by l.name
  )
  select g.name, 100 * g.cost / nullif(sum(g.cost) over (), 0)
  from g where g.cost > 0
  order by g.cost desc, g.name
  limit 3
$$;

-- Lower case, accents out, anything but letters and digits as one space.
create function app.norm_name(x text) returns text
language sql immutable set search_path = ''
as $$
  select btrim(regexp_replace(translate(lower(x), 'áéíóúüñàèìòùâêîôûäëïö', 'aeiouunaeiouaeiouaeio'), '[^a-z0-9]+', ' ', 'g'))
$$;

-- get_dish_margin ---------------------------------------------------------------------------
-- `dish` is a menu item id or a name. A name matches the dishes whose name holds every word of
-- it; an exact name wins. One match is resolved, several are `ambiguous` (the 5 that sold the
-- most units in the last 30 days), none is not_found. The margin is the latest snapshot on or
-- before today (meta.period_resolved is its day). With no location asked, a single location with
-- a snapshot is used, or the first when every location agrees on cost and price; otherwise the
-- answer is `needs_location` (D24).
create function api.get_dish_margin(dish text, location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  q text;
  item_id uuid;
  item_name text;
  matches int;
  candidates jsonb;
  opts jsonb;
  pick jsonb;
  food numeric;
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  q := app.norm_name(coalesce(dish, ''));
  if q = '' then
    raise exception 'dish must name a dish' using errcode = '22023';
  end if;
  today := app.business_today(location_id);

  if btrim(dish) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    select m.id, m.name into item_id, item_name from public.menu_item m where m.id = btrim(dish)::uuid;
  end if;
  if item_id is null then
    select m.id, m.name into item_id, item_name from public.menu_item m
    where m.is_active and app.norm_name(m.name) = q
    order by m.id limit 1;
  end if;
  if item_id is null then
    with c as (
      select m.id, m.name,
             (select coalesce(sum(v.units), 0) from app.v_item_sales_daily v
              where v.menu_item_id = m.id and v.location_id = any (locs)
                and v.business_date between today - 30 and today - 1) as units
      from public.menu_item m
      where m.is_active
        and not exists (select 1 from unnest(string_to_array(q, ' ')) w
                        where strpos(app.norm_name(m.name), w) = 0)
    )
    select count(*)::int,
           (select jsonb_agg(jsonb_build_object('menu_item_id', x.id, 'name', x.name) order by x.units desc, x.name, x.id)
            from (select * from c order by c.units desc, c.name, c.id limit 5) x),
           (select c.id from c limit 1), (select c.name from c limit 1)
    into matches, candidates, item_id, item_name
    from c;
    if matches = 0 then
      return app.rpc_error('not_found', 'no dish matches that name', locs);
    elsif matches > 1 then
      return app.rpc_ok(jsonb_build_object('match', 'ambiguous', 'candidates', candidates), locs);
    end if;
  end if;
  if item_id is null then
    return app.rpc_error('not_found', 'dish not found', locs);
  end if;

  select jsonb_agg(to_jsonb(x) order by x.name, x.location_id) into opts
  from (
    select distinct on (s.location_id) s.location_id, l.name, s.date, s.cost, s.price_net, s.confidence,
           app.menu_price_on(item_id, s.location_id, s.date) as price_gross
    from public.dish_cost_snapshot s
    join public.location l on l.id = s.location_id
    where s.menu_item_id = item_id and s.location_id = any (locs) and s.date <= today
    order by s.location_id, s.date desc
  ) x
  where x.price_net > 0 and x.price_gross >= x.price_net;

  if opts is null then
    return app.rpc_error('no_data', 'the dish has no cost: its recipe or a price is missing', locs);
  end if;
  if jsonb_array_length(opts) > 1 and (
      select count(distinct (o ->> 'cost', o ->> 'price_net', o ->> 'price_gross', o ->> 'confidence'))
      from jsonb_array_elements(opts) o) > 1 then
    return app.rpc_ok(
      jsonb_build_object('match', 'needs_location', 'menu_item_id', item_id, 'name', item_name,
        'locations', (select jsonb_agg(jsonb_build_object('location_id', o -> 'location_id', 'name', o -> 'name'))
                      from jsonb_array_elements(opts) o)),
      locs, '[]', 100);
  end if;

  pick := opts -> 0;
  food := 100.0 * (pick ->> 'cost')::bigint / (pick ->> 'price_net')::bigint;
  return app.rpc_ok(
    jsonb_build_object(
      'match', 'resolved',
      'menu_item_id', item_id,
      'location_id', pick -> 'location_id',
      'name', item_name,
      'cost', app.money((pick ->> 'cost')::bigint),
      'price_gross', app.money((pick ->> 'price_gross')::bigint),
      'net_price', app.money((pick ->> 'price_net')::bigint),
      'margin', app.money((pick ->> 'price_net')::bigint - (pick ->> 'cost')::bigint),
      'margin_pct', app.pct(100 - round(food, 4)),
      'food_cost', app.pct(food),
      'confidence', pick -> 'confidence',
      'cost_drivers', coalesce((
        select jsonb_agg(jsonb_build_object('ingredient', d.ingredient, 'share', app.pct(d.share)))
        from app.cost_drivers(item_id, (pick ->> 'date')::date) d), '[]')),
    locs, '[]', 100, array[(pick ->> 'date')::date, (pick ->> 'date')::date]);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- get_food_cost_pct -------------------------------------------------------------------------
-- Theoretical food cost over the period (03; fixtures/README.md "Day food cost"): the units x
-- dish cost of the costed items sold over their net sales without IVA. `coverage` is the costed
-- items' share of item net sales. Categories are listed by their net sales, largest first.
create function api.get_food_cost_pct(period jsonb, location_id uuid default null, group_by text default 'none')
returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  r date[];
  x record;
  s record;
  categories jsonb := '[]';
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  if group_by is null or group_by not in ('none', 'category') then
    raise exception 'group_by must be none or category' using errcode = '22023';
  end if;
  r := app.resolve_period(period, app.business_today(location_id));

  select sum(c.units * c.cost) filter (where c.cost is not null) as cost,
         sum(c.net) filter (where c.cost is not null) as covered_net,
         sum(c.net) as total_net,
         array_agg(distinct c.confidence) filter (where c.confidence is not null) as levels
  into x
  from app.item_cost_rows(locs, r[1], r[2]) c;
  if coalesce(x.covered_net, 0) - round(coalesce(x.covered_net, 0) * 16 / 116.0) <= 0 then
    return app.rpc_error('no_data', 'No costed dish sales for the period', locs);
  end if;

  if group_by = 'category' then
    select coalesce(jsonb_agg(jsonb_build_object('category', g.name, 'food_cost', app.pct(g.fc))
                              order by g.total_net desc, g.name), '[]')
    into categories
    from (
      select coalesce(mc.name, 'Sin categoría') as name, sum(c.net) as total_net,
             100 * sum(c.units * c.cost) filter (where c.cost is not null)
               / nullif(sum(c.net) filter (where c.cost is not null)
                        - round(sum(c.net) filter (where c.cost is not null) * 16 / 116.0), 0) as fc
      from app.item_cost_rows(locs, r[1], r[2]) c
      join public.menu_item m on m.id = c.menu_item_id
      left join public.menu_category mc on mc.id = m.category_id
      group by coalesce(mc.name, 'Sin categoría')
    ) g
    where g.fc is not null;
  end if;

  flags := flags || app.confidence_flag(x.levels);
  select * into s from app.sales_totals(locs, r[1], r[2]);
  if s.expected_covered < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.expected_covered, s.expected_days));
  end if;

  return app.rpc_ok(
    jsonb_build_object(
      'theoretical', app.pct(100 * x.cost / (x.covered_net - round(x.covered_net * 16 / 116.0))),
      'target', app.pct(app.food_cost_target()),
      'coverage', app.pct(100.0 * x.covered_net / x.total_net),
      'by_category', categories),
    locs, flags, 100.0 * s.expected_covered / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- get_menu_engineering ----------------------------------------------------------------------
-- Kasavana-Smith (03): over the costed sales of the period, a dish is popular when its share of
-- units is at least 70 % of the equal share (1 / number of dishes), and profitable when its
-- contribution margin per unit (net without IVA - cost) is at least the units-weighted average.
-- Star = popular and profitable, plowhorse = popular only, puzzle = profitable only, dog =
-- neither. Modifiers are left out. Each quadrant lists its 3 best sellers by units.
create function api.get_menu_engineering(period jsonb, location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  r date[];
  s record;
  quadrants jsonb;
  levels app.cost_confidence[];
  uncosted bigint;
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  r := app.resolve_period(period, app.business_today(location_id));

  with x as (
    select c.* from app.item_cost_rows(locs, r[1], r[2]) c
    join public.menu_item m on m.id = c.menu_item_id
    where m.kind <> 'modifier'
  ), d as (
    select x.menu_item_id, sum(x.units) as units,
           sum(x.net - round(x.net * 16 / 116.0)) - sum(x.units * x.cost) as cm
    from x where x.cost is not null
    group by x.menu_item_id having sum(x.units) > 0
  ), tot as (
    select count(*) as n, sum(d.units) as units, sum(d.cm) as cm from d
  ), q as (
    select m.name, d.units,
           case when d.units / tot.units >= 0.7 / tot.n then
                  case when d.cm / d.units >= tot.cm / tot.units then 'star' else 'plowhorse' end
                else case when d.cm / d.units >= tot.cm / tot.units then 'puzzle' else 'dog' end
           end as quadrant
    from d cross join tot join public.menu_item m on m.id = d.menu_item_id
  )
  select case when exists (select 1 from q) then (
           select jsonb_agg(jsonb_build_object(
                    'name', k.name,
                    'count', (select count(*) from q where q.quadrant = k.name),
                    'top_items', coalesce((select jsonb_agg(t.name order by t.units desc, t.name)
                                           from (select q.name, q.units from q where q.quadrant = k.name
                                                 order by q.units desc, q.name limit 3) t), '[]'))
                  order by k.ord)
           from unnest(array['star', 'plowhorse', 'puzzle', 'dog']) with ordinality k(name, ord)) end,
         (select array_agg(distinct x.confidence) from x where x.confidence is not null),
         (select count(*) from x where x.cost is null)
  into quadrants, levels, uncosted;

  if quadrants is null then
    return app.rpc_error('no_data', 'No costed dish sales for the period', locs);
  end if;
  flags := flags || app.confidence_flag(levels);
  if uncosted > 0 then
    flags := flags || app.flag('uncosted_sales', 'Algunos platillos vendidos no tienen costo y no entran en el análisis.');
  end if;
  select * into s from app.sales_totals(locs, r[1], r[2]);
  if s.expected_covered < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.expected_covered, s.expected_days));
  end if;

  return app.rpc_ok(jsonb_build_object('quadrants', quadrants), locs, flags,
                    100.0 * s.expected_covered / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- get_cost_alerts ---------------------------------------------------------------------------
-- `since` names where the window starts; it runs through today (a price that starts today is
-- news), and meta.period_resolved says so.
-- - Price moves: ingredients used by a recipe in effect whose price of record at the end of the
--   window differs by at least 8 % (03 alert table) from the one the day before the window, in
--   the order the new prices started.
-- - Breaches: dishes whose latest snapshot in the window is above target + 3 pts (03), the worst
--   location when several are asked; highest food cost first.
-- - Suggestions: open price_suggestion rows (status null, 'open' or 'pending'), computed by the
--   backend; the dish and its current price are given when `subject` is a dish id or name.
create function app.price_text(pesos numeric, unit app.base_unit) returns text
language sql immutable set search_path = ''
as $$
  select case unit
    when 'g' then app.fmt_money(round(pesos * 100000)) || '/kg'
    when 'ml' then app.fmt_money(round(pesos * 100000)) || '/L'
    else app.fmt_money(round(pesos * 100)) || '/pza'
  end
$$;

create function api.get_cost_alerts(since jsonb default '"last_7d"', location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  r date[];
  w_to date;
  moves jsonb;
  breaches jsonb;
  suggestions jsonb;
  levels app.cost_confidence[];
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  today := app.business_today(location_id);
  r := app.resolve_period(coalesce(since, '"last_7d"'), today);
  w_to := greatest(r[2], today);

  select coalesce(jsonb_agg(jsonb_build_object(
           'ingredient', m.name,
           'change', app.pct(100 * (m.new_price - m.old_price) / m.old_price, true),
           'new_unit_price', jsonb_build_object('raw', trim_scale(m.new_price), 'base_unit', m.base_unit,
                                                'text', app.price_text(m.new_price, m.base_unit)))
         order by m.started, m.name), '[]')
  into moves
  from (
    select i.name, i.base_unit, o.unit_price_net as old_price, n.unit_price_net as new_price, n.effective_from as started
    from public.ingredient i
    cross join lateral app.price_of_record(i.id, r[1] - 1) o
    cross join lateral app.price_of_record(i.id, w_to) n
    where o.unit_price_net > 0 and n.effective_from >= r[1]
      and abs(n.unit_price_net - o.unit_price_net) >= 0.08 * o.unit_price_net
      and exists (select 1 from public.recipe_line rl join public.recipe rc on rc.id = rl.recipe_id
                  where rl.ingredient_id = i.id
                    and (rc.effective_from is null or rc.effective_from <= w_to)
                    and (rc.effective_to is null or rc.effective_to >= w_to))
  ) m;

  with latest as (
    select distinct on (s.menu_item_id, s.location_id) s.menu_item_id, s.cost, s.price_net, s.confidence
    from public.dish_cost_snapshot s
    where s.location_id = any (locs) and s.date between r[1] and w_to and s.price_net > 0
    order by s.menu_item_id, s.location_id, s.date desc
  ), worst as (
    select distinct on (l.menu_item_id) l.menu_item_id, 100.0 * l.cost / l.price_net as fc
    from latest l order by l.menu_item_id, 100.0 * l.cost / l.price_net desc
  )
  select coalesce((select jsonb_agg(jsonb_build_object('menu_item_id', b.menu_item_id, 'name', m.name,
                                                       'food_cost', app.pct(b.fc), 'target', app.pct(app.food_cost_target()))
                                    order by round(b.fc, 4) desc, m.name)
                   from worst b join public.menu_item m on m.id = b.menu_item_id
                   where b.fc > app.food_cost_target() + 3), '[]'),
         (select array_agg(distinct l.confidence) from latest l)
  into breaches, levels;

  select coalesce(jsonb_agg(jsonb_build_object(
           'menu_item_id', x.item_id,
           'name', coalesce(x.item_name, nullif(btrim(x.subject), ''), x.rule),
           'current_price', case when x.price is not null then app.money(x.price) end,
           'suggested_price', app.money(x.suggested_price))
         order by x.created_at, x.id), '[]')
  into suggestions
  from (
    select ps.id, ps.subject, ps.rule, ps.suggested_price, ps.created_at, m.id as item_id, m.name as item_name,
           case when m.id is not null and coalesce(ps.location_id, get_cost_alerts.location_id) is not null
                then app.menu_price_on(m.id, coalesce(ps.location_id, get_cost_alerts.location_id), today) end as price
    from public.price_suggestion ps
    left join lateral (
      select mi.id, mi.name from public.menu_item mi
      where mi.id::text = lower(btrim(ps.subject)) or app.norm_name(mi.name) = app.norm_name(ps.subject)
      order by mi.id::text = lower(btrim(ps.subject)) desc, mi.id limit 1
    ) m on true
    where (ps.location_id = any (locs) or ps.location_id is null)
      and (ps.status is null or ps.status in ('open', 'pending'))
      and ps.suggested_price is not null
  ) x;

  if breaches <> '[]' then
    flags := flags || app.confidence_flag(levels);
  end if;
  return app.rpc_ok(
    jsonb_build_object('price_moves', moves, 'breaches', breaches, 'suggestions', suggestions),
    locs, flags, null, array[r[1], w_to]);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- Privileges --------------------------------------------------------------------------------
-- The RPCs run as the caller, so the caller needs the helpers they call. The engine's read-only
-- helpers (price and recipe of record, recipe cost) are granted for the cost drivers: they run
-- as the caller too and read only what RLS lets the caller read. compute_dish_costs, which
-- writes, stays with the backend.
grant execute on function
  app.price_of_record(uuid, date), app.recipe_of_record(uuid, uuid, date), app.recipe_cost(uuid, date, int),
  app.food_cost_target(), app.pct(numeric, boolean), app.money(numeric),
  app.confidence_flag(app.cost_confidence[]), app.item_cost_rows(uuid[], date, date),
  app.menu_price_on(uuid, uuid, date), app.cost_drivers(uuid, date), app.norm_name(text),
  app.price_text(numeric, app.base_unit)
  to authenticated;
grant execute on function
  api.get_dish_margin(text, uuid), api.get_food_cost_pct(jsonb, uuid, text),
  api.get_menu_engineering(jsonb, uuid), api.get_cost_alerts(jsonb, uuid)
  to authenticated;
