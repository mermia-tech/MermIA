-- MR-24 (1 of 2): the cost read RPCs (09 section 4.1; C3 shapes in packages/contracts rpc.py):
-- get_dish_margin, get_food_cost_pct, get_menu_engineering, get_cost_alerts, and the cost helpers
-- the sales RPCs of 20261108090100_read_rpcs_sales.sql also use.
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
-- - IVA comes out of item sales at the rate of the menu price in effect that day (16 % when the
--   price row has none), the rate the engine uses for the snapshot's net price, so food cost and
--   margin agree across RPCs in the northern border zone (8 %) or for 0 % items. Item nets are
--   taken out of IVA per row unrounded and the sum is rounded once (app.net_ex_iva); for one rate
--   that is MR-17's net - round(net x 16 / 116). 20261108090200_iva_by_tax_rate.sql moves
--   compare_periods, compare_locations and get_top_dishes onto the same rule.
-- - get_dish_margin flags `stale_cost` (and says `estimated`) when the snapshot is older than the
--   location's latest one or than 30 days: the engine stopped costing the dish.

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

-- The menu price row in effect on a day at a location (the engine's rule), its price and its
-- IVA rate (16 % when the row has none, as the engine assumes).
create function app.menu_price_row(item uuid, loc uuid, on_date date) returns table (price_gross bigint, tax_rate numeric)
language sql stable set search_path = ''
as $$
  select p.price_gross, coalesce(p.tax_rate, 0.16) from public.menu_item_price p
  where p.menu_item_id = item and p.location_id = loc
    and p.effective_from <= on_date and (p.effective_to is null or p.effective_to >= on_date)
  order by p.effective_from desc, p.created_at desc
  limit 1
$$;

create function app.menu_price_on(item uuid, loc uuid, on_date date) returns bigint
language sql stable set search_path = ''
as $$ select r.price_gross from app.menu_price_row(item, loc, on_date) r $$;

-- A net with IVA inside, without it, unrounded: callers sum and round once. The rate is a
-- fraction (0.16); null is 16 %.
create function app.net_ex_iva(net numeric, tax_rate numeric) returns numeric
language sql immutable set search_path = ''
as $$ select net / (1 + coalesce(tax_rate, 0.16)) $$;

-- Items sold over [f, t] with the dish cost snapshot of that day and its confidence (as
-- app.item_rows, plus the confidence and the net without IVA at the day's menu price rate).
-- The rate is app.menu_price_row's rule, as one join over the price rows (one lookup per row
-- made the MR-17 RPCs about 4x slower, PR #77 review).
create function app.item_cost_rows(locs uuid[], f date, t date)
returns table (location_id uuid, day date, menu_item_id uuid, units numeric, net bigint, discount bigint,
               cost bigint, confidence app.cost_confidence, net_ex_iva numeric)
language sql stable set search_path = ''
as $$
  with v as (
    select v.location_id, v.business_date, v.menu_item_id, v.units, v.net, v.discount, c.cost, c.confidence
    from app.v_item_sales_daily v
    left join public.dish_cost_snapshot c
      on c.tenant_id = v.tenant_id and c.menu_item_id = v.menu_item_id
     and c.location_id = v.location_id and c.date = v.business_date
    where v.location_id = any (locs) and v.business_date between f and t
  ), rate as (
    select distinct on (v.location_id, v.business_date, v.menu_item_id)
           v.location_id, v.business_date, v.menu_item_id, coalesce(p.tax_rate, 0.16) as tax_rate
    from v join public.menu_item_price p
      on p.menu_item_id = v.menu_item_id and p.location_id = v.location_id
     and p.effective_from <= v.business_date and (p.effective_to is null or p.effective_to >= v.business_date)
    order by v.location_id, v.business_date, v.menu_item_id, p.effective_from desc, p.created_at desc
  )
  select v.location_id, v.business_date, v.menu_item_id, v.units, v.net, v.discount, v.cost, v.confidence,
         app.net_ex_iva(v.net, rate.tax_rate)
  from v left join rate
    on rate.location_id = v.location_id and rate.business_date = v.business_date and rate.menu_item_id = v.menu_item_id
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
-- before today (meta.period_resolved is its day). It is stale when it is older than the latest
-- snapshot of any dish at that location, or than 30 days: the engine stopped costing the dish (a
-- price or the recipe went missing), so the answer says `estimated` and flags `stale_cost`. With
-- no location asked, a single location with a snapshot is used, or, when every location agrees on
-- cost, price and the snapshot's confidence, the freshest one (a current snapshot before a stale
-- one, then the latest day); otherwise the answer is `needs_location` (D24). A recipe changed
-- since the snapshot that now nests too deep loses its cost drivers, not the answer.
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
  drivers jsonb;
  flags jsonb := '[]';
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
    -- an exact name; when several items share it ("Coca-Cola" and "Coca Cola"), the one costed
    -- in these locations, else they are ambiguous
    with e as (
      select m.id, m.name, exists (select 1 from public.dish_cost_snapshot s
                                   where s.menu_item_id = m.id and s.location_id = any (locs) and s.date <= today) as costed
      from public.menu_item m where m.is_active and app.norm_name(m.name) = q
    )
    select case when count(*) = 1 then min(e.id::text)
                when count(*) filter (where e.costed) = 1 then min(e.id::text) filter (where e.costed) end::uuid,
           count(*)::int,
           (select jsonb_agg(jsonb_build_object('menu_item_id', x.id, 'name', x.name) order by x.costed desc, x.name, x.id)
            from (select * from e order by e.costed desc, e.name, e.id limit 5) x)
    into item_id, matches, candidates
    from e;
    if item_id is null and matches > 1 then
      return app.rpc_ok(jsonb_build_object('match', 'ambiguous', 'candidates', candidates), locs);
    end if;
    select m.name into item_name from public.menu_item m where m.id = item_id;
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

  -- freshest first (PR #77 review): a stale location never wins over a current one
  select jsonb_agg(to_jsonb(x) - 'latest' || jsonb_build_object(
           'stale', x.stale, 'snapshot_confidence', x.confidence,
           'confidence', case when x.stale then 'estimated'::app.cost_confidence else x.confidence end)
         order by x.stale, x.date desc, x.name, x.location_id) into opts
  from (
    select y.*, (y.date < y.latest or y.date < today - 30) as stale
    from (
      select distinct on (s.location_id) s.location_id, l.name, s.date, s.cost, s.price_net, s.confidence,
             app.menu_price_on(item_id, s.location_id, s.date) as price_gross,
             (select max(o.date) from public.dish_cost_snapshot o
              where o.location_id = s.location_id and o.date <= today) as latest
      from public.dish_cost_snapshot s
      join public.location l on l.id = s.location_id
      where s.menu_item_id = item_id and s.location_id = any (locs) and s.date <= today
      order by s.location_id, s.date desc
    ) y
  ) x
  where x.price_net > 0 and x.price_gross >= x.price_net;

  if opts is null then
    return app.rpc_error('no_data', 'the dish has no cost: its recipe or a price is missing', locs);
  end if;
  if jsonb_array_length(opts) > 1 and (
      select count(distinct (o ->> 'cost', o ->> 'price_net', o ->> 'price_gross', o ->> 'snapshot_confidence'))
      from jsonb_array_elements(opts) o) > 1 then
    return app.rpc_ok(
      jsonb_build_object('match', 'needs_location', 'menu_item_id', item_id, 'name', item_name,
        'locations', (select jsonb_agg(jsonb_build_object('location_id', o -> 'location_id', 'name', o -> 'name')
                                       order by o ->> 'name', o ->> 'location_id')
                      from jsonb_array_elements(opts) o)),
      locs, '[]', 100);
  end if;

  pick := opts -> 0;
  food := 100.0 * (pick ->> 'cost')::bigint / (pick ->> 'price_net')::bigint;
  if (pick ->> 'stale')::boolean then
    flags := flags || app.flag('stale_cost',
      format('Costo calculado al %s: no hay uno más reciente de este platillo (falta un precio o la receta).',
             to_char((pick ->> 'date')::date, 'DD/MM/YYYY')));
  end if;
  begin
    select coalesce(jsonb_agg(jsonb_build_object('ingredient', d.ingredient, 'share', app.pct(d.share))), '[]')
    into drivers
    from app.cost_drivers(item_id, (pick ->> 'date')::date) d;
  exception when sqlstate '54001' then
    drivers := '[]';  -- the recipe now nests more than 8 levels: no drivers, still the margin
  end;
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
      'cost_drivers', drivers),
    locs, flags, 100, array[(pick ->> 'date')::date, (pick ->> 'date')::date]);
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
         round(sum(c.net_ex_iva) filter (where c.cost is not null)) as covered_ex_iva,
         sum(c.net) as total_net,
         array_agg(distinct c.confidence) filter (where c.confidence is not null) as levels
  into x
  from app.item_cost_rows(locs, r[1], r[2]) c;
  if coalesce(x.covered_ex_iva, 0) <= 0 then
    return app.rpc_error('no_data', 'No costed dish sales for the period', locs);
  end if;

  if group_by = 'category' then
    select coalesce(jsonb_agg(jsonb_build_object('category', g.name, 'food_cost', app.pct(g.fc))
                              order by g.total_net desc, g.name), '[]')
    into categories
    from (
      select coalesce(mc.name, 'Sin categoría') as name, sum(c.net) as total_net,
             100 * sum(c.units * c.cost) filter (where c.cost is not null)
               / nullif(round(sum(c.net_ex_iva) filter (where c.cost is not null)), 0) as fc
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
      'theoretical', app.pct(100 * x.cost / x.covered_ex_iva),
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
           round(sum(x.net_ex_iva)) - sum(x.units * x.cost) as cm
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
-- `since` names where the window starts; it runs through today, never later (a price that starts
-- today is news; one that starts tomorrow is not yet), and meta.period_resolved says so. A
-- `since` that starts after today is invalid.
-- - Price moves: ingredients a live dish uses (the recipe of record of an active dish, through
--   its sub-recipes of record) whose price of record at the end of the window differs by at least
--   8 % (the lower threshold of the 03 alert table; its 30-day average and top-20-spend rules are
--   not applied yet) from the one the day before the window, in the order the new prices started.
-- - Breaches: dishes whose latest snapshot in the window is above target + 3 pts (03), the worst
--   location when several are asked; highest food cost first. The confidence flag is the
--   breaches' own (the snapshots they quote).
-- - Suggestions: open price_suggestion rows (status null, 'open' or 'pending'), computed by the
--   backend; the dish and its current price are given when `subject` is a dish id, or the name of
--   one active dish (or of the one priced at the location among several); otherwise no dish.
create function app.price_text(pesos numeric, unit app.base_unit) returns text
language sql immutable set search_path = ''
as $$
  select case unit
    when 'g' then app.fmt_money(round(pesos * 100000)) || '/kg'
    when 'ml' then app.fmt_money(round(pesos * 100000)) || '/L'
    else app.fmt_money(round(pesos * 100)) || '/pza'
  end
$$;

-- Ingredients the recipes of record of active dishes use on a day, through sub-recipes (the
-- engine's depth limit).
create function app.live_ingredients(on_date date) returns table (ingredient_id uuid)
language sql stable set search_path = ''
as $$
  with recursive used(recipe_id, depth) as (
    select app.recipe_of_record(m.id, null, on_date), 0 from public.menu_item m where m.is_active
    union
    select app.recipe_of_record(null, sr.produces_ingredient_id, on_date), u.depth + 1
    from used u
    join public.recipe_line rl on rl.recipe_id = u.recipe_id
    join public.recipe sr on sr.id = rl.sub_recipe_id
    where u.depth < 8
  )
  select distinct rl.ingredient_id from used u join public.recipe_line rl on rl.recipe_id = u.recipe_id
  where rl.ingredient_id is not null
$$;

-- The dish a suggestion's subject names: its id, or the one active dish with that name, or the
-- one of them priced at one of `locs` on the day; null otherwise (never an arbitrary pick).
create function app.subject_item(subject text, locs uuid[], on_date date) returns uuid
language sql stable set search_path = ''
as $$
  select coalesce(
    (select mi.id from public.menu_item mi where mi.id::text = lower(btrim(subject))),
    (select case when count(*) = 1 then min(x.id::text)
                 when count(*) filter (where x.priced) = 1 then min(x.id::text) filter (where x.priced) end::uuid
     from (select mi.id, exists (select 1 from unnest(locs) l where app.menu_price_on(mi.id, l, on_date) is not null) as priced
           from public.menu_item mi
           where mi.is_active and app.norm_name(mi.name) = app.norm_name(subject)) x))
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
  if r[1] > today then
    raise exception 'since must start on or before today' using errcode = '22023';
  end if;
  w_to := today;

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
    where o.unit_price_net > 0 and n.unit_price_net > 0 and n.effective_from >= r[1]
      and abs(n.unit_price_net - o.unit_price_net) >= 0.08 * o.unit_price_net
      and i.id in (select u.ingredient_id from app.live_ingredients(w_to) u)
  ) m;

  with latest as (
    select distinct on (s.menu_item_id, s.location_id) s.menu_item_id, s.cost, s.price_net, s.confidence
    from public.dish_cost_snapshot s
    where s.location_id = any (locs) and s.date between r[1] and w_to and s.price_net > 0
    order by s.menu_item_id, s.location_id, s.date desc
  ), worst as (
    select distinct on (l.menu_item_id) l.menu_item_id, 100.0 * l.cost / l.price_net as fc, l.confidence
    from latest l order by l.menu_item_id, 100.0 * l.cost / l.price_net desc
  )
  select coalesce((select jsonb_agg(jsonb_build_object('menu_item_id', b.menu_item_id, 'name', m.name,
                                                       'food_cost', app.pct(b.fc), 'target', app.pct(app.food_cost_target()))
                                    order by round(b.fc, 4) desc, m.name)
                   from worst b join public.menu_item m on m.id = b.menu_item_id
                   where b.fc > app.food_cost_target() + 3), '[]'),
         (select array_agg(distinct b.confidence) from worst b where b.fc > app.food_cost_target() + 3)
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
           case when m.id is not null and ps.loc is not null then app.menu_price_on(m.id, ps.loc, today) end as price
    from (select p.*, coalesce(p.location_id, get_cost_alerts.location_id) as loc from public.price_suggestion p) ps
    left join public.menu_item m
      on m.id = app.subject_item(ps.subject, case when ps.loc is not null then array[ps.loc] else locs end, today)
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
  app.menu_price_row(uuid, uuid, date), app.menu_price_on(uuid, uuid, date), app.net_ex_iva(numeric, numeric),
  app.cost_drivers(uuid, date), app.norm_name(text), app.price_text(numeric, app.base_unit),
  app.live_ingredients(date), app.subject_item(text, uuid[], date)
  to authenticated;
grant execute on function
  api.get_dish_margin(text, uuid), api.get_food_cost_pct(jsonb, uuid, text),
  api.get_menu_engineering(jsonb, uuid), api.get_cost_alerts(jsonb, uuid)
  to authenticated;
