-- MR-98: a location's normal closed weekdays (location.closed_weekdays, ISO 1=Mon .. 7=Sun) are
-- never missing days. An open day without sales is still flagged. Seed: El Güero, both locations
-- with daily and item sales every day from 2026-08-17 to 2026-10-11.
begin;
select * from no_plan();

\set CENTRO '705e8e51-376b-5785-adbb-405eff4e2a22'
\set POLANCO 'fdda5e3b-6bcd-5c48-a6de-f524be37463e'

-- Runs an RPC expression as a member with the given claims and business date.
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

\set OWNER '''{"tenant_id":"03299e41-28bd-5779-bcc6-0e5e76580fad","location_ids":null}'''
\set POLANCO_MGR '''{"tenant_id":"03299e41-28bd-5779-bcc6-0e5e76580fad","location_ids":["fdda5e3b-6bcd-5c48-a6de-f524be37463e"]}'''

-- the column and its check -------------------------------------------------------------------------
select is((select count(*) from public.location where closed_weekdays <> '{}'), 0::bigint,
          'seeded locations default to no closed days');
select col_not_null('public', 'location', 'closed_weekdays', 'closed_weekdays is not null');
select is((select convalidated from pg_constraint where conname = 'location_closed_weekdays_valid'), true,
          'the constraint is validated');
select ok(has_function_privilege('service_role', 'app.is_closed_weekdays(smallint[])', 'execute')
          and not has_function_privilege('authenticated', 'app.is_closed_weekdays(smallint[])', 'execute')
          and not has_function_privilege('anon', 'app.is_closed_weekdays(smallint[])', 'execute'),
          'only the backend (the one writer of location) can run the check');

select lives_ok(format('update public.location set closed_weekdays = %L where id = %L', v, :'CENTRO'),
                'accepts ' || v)
from unnest(array['{}', '{1}', '{6,7}', '{1,2,3,4,5,6}']) v;
select throws_ok(format('update public.location set closed_weekdays = %L where id = %L', v, :'CENTRO'),
                 '23514', null, 'refuses ' || v)
from unnest(array['{0}', '{8}', '{NULL}', '{1,1}', '{2,1}', '{1,2,3,4,5,6,7}', '{{1,2}}']) v;
select throws_ok(format('update public.location set closed_weekdays = null where id = %L', :'CENTRO'),
                 '23502', null, 'refuses null');
update public.location set closed_weekdays = '{}' where id = :'CENTRO';

-- open_location_days ------------------------------------------------------------------------------
update public.location set closed_weekdays = '{1}' where id = :'CENTRO';
select set_eq(format($$select day from app.open_location_days(array[%L, %L]::uuid[], '2026-10-05', '2026-10-11')
                       where location_id = %L$$, :'CENTRO', :'POLANCO', :'CENTRO'),
              $$select d::date from generate_series('2026-10-06'::date, '2026-10-11', '1 day') d$$,
              'Centro, closed on Monday, has no Monday');
select set_eq(format($$select day from app.open_location_days(array[%L, %L]::uuid[], '2026-10-05', '2026-10-11')
                       where location_id = %L$$, :'CENTRO', :'POLANCO', :'POLANCO'),
              $$select d::date from generate_series('2026-10-05'::date, '2026-10-11', '1 day') d$$,
              'Polanco keeps its Monday');
select is((select count(*) from app.open_location_days(array[:'CENTRO']::uuid[], '2026-10-11', '2026-10-05')), 0::bigint,
          'an empty range has no days');

-- get_data_status ---------------------------------------------------------------------------------
-- At 2026-10-15 the window is 09-15..10-14; the seed ends 10-11. Mondays in it: 09-21, 09-28, 10-05, 10-12.
update public.location set closed_weekdays = '{1}';
select is(pg_temp.rpc(:OWNER, 'api.get_data_status()', '2026-10-15') #> '{data,missing_business_days}',
          '["2026-10-13", "2026-10-14"]', 'both locations closed on Monday: 10-12 is not missing');
