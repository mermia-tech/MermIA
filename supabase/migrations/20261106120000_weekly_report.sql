-- MR-34: api.build_weekly_report, everything the Monday report needs in one read-only call (C3
-- shape WeeklyReportData in packages/contracts rpc.py, registered in REPORT_RPCS, not an agent
-- tool). MR-38 renders and sends it; decisions W1-W4 in
-- docs/superpowers/plans/2026-11-06-mr-34-weekly-report.md.
--
-- - The week runs Monday to Sunday (W2) and must have ended: `last_week` (the default),
--   `prev_week` or an explicit {from, to}. Anything else is invalid_args.
-- - Each section is the read RPC the agent uses, called with the explicit week, so the report says
--   what the agent would say: sales and the change vs the previous week (W3), the top 3 dishes by
--   units, the food cost against the target and the stale costs of today. Sales is
--   get_sales_summary itself; top dishes, food cost and the missing days come from one read of the
--   week's item sales (app.report_item_sections, the same rows and rules as get_top_dishes and
--   get_food_cost_pct), and the stale costs from app.stale_costs, get_data_status' count (MR-98:
--   about 0.5 s less for a heavy tenant). 99_weekly_report pins each section to its RPC.
-- - cost_alerts: get_cost_alerts' shape (top 10 with *_total; dishes over target =
--   breaches_total) from app.cost_alerts, with price moves and breaches over the week only (a price
--   dated after Sunday does not change last week's report) and the suggestions as of today; each
--   breach lists the locations where it is over target, with cost, prices and the suggestion
--   priced on those figures, for [Ver márgenes] (W4).
-- - locations: the locations in scope with their names, to label breaches and suggestions.
-- - missing_business_days: the days of the week a visible location has no sales data (W2: the
--   report goes out anyway and says so).
-- - Errors: a section error is one error envelope naming the section, except that no dish sales
--   gives top_dishes.rows = [] and no costed sales gives food_cost = null (a new tenant without
--   recipes still gets its report). No sales at all is no_data. Only the argument checks answer
--   invalid_args (MR-98 A1): past them the week is valid, so a 22023 raised later, or a section
--   answering invalid_args to that week, is internal (our data or our bug, not the caller's).
-- - Flags: every section's flags, first occurrence kept, no duplicates. meta.coverage_pct is the
--   sales coverage of the week.
-- Security invoker like every RPC: RLS decides the tenant and the locations (W1: a manager sees
-- only their location). It writes nothing.

-- The ingredients used by a recipe in effect on `today` whose newest price is older than 45 days
-- (03 C.3), or that have no price: get_data_status' stale_costs, which the report shows too (MR-98
-- P1: the report no longer runs get_data_status' 30-day scans for this one count). Ingredients and
-- recipes belong to the tenant, not to a location, so it takes no locations; RLS scopes the tenant.
create function app.stale_costs(today date) returns bigint
language sql stable set search_path = ''
as $$
  select count(*)
  from public.ingredient i
  where exists (
      select 1 from public.recipe_line rl join public.recipe rc on rc.id = rl.recipe_id
      where rl.ingredient_id = i.id
        and (rc.effective_from is null or rc.effective_from <= today)
        and (rc.effective_to is null or rc.effective_to >= today))
    and coalesce((select max(p.effective_from) from public.ingredient_price p
                  where p.ingredient_id = i.id and p.effective_from <= today), '-infinity') < today - 45
$$;

-- get_data_status with its stale-cost count from app.stale_costs (MR-98 P1), otherwise word for
-- word 20261019200000_read_rpcs_first4.sql (merged, so it is replaced here): the same answer.
create or replace function api.get_data_status(location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  sources jsonb;
  missing jsonb;
  stale bigint;
  s record;
  coverage numeric;
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  today := app.business_today(location_id);

  select coalesce(jsonb_agg(jsonb_build_object('source_kind', k.kind, 'last_batch_at', k.last_at) order by k.kind), '[]')
  into sources
  from (
    select src.kind, max(b.applied_at) filter (where b.status = 'applied') as last_at
    from public.source src
    left join public.import_batch b on b.tenant_id = src.tenant_id and b.source_id = src.id
      and (b.location_id = any (locs) or b.location_id is null)
    where src.location_id = any (locs) or src.location_id is null
    group by src.kind
  ) k;

  with covered as (
    select v.location_id, v.business_date from app.v_daily_sales v
    where v.location_id = any (locs) and v.business_date between today - 30 and today - 1
    union
    select v.location_id, v.business_date from app.v_item_sales_daily v
    where v.location_id = any (locs) and v.business_date between today - 30 and today - 1
  )
  select coalesce(jsonb_agg(d.day order by d.day), '[]') into missing
  from (select g::date as day from generate_series(today - 30, today - 1, interval '1 day') g) d
  where exists (
    select 1 from unnest(locs) l(id)
    where not exists (select 1 from covered c where c.location_id = l.id and c.business_date = d.day));

  stale := app.stale_costs(today);

  select * into s from app.sales_totals(locs, today - 30, today - 1);
  coverage := round(100.0 * s.expected_covered / nullif(s.expected_days, 0), 4);

  return app.rpc_ok(
    jsonb_build_object(
      'sources', sources,
      'missing_business_days', missing,
      'stale_costs', stale,
      'coverage', jsonb_build_object('raw', trim_scale(coalesce(coverage, 0)), 'text', app.fmt_pct(coalesce(coverage, 0)))),
    locs, '[]', null, null);
end
$$;

-- Three report sections from one read of the week's item sales (MR-98 P3/P4; app.item_cost_rows
-- has one row per app.item_rows row, the same sales and snapshot join plus the day's IVA rate):
-- - top_rows: get_top_dishes(week, 'units', 'desc', 3)'s rows; null when no dish sold (its no_data);
-- - food: get_food_cost_pct(week)'s data (group_by 'none'); null when no costed sales (its no_data);
--   food_flags: its confidence flag (its missing_days flag is the sales section's, the same text);
-- - missing: the days of [f, t] on which a location has no sales data (daily or item rows), the
--   rule of get_data_status.
-- The report used to call the two RPCs and a helper, which read the week four more times.
create function app.report_item_sections(locs uuid[], f date, t date)
returns table (top_rows jsonb, food jsonb, food_flags jsonb, missing jsonb)
language sql stable set search_path = ''
as $$
  with c as materialized (
    select * from app.item_cost_rows(locs, f, t)
  ), ranked as (
    select u.menu_item_id, u.name, u.value,
           row_number() over (order by u.value desc nulls last, u.name, u.menu_item_id) as rank
    from (select c.menu_item_id, m.name, sum(c.units) as value
          from c join public.menu_item m on m.id = c.menu_item_id
          group by c.menu_item_id, m.name) u
    where u.value is not null
  ), x as (
    select sum(c.units * c.cost) filter (where c.cost is not null) as cost,
           sum(c.net) filter (where c.cost is not null) as covered_net,
           round(sum(c.net_ex_iva) filter (where c.cost is not null)) as covered_ex_iva,
           sum(c.net) as total_net,
           array_agg(distinct c.confidence) filter (where c.confidence is not null) as levels
    from c
  ), covered as (
    select v.location_id, v.business_date from app.v_daily_sales v
    where v.location_id = any (locs) and v.business_date between f and t
    union
    select c.location_id, c.day from c
  )
  select
    (select jsonb_agg(jsonb_build_object('rank', k.rank, 'menu_item_id', k.menu_item_id, 'name', k.name,
                                         'value', app.figure('units', k.value)) order by k.rank)
     from ranked k where k.rank <= 3),
    case when coalesce(x.covered_ex_iva, 0) > 0 then jsonb_build_object(
      'theoretical', app.pct(100 * x.cost / x.covered_ex_iva),
      'target', app.pct(app.food_cost_target()),
      'coverage', app.pct(100.0 * x.covered_net / x.total_net),
      'by_category', '[]'::jsonb) end,
    case when coalesce(x.covered_ex_iva, 0) > 0 then coalesce('[]'::jsonb || app.confidence_flag(x.levels), '[]') else '[]' end,
    (select coalesce(jsonb_agg(d.day order by d.day), '[]')
     from (select g::date as day from generate_series(f, t, interval '1 day') g) d
     where exists (
       select 1 from unnest(locs) l(id)
       where not exists (select 1 from covered v where v.location_id = l.id and v.business_date = d.day)))
  from x
$$;

-- The target price app.write_price_suggestions gives a cost at a menu price and IVA rate (its
-- app.suggest_menu_price call). The formula stays the backend's; members get only this number, a
-- pure function of its arguments (security definer reads nothing).
create function app.suggestion_target_price(cost bigint, price_gross bigint, tax_rate numeric)
returns bigint
language sql stable security definer set search_path = ''
as $$
  select f.target_price from app.suggest_menu_price(cost, price_gross, tax_rate, app.food_cost_target()) f
$$;

-- One location of a report breach ([Ver márgenes], WeeklyBreachAt): the dish's latest snapshot of
-- the week there (cost, net price, food cost, confidence), the menu price with IVA that day, and
-- its suggestion from `shown` only when it is priced on these figures: the dish's latest snapshot
-- up to `today` has the same cost and net price (no price dated after Sunday re-costed it), the
-- suggestion's current price is this menu price and its target price is the one this cost gives
-- (app.suggestion_target_price on the menu price row of `d`: a price dated inside the week
-- that landed after the evaluation re-costs the dish but leaves an open or pending row priced on
-- the old cost). Otherwise null; it stays in `suggestions`.
create function app.breach_at(item uuid, loc uuid, d date, snap_cost bigint, snap_net bigint,
                              snap_confidence app.cost_confidence, today date, shown jsonb)
returns jsonb
language sql stable security invoker set search_path = ''
as $$
  with gross as (
    select r.price_gross as price, app.suggestion_target_price(snap_cost, r.price_gross, r.tax_rate) as target_price
    from (select) one
    left join app.menu_price_row(item, loc, d) r on true
  )
  select jsonb_build_object(
    'location_id', loc,
    'cost', app.money(snap_cost),
    'net_price', app.money(snap_net),
    'price_gross', app.money(g.price),
    'food_cost', app.pct(100.0 * snap_cost / snap_net),
    'confidence', snap_confidence,
    'suggestion', (
      select s from jsonb_array_elements(shown) s
      where s ->> 'menu_item_id' = item::text and s ->> 'location_id' = loc::text
        and (s #>> '{current_price,raw}')::bigint = g.price
        and (s #>> '{target_price,raw}')::bigint = g.target_price
        and (select (x.cost, x.price_net) = (snap_cost, snap_net)
             from public.dish_cost_snapshot x
             where x.location_id = loc and x.menu_item_id = item and x.date between d and today
             order by x.date desc limit 1)))
  from gross g
$$;

-- The cost alerts of the locations, as get_cost_alerts lists them, returned as {data, flags}:
-- - price moves and breaches over [f, t] (the ingredient prices of record up to t, the dish
--   snapshots of [f, t]);
-- - suggestions as of `today`: the rows evaluated from f to today that are still open (or pending)
--   and fresh today, at today's menu price, whose dish's latest snapshot up to today still
--   breaches (the rules of 20261106110000_price_suggestions.sql).
-- get_cost_alerts is t = today. The weekly report passes the week's Sunday as t, so a price dated
-- after Sunday never moves last week's figures (the 9:00 and the 12:00 report agree), and
-- `detailed`: each breach also gets `at`, one app.breach_at per location in scope where the dish
-- is over target, worst first ([Ver márgenes], doc 12 1b). The agent's breaches stay compact
-- (doc 13).
create function app.cost_alerts(locs uuid[], f date, t date, today date, detailed boolean default false)
returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  top_n int := app.cost_alerts_top_n();
  moves jsonb;
  moves_total int;
  breaches jsonb;
  breaches_total int;
  shown jsonb;
  levels app.cost_confidence[];
  flags jsonb := '[]';
  breach_above numeric := app.food_cost_target() + (select s.breach_pts from app.cost_alert_settings() s);
begin
  with moved as (
    select i.name, i.base_unit, cur.unit_price_net as new_price, j.started,
           100 * (cur.unit_price_net - coalesce(nullif(pre.unit_price_net, 0), j.first_old))
             / coalesce(nullif(pre.unit_price_net, 0), j.first_old) as change_pct
    from (select x.ingredient_id, max(x.started) as started,
                 (array_agg(x.old_unit_price order by x.started))[1] as first_old
          from app.price_jumps((select app.current_tenant_id()), f, t) x
          group by x.ingredient_id) j
    join public.ingredient i on i.id = j.ingredient_id
    cross join lateral app.price_of_record(j.ingredient_id, t) cur
    left join lateral app.price_of_record(j.ingredient_id, f - 1) pre on true
    where cur.unit_price_net > 0
  ), ranked as (
    select m.*, row_number() over (order by abs(m.change_pct) desc, m.name) as n
    from moved m
    where abs(m.change_pct) >= (select s.jump_vs_avg_pct from app.cost_alert_settings() s)
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'ingredient', m.name,
           'change', app.pct(m.change_pct, true),
           'new_unit_price', jsonb_build_object('raw', trim_scale(m.new_price), 'base_unit', m.base_unit,
                                                'text', app.price_text(m.new_price, m.base_unit)))
         order by m.started, m.name) filter (where m.n <= top_n), '[]'),
         count(*)
  into moves, moves_total
  from ranked m;

  -- every suggestion shown, highest value first (the listed ones are the first top_n)
  with shown as (
    select x.*, m.name
    from (
      select distinct on (p.location_id, p.menu_item_id) p.*
      from public.price_suggestion p
      where p.location_id = any (locs) and p.as_of between f and today
      order by p.location_id, p.menu_item_id, p.as_of desc, p.id desc
    ) x
    join public.menu_item m on m.id = x.menu_item_id
    where x.status in ('open', 'pending')
      and (x.status = 'pending' or not exists (
             select 1 from public.price_suggestion d
             where d.tenant_id = x.tenant_id and d.location_id = x.location_id and d.menu_item_id = x.menu_item_id
               and d.status <> 'open' and d.episode_start >= x.episode_start
               and not app.suggestion_reopens(d.current_price, d.suggested_price, x.current_price, x.suggested_price)))
      -- an open row only while fresh: evaluated on or after the dish's latest snapshot (the evaluator
      -- ran since) and within the writer's observation week (a dish no longer costed shows nothing)
      and (x.status = 'pending' or (
             x.as_of > today - (select k.observation_days from app.price_suggestion_settings() k)
             and x.as_of >= (select max(s.date) from public.dish_cost_snapshot s
                             where s.location_id = x.location_id and s.menu_item_id = x.menu_item_id
                               and s.date <= today)))
      and x.current_price = app.menu_price_on(x.menu_item_id, x.location_id, today)
      and (select 100.0 * s.cost / s.price_net > breach_above
           from public.dish_cost_snapshot s
           where s.location_id = x.location_id and s.menu_item_id = x.menu_item_id
             and s.date between f and today and s.price_net > 0
           order by s.date desc limit 1)
  ), ranked as (
    select x.*, row_number() over (order by x.value desc, x.name, x.location_id) as n from shown x
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'menu_item_id', x.menu_item_id,
           'location_id', x.location_id,
           'name', x.name,
           'current_price', app.money(x.current_price),
           'target_price', app.money(x.target_price),
           'suggested_price', case when x.suggested_price is not null then app.money(x.suggested_price) end,
           'change', case when x.suggested_price is not null
                          then app.pct(100.0 * (x.suggested_price - x.current_price) / x.current_price, true) end,
           'new_food_cost', case when x.new_food_cost_pct is not null then app.pct(x.new_food_cost_pct) end,
           'confidence', x.confidence,
           'rationale_code', x.rationale_code)
         order by x.n), '[]')
  into shown
  from ranked x;

  with latest as (
    select distinct on (s.menu_item_id, s.location_id) s.menu_item_id, s.location_id, s.date, s.cost, s.price_net,
           s.confidence
    from public.dish_cost_snapshot s
    where s.location_id = any (locs) and s.date between f and t and s.price_net > 0
    order by s.menu_item_id, s.location_id, s.date desc
  ), located as (
    -- k = 1 is the dish's worst location
    select l.*, 100.0 * l.cost / l.price_net as fc,
           row_number() over (partition by l.menu_item_id order by 100.0 * l.cost / l.price_net desc, l.location_id) as k
    from latest l
  ), ranked as (
    select b.*, m.name, row_number() over (order by round(b.fc, 4) desc, m.name, b.menu_item_id) as n
    from located b join public.menu_item m on m.id = b.menu_item_id
    where b.k = 1 and b.fc > breach_above
  )
  -- the top N by food cost; the confidence covers every breach, listed or not (in the report,
  -- every location over target)
  select coalesce(jsonb_agg(
           jsonb_build_object('menu_item_id', b.menu_item_id, 'name', b.name,
                              'food_cost', app.pct(b.fc), 'target', app.pct(app.food_cost_target()))
           || case when detailed then jsonb_build_object('at', (
                select jsonb_agg(app.breach_at(o.menu_item_id, o.location_id, o.date, o.cost, o.price_net, o.confidence,
                                               today, shown) order by o.k)
                from located o
                where o.menu_item_id = b.menu_item_id and o.fc > breach_above and o.k <= top_n))
              else '{}' end
           order by b.n) filter (where b.n <= top_n), '[]'),
         count(*),
         case when detailed then (select array_agg(distinct o.confidence) from located o where o.fc > breach_above)
              else array_agg(distinct b.confidence) end
  into breaches, breaches_total, levels
  from ranked b;

  if breaches <> '[]' then
    flags := flags || app.confidence_flag(levels);
  end if;
  return jsonb_build_object(
    'data', jsonb_build_object(
      'price_moves', moves, 'price_moves_total', moves_total, 'breaches', breaches,
      'breaches_total', breaches_total,
      'suggestions', (select coalesce(jsonb_agg(s order by i), '[]')
                      from jsonb_array_elements(shown) with ordinality x(s, i) where i <= top_n),
      'suggestions_total', jsonb_array_length(shown)),
    'flags', flags);
end
$$;

-- get_cost_alerts on the shared body, up to today: the same answer as in
-- 20261106110000_price_suggestions.sql (its tests and examples pin it).
create or replace function api.get_cost_alerts(since jsonb default '"last_7d"', location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  r date[];
  alerts jsonb;
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  today := app.business_today(location_id);
  r := app.resolve_period(coalesce(since, '"last_7d"'), today);
  if r[1] > today then
    raise exception 'since must start on or before today' using errcode = '22023';
  end if;
  alerts := app.cost_alerts(locs, r[1], today, today);
  return app.rpc_ok(alerts -> 'data', locs, alerts -> 'flags', null, array[r[1], today]);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

create function api.build_weekly_report(period jsonb default '"last_week"', location_id uuid default null)
returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  r date[];
  week jsonb;
  sales jsonb;
  items record;
  alerts jsonb;
  flags jsonb;
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  today := app.business_today(location_id);
  -- the arguments: a 22023 here is the caller's
  begin
    if period is null or jsonb_typeof(period) not in ('string', 'object')
       or (jsonb_typeof(period) = 'string' and period #>> '{}' not in ('last_week', 'prev_week')) then
      raise exception 'period must be last_week, prev_week or a Monday-to-Sunday {from, to}' using errcode = '22023';
    end if;
    r := app.resolve_period(period, today);
    if extract(isodow from r[1]) <> 1 or r[2] <> r[1] + 6 then
      raise exception 'the week must run Monday to Sunday' using errcode = '22023';
    end if;
    if r[2] >= today then
      raise exception 'the week has not ended yet' using errcode = '22023';
    end if;
  exception when sqlstate '22023' then
    return app.rpc_error('invalid_args', sqlerrm, locs);
  end;
  week := jsonb_build_object('from', r[1], 'to', r[2]);

  -- the week is valid now, so a section rejecting it is our fault, not the caller's
  sales := api.get_sales_summary(week, location_id);
  if not (sales ->> 'ok')::boolean then
    return app.rpc_error(case when sales #>> '{error,code}' = 'invalid_args' then 'internal' else sales #>> '{error,code}' end,
                         'sales: ' || (sales #>> '{error,message}'), locs);
  end if;
  select * into items from app.report_item_sections(locs, r[1], r[2]);
  alerts := app.cost_alerts(locs, r[1], r[2], today, true);

  -- every section's flags, first occurrence kept (top dishes' and food cost's missing_days flag is
  -- the sales section's)
  select coalesce(jsonb_agg(f.flag order by f.first), '[]') into flags
  from (
    select e.flag, min(e.n) as first
    from jsonb_array_elements(sales -> 'flags' || items.food_flags || (alerts -> 'flags')) with ordinality e(flag, n)
    group by e.flag
  ) f;

  return app.rpc_ok(
    jsonb_build_object(
      'week', week,
      'previous_week', jsonb_build_object('from', r[1] - 7, 'to', r[2] - 7),
      'locations', (select jsonb_agg(jsonb_build_object('location_id', l.id, 'name', l.name) order by l.name, l.id)
                    from public.location l where l.id = any (locs)),
      'sales', sales -> 'data',
      'top_dishes', jsonb_build_object('metric', 'units', 'rows', coalesce(items.top_rows, '[]')),
      'food_cost', items.food,
      'cost_alerts', alerts -> 'data',
      'missing_business_days', items.missing,
      'stale_costs', app.stale_costs(today)),
    locs, flags, (sales #>> '{meta,coverage_pct}')::numeric, r);
exception when sqlstate '22023' then
  -- past the argument checks: bad data or a bug of ours (a bad location time zone, a section)
  return app.rpc_error('internal', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- Privileges ---------------------------------------------------------------------------------
-- Runs as the caller, like the section RPCs it calls.
revoke all on function app.stale_costs(date), app.report_item_sections(uuid[], date, date), app.cost_alerts(uuid[], date, date, date, boolean),
  app.suggestion_target_price(bigint, bigint, numeric), app.breach_at(uuid, uuid, date, bigint, bigint, app.cost_confidence, date, jsonb),
  api.build_weekly_report(jsonb, uuid)
  from public, anon;
grant execute on function app.stale_costs(date), app.report_item_sections(uuid[], date, date), app.cost_alerts(uuid[], date, date, date, boolean),
  app.suggestion_target_price(bigint, bigint, numeric), app.breach_at(uuid, uuid, date, bigint, bigint, app.cost_confidence, date, jsonb),
  api.build_weekly_report(jsonb, uuid)
  to authenticated;
