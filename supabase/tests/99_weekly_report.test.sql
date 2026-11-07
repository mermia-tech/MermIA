-- MR-34: api.build_weekly_report on the El Güero seed, after the backend's cost job and the alert
-- evaluation of 2026-10-12 (as the Monday job would run them), called as `authenticated`.
begin;
select * from no_plan();

\set TENANT '03299e41-28bd-5779-bcc6-0e5e76580fad'
\set CENTRO '705e8e51-376b-5785-adbb-405eff4e2a22'
\set POLANCO 'fdda5e3b-6bcd-5c48-a6de-f524be37463e'

create function pg_temp.rpc(claims text, expr text, today text default '2026-10-12') returns jsonb
language plpgsql as $$
declare r jsonb;
begin
  execute 'set local role authenticated';
  perform set_config('request.jwt.claims', claims, true);
  perform set_config('app.today', today, true);
  execute 'select ' || expr into r;
  reset role;
  return r;
end $$;

create function pg_temp.writes() returns bigint
language sql as $$
  select (select count(*) from public.alert) + (select count(*) from public.price_suggestion)
       + (select count(*) from public.report_run) + (select count(*) from public.audit_log)
       + (select count(*) from public.dish_cost_snapshot)
$$;

\set OWNER '''{"tenant_id":"03299e41-28bd-5779-bcc6-0e5e76580fad","location_ids":null}'''
\set POLANCO_MGR '''{"tenant_id":"03299e41-28bd-5779-bcc6-0e5e76580fad","location_ids":["fdda5e3b-6bcd-5c48-a6de-f524be37463e"]}'''
\set OTHER '''{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000009","location_ids":null}'''
\set WEEK '''{"from":"2026-10-05","to":"2026-10-11"}'''

-- the function --------------------------------------------------------------------------------
select ok(not (select prosecdef from pg_proc where oid = 'api.build_weekly_report(jsonb, uuid)'::regprocedure),
          'security invoker: RLS decides the tenant and the locations');
select is((select provolatile from pg_proc where oid = 'api.build_weekly_report(jsonb, uuid)'::regprocedure), 's',
          'stable: a read-only call');
select ok(has_function_privilege('authenticated', 'api.build_weekly_report(jsonb, uuid)', 'execute'), 'members run it');
select ok(not has_function_privilege('anon', 'api.build_weekly_report(jsonb, uuid)', 'execute'), 'anon does not');

-- the backend's jobs, as on Monday 2026-10-12 ------------------------------------------------------
select ok(app.compute_dish_costs(:'TENANT', '2026-09-01', '2026-10-12') > 0, 'dish costs computed');
set local role service_role;
select ok(app.evaluate_cost_alerts(:'TENANT', '2026-10-12', '2026-10-12') > 0, 'alerts and suggestions evaluated');
reset role;

create temp table report as
select pg_temp.writes() as before, pg_temp.rpc(:OWNER, 'api.build_weekly_report()') as r;

