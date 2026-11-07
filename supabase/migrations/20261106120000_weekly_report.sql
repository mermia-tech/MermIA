-- MR-34: api.build_weekly_report, everything the Monday report needs in one read-only call (C3
-- shape WeeklyReportData in packages/contracts rpc.py, registered in REPORT_RPCS, not an agent
-- tool). MR-38 renders and sends it; decisions W1-W4 in
-- docs/superpowers/plans/2026-11-06-mr-34-weekly-report.md.
--
-- - The week runs Monday to Sunday (W2) and must have ended: `last_week` (the default),
--   `prev_week` or an explicit {from, to}. Anything else is invalid_args.
-- - Each section is the read RPC the agent uses, called with the explicit week, so the report says
--   what the agent would say: sales and the change vs the previous week (W3), the top 3 dishes by
--   units, the food cost against the target, the cost alerts since the week's Monday (top 10 with
--   *_total; dishes over target = breaches_total) and the stale costs of today.
-- - missing_business_days: the days of the week a visible location has no sales data (W2: the
--   report goes out anyway and says so).
-- - Errors: a section error is one error envelope naming the section, except that no dish sales
--   gives top_dishes.rows = [] and no costed sales gives food_cost = null (a new tenant without
--   recipes still gets its report). No sales at all is no_data.
-- - Flags: every section's flags, first occurrence kept, no duplicates. meta.coverage_pct is the
--   sales coverage of the week.
-- Security invoker like every RPC: RLS decides the tenant and the locations (W1: a manager sees
-- only their location). It writes nothing.

-- The days of [f, t] on which at least one of the locations has no sales data (daily or item rows),
-- as in api.get_data_status.
create function app.missing_business_days(locs uuid[], f date, t date) returns jsonb
language sql stable set search_path = ''
as $$
  with covered as (
    select v.location_id, v.business_date from app.v_daily_sales v
    where v.location_id = any (locs) and v.business_date between f and t
    union
    select v.location_id, v.business_date from app.v_item_sales_daily v
    where v.location_id = any (locs) and v.business_date between f and t
  )
  select coalesce(jsonb_agg(d.day order by d.day), '[]')
  from (select g::date as day from generate_series(f, t, interval '1 day') g) d
  where exists (
    select 1 from unnest(locs) l(id)
    where not exists (select 1 from covered c where c.location_id = l.id and c.business_date = d.day))
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
  top jsonb;
  food jsonb;
  alerts jsonb;
  status jsonb;
  bad record;
  flags jsonb;
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  if period is null or jsonb_typeof(period) not in ('string', 'object')
     or (jsonb_typeof(period) = 'string' and period #>> '{}' not in ('last_week', 'prev_week')) then
    raise exception 'period must be last_week, prev_week or a Monday-to-Sunday {from, to}' using errcode = '22023';
  end if;
  today := app.business_today(location_id);
  r := app.resolve_period(period, today);
  if extract(isodow from r[1]) <> 1 or r[2] <> r[1] + 6 then
    raise exception 'the week must run Monday to Sunday' using errcode = '22023';
  end if;
  if r[2] >= today then
    raise exception 'the week has not ended yet' using errcode = '22023';
  end if;
  week := jsonb_build_object('from', r[1], 'to', r[2]);

  sales := api.get_sales_summary(week, location_id);
  top := api.get_top_dishes(week, 'units', 'desc', 3, location_id);
  food := api.get_food_cost_pct(week, location_id, 'none');
  alerts := api.get_cost_alerts(week, location_id);
  status := api.get_data_status(location_id);

  -- the first failing section decides the answer
  select s.name, s.env into bad
  from (values (1, 'sales', sales), (2, 'top_dishes', top), (3, 'food_cost', food),
               (4, 'cost_alerts', alerts), (5, 'data_status', status)) s(n, name, env)
  where not (s.env ->> 'ok')::boolean
    and not (s.name in ('top_dishes', 'food_cost') and s.env #>> '{error,code}' = 'no_data')
  order by s.n
  limit 1;
  if found then
    return app.rpc_error(bad.env #>> '{error,code}', bad.name || ': ' || (bad.env #>> '{error,message}'), locs);
  end if;

  select coalesce(jsonb_agg(f.flag order by f.first), '[]') into flags
  from (
    select e.flag, min(e.n) as first
    from jsonb_array_elements(sales -> 'flags' || (top -> 'flags') || (food -> 'flags') || (alerts -> 'flags'))
         with ordinality e(flag, n)
    group by e.flag
  ) f;

  return app.rpc_ok(
    jsonb_build_object(
      'week', week,
      'previous_week', jsonb_build_object('from', r[1] - 7, 'to', r[2] - 7),
      'sales', sales -> 'data',
      'top_dishes', case when (top ->> 'ok')::boolean then top -> 'data'
                         else jsonb_build_object('metric', 'units', 'rows', '[]'::jsonb) end,
      'food_cost', case when (food ->> 'ok')::boolean then food -> 'data' end,
      'cost_alerts', alerts -> 'data',
      'missing_business_days', app.missing_business_days(locs, r[1], r[2]),
      'stale_costs', status #> '{data,stale_costs}'),
    locs, flags, (sales #>> '{meta,coverage_pct}')::numeric, r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- Privileges ---------------------------------------------------------------------------------
-- Runs as the caller, like the section RPCs it calls.
revoke all on function app.missing_business_days(uuid[], date, date), api.build_weekly_report(jsonb, uuid)
  from public, anon;
grant execute on function app.missing_business_days(uuid[], date, date), api.build_weekly_report(jsonb, uuid)
  to authenticated;