select is(pg_temp.rpc(:OWNER, 'api.get_data_status()', '2026-10-15') #> '{data,coverage}',
          '{"raw": 92.3077, "text": "92.3%"}', 'coverage: 48 of 52 open location-days');
update public.location set closed_weekdays = '{}' where id = :'POLANCO';
select is(pg_temp.rpc(:OWNER, 'api.get_data_status()', '2026-10-15') #> '{data,missing_business_days}',
          '["2026-10-12", "2026-10-13", "2026-10-14"]', 'only Centro closed on Monday: Polanco still misses 10-12');
select is(pg_temp.rpc(:OWNER, 'api.get_data_status()', '2026-10-15') #> '{data,coverage}',
          '{"raw": 91.0714, "text": "91.1%"}', 'coverage: 51 of 56 open location-days');

-- a manager scoped to one location sees only that location's days
update public.location set closed_weekdays = case when id = :'POLANCO' then '{1}'::smallint[] else '{}' end;
select is(pg_temp.rpc(:POLANCO_MGR, 'api.get_data_status()', '2026-10-15') #> '{data,missing_business_days}',
          '["2026-10-13", "2026-10-14"]', 'the Polanco manager does not see Centro''s open Monday');
select is(pg_temp.rpc(:POLANCO_MGR, 'api.get_data_status()', '2026-10-15') #>> '{data,coverage,text}',
          '92.3%', 'and gets Polanco''s coverage only (24 of 26)');
update public.location set closed_weekdays = '{}';

-- sales on a closed day still count, coverage stays within 100 -----------------------------------
update public.location set closed_weekdays = '{1}' where id = :'CENTRO';
select is((select row(s.net_sales, s.covered_days, s.expected_days, s.expected_covered)::text
           from app.sales_totals(array[:'CENTRO']::uuid[], '2026-10-05', '2026-10-11') s),
          (select row(sum(v.net_sales), 7, 6, 6)::text from app.v_daily_sales v
           where v.location_id = :'CENTRO' and v.business_date between '2026-10-05' and '2026-10-11'),
          'Centro sold on its closed Monday: the sales count, the coverage counts only its 6 open days');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO')) #>> '{meta,coverage_pct}',
          '100', 'and coverage stays at 100');
update public.location set closed_weekdays = '{}';

-- #98 done-when: a week whose only gap is the closed Monday ----------------------------------------
-- Centro has no sales on Mondays 09-28 and 10-05 (last_week 10-05..11, prev_week 09-28..10-04).
update public.import_batch b set status = 'rolled_back'
where b.id in (select d.batch_id from public.daily_sales_agg d where d.location_id = :'CENTRO' and d.business_date in ('2026-10-05', '2026-09-28')
               union select a.batch_id from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from in ('2026-10-05', '2026-09-28'));

update public.location set closed_weekdays = '{1}' where id = :'CENTRO';
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"last_week"')) -> 'flags', '[]',
          'closed on Monday: no missing_days and no previous_partial flag');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"last_week"')) #>> '{meta,coverage_pct}', '100',
          'and coverage is 100 (13 of 13 open location-days)');
select is(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L)', 'net_sales', '"last_week"', '"prev_week"')) -> 'flags', '[]',
          'compare_periods does not flag the closed Mondays');
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L)', '"last_week"', 'units')) -> 'flags', '[]',
          'get_top_dishes does not flag the closed Monday');

update public.location set closed_weekdays = '{}' where id = :'CENTRO';
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"last_week"')) -> 'flags',
          jsonb_build_array(
            app.flag('previous_partial', 'Faltan días en el periodo anterior: la comparación es aproximada.'),
            app.flag('missing_days', 'Faltan datos de 1 de 14 días del periodo.')),
          'open on Monday: the empty Mondays are flagged');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"last_week"')) #>> '{meta,coverage_pct}', '92.9',
          'and coverage is 13 of 14');
select is(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L)', 'net_sales', '"last_week"', '"prev_week"')) #>> '{flags,0,code}',
          'missing_days', 'compare_periods flags them');
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L)', '"last_week"', 'units')) #>> '{flags,0,code}',
          'missing_days', 'get_top_dishes flags them');

select * from finish();
rollback;