-- owner, last week ------------------------------------------------------------------------------
select is((select r ->> 'ok' from report), 'true', 'the owner gets the report');
select is((select pg_temp.writes() - before from report), 0::bigint, 'no rows written');
select is((select r #> '{data,week}' from report), :WEEK::jsonb, 'last_week is Monday 10-05 to Sunday 10-11');
select is((select r #> '{data,previous_week}' from report), '{"from":"2026-09-28","to":"2026-10-04"}'::jsonb,
          'the previous week is the week before (W3)');
select is((select r #> '{meta,period_resolved}' from report), :WEEK::jsonb, 'meta names the week');
select is((select r #> '{data,sales,net_sales,raw}' from report), '34524130'::jsonb,
          'net sales: Centro 18,432,050 + Polanco 16,092,080');
select is((select r #>> '{data,sales,change_vs_previous,text}' from report), '+3.5%', '+3.5 % vs 33,352,460 the week before');

select is((select r #> '{data,sales}' from report),
          pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', :WEEK)) -> 'data', 'sales = get_sales_summary of the week');
select is((select r #> '{data,top_dishes}' from report),
          pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, ''units'', ''desc'', 3)', :WEEK)) -> 'data',
          'top dishes = get_top_dishes of the week, top 3 by units');
select is((select r #> '{data,food_cost}' from report),
          pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L)', :WEEK)) -> 'data', 'food cost = get_food_cost_pct of the week');
select is((select r #> '{data,cost_alerts}' from report),
          pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L)', :WEEK)) -> 'data', 'cost alerts = get_cost_alerts since the Monday');
select is((select r #> '{data,stale_costs}' from report),
          pg_temp.rpc(:OWNER, 'api.get_data_status()') #> '{data,stale_costs}', 'stale costs = get_data_status');
select is((select r #> '{data,missing_business_days}' from report), '[]'::jsonb, 'no day of the week is missing');
select is((select r #> '{data,cost_alerts,breaches_total}' from report), '9'::jsonb, 'dishes over target: 9');
select is((select count(*) from report, jsonb_array_elements(r -> 'flags') f group by f order by 1 desc limit 1), 1::bigint,
          'no flag twice');
select is(pg_temp.rpc(:OWNER, format('api.build_weekly_report(%L)', :WEEK)) #- '{meta,as_of}',
          (select r #- '{meta,as_of}' from report), 'the named week and its explicit range answer the same');

-- RLS (W1) ----------------------------------------------------------------------------------------
select is(pg_temp.rpc(:POLANCO_MGR, 'api.build_weekly_report()') #> '{data,sales,net_sales,raw}', '16092080'::jsonb,
          'a Polanco manager gets Polanco only');
select is((select count(*) from jsonb_array_elements(pg_temp.rpc(:POLANCO_MGR, 'api.build_weekly_report()') #> '{data,cost_alerts,suggestions}') s
           where s ->> 'location_id' <> :'POLANCO'), 0::bigint, 'and only Polanco suggestions');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.build_weekly_report(location_id => %L)', :'CENTRO')) #>> '{error,code}', 'not_found',
          'nor Centro by asking for it');
select is(pg_temp.rpc(:OWNER, format('api.build_weekly_report(location_id => %L)', :'CENTRO')) #> '{data,sales,net_sales,raw}',
          '18432050'::jsonb, 'the owner can ask for one location');
select is(pg_temp.rpc(:OTHER, 'api.build_weekly_report()') #- '{meta,as_of}',
          '{"ok":false,"error":{"code":"no_data","message":"sales: No sales loaded for the period"},"flags":[],"meta":{}}'::jsonb,
          'another tenant sees nothing');
select is(pg_temp.rpc(:OTHER, format('api.build_weekly_report(location_id => %L)', :'CENTRO')) #>> '{error,code}', 'not_found',
          'nor El Güero''s locations');

-- arguments ---------------------------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, 'api.build_weekly_report(''"prev_week"'')') #> '{data,week}', '{"from":"2026-09-28","to":"2026-10-04"}'::jsonb,
          'prev_week is the week before');
select is(pg_temp.rpc(:OWNER, format('api.build_weekly_report(%L)', p)) #>> '{error,code}', 'invalid_args', 'rejects ' || p)
from unnest(array['"this_week"', '"last_7d"', '7', '{"from":"2026-10-06","to":"2026-10-12"}',
                  '{"from":"2026-09-28","to":"2026-10-11"}', '{"from":"2026-10-12","to":"2026-10-18"}']) p;
select is(pg_temp.rpc(:OWNER, 'api.build_weekly_report(null)') #>> '{error,code}', 'invalid_args', 'rejects a null period');

-- the week of the aguacate jump (09-29) -------------------------------------------------------------
select is((select jsonb_agg(m ->> 'ingredient')
           from jsonb_array_elements(pg_temp.rpc(:OWNER, 'api.build_weekly_report(''"prev_week"'')') #> '{data,cost_alerts,price_moves}') m),
          '["Aguacate Hass"]'::jsonb, 'the week of 09-28 shows the aguacate jump');

-- a missing Sunday (W2): the report still goes out and names the day ----------------------------------
delete from public.daily_sales_agg where location_id = :'POLANCO' and business_date = '2026-10-11';
delete from public.item_sales_agg where location_id = :'POLANCO' and period_from = '2026-10-11';
select is(pg_temp.rpc(:OWNER, 'api.build_weekly_report()') #> '{data,missing_business_days}', '["2026-10-11"]'::jsonb,
          'Polanco''s Sunday is missing');
select is((select count(*) from jsonb_array_elements(pg_temp.rpc(:OWNER, 'api.build_weekly_report()') -> 'flags') f
           where f ->> 'code' = 'missing_days'), 1::bigint, 'one missing_days flag, not one per section');

-- no costed sales: food cost is null, the report still goes out ------------------------------------
delete from public.dish_cost_snapshot where date between '2026-10-05' and '2026-10-11';
select is(pg_temp.rpc(:OWNER, 'api.build_weekly_report()') #> '{data,food_cost}', 'null'::jsonb, 'no costs: food_cost is null');
select is(pg_temp.rpc(:OWNER, 'api.build_weekly_report()') ->> 'ok', 'true', 'and the report is still ok');

-- no dish sales: top dishes is empty --------------------------------------------------------------
delete from public.item_sales_agg where period_from between '2026-10-05' and '2026-10-11';
delete from public.sale_line l using public.sale_ticket t
where t.id = l.ticket_id and t.business_date between '2026-10-05' and '2026-10-11';
select is(pg_temp.rpc(:OWNER, 'api.build_weekly_report()') #> '{data,top_dishes}', '{"metric":"units","rows":[]}'::jsonb,
          'no dish sales: no top dishes');

select * from finish();
rollback;
