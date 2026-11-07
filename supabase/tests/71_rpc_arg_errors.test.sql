-- MR-98 (A1): get_sales_summary answers invalid_args only from its argument check. A 22023 raised
-- after it (the business date, a nested helper) is our fault or bad data, so it is internal.
begin;
select * from no_plan();

\set CENTRO '705e8e51-376b-5785-adbb-405eff4e2a22'

-- Runs an RPC expression as a member with the given claims and business date ('' = the real date).
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

-- bad arguments are still invalid_args ------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', p)) -> 'error',
          jsonb_build_object('code', 'invalid_args', 'message', 'invalid period: ' || p::jsonb::text),
          'invalid_args: ' || p)
from unnest(array['"nope"', '{"from":"2026-10-03","to":"2026-10-01"}', '{"from":"2026-10-01"}',
                  '{"from":"2025-01-01","to":"2026-10-01"}', '{"from":"2026-02-30","to":"2026-03-01"}', '5']) p;
select is(pg_temp.rpc(:OWNER, 'api.get_sales_summary(null)') #>> '{error,code}', 'invalid_args',
          'a null period is invalid_args');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_sales_summary(%L, %L)', '"nope"', :'CENTRO')) #>> '{error,code}',
          'not_found', 'a location out of scope is still not_found, before the period is checked');
select is(pg_temp.rpc(:OWNER, 'api.get_sales_summary(''"last_week"'')') ->> 'ok', 'true', 'a good period still answers');

-- a 22023 after the argument check is internal ----------------------------------------------------
-- Real path: a location time zone that a server tzdata upgrade no longer knows. The CHECK
-- (location_timezone_valid) keeps new rows out, so the old row is simulated by dropping it here.
-- No savepoints: rolling one back would also drop pgTAP's recorded results.
select timezone as centro_tz from public.location where id = :'CENTRO' \gset
alter table public.location drop constraint location_timezone_valid;
update public.location set timezone = 'Mars/Olympus' where id = :'CENTRO';
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO'), '') -> 'error',
          '{"code":"internal","message":"time zone \"Mars/Olympus\" not recognized"}'::jsonb,
          'an unknown location time zone is internal, not invalid_args');
select is(pg_temp.rpc(:OWNER, 'api.get_sales_summary(''"last_week"'')', '') #>> '{error,code}', 'internal',
          'also for the whole business, whose business date is the first location''s');
update public.location set timezone = :'centro_tz' where id = :'CENTRO';
alter table public.location add constraint location_timezone_valid check (app.is_valid_timezone(timezone));

-- Nested path: a helper of the body raises 22023 after the period passed (the final rollback
-- restores the helper).
create or replace function app.sales_totals(locs uuid[], f date, t date)
returns table (net_sales bigint, tickets bigint, guests bigint, discounts bigint, cancellations bigint,
               covered_days int, item_only_days int, expected_days int, expected_covered int)
language plpgsql stable set search_path = '' as $$
begin
  raise exception 'sales totals failed' using errcode = '22023';
end $$;
select is(pg_temp.rpc(:OWNER, 'api.get_sales_summary(''"last_week"'')') -> 'error',
          '{"code":"internal","message":"sales totals failed"}'::jsonb,
          'a 22023 inside a nested helper is internal');
select is(pg_temp.rpc(:OWNER, 'api.get_sales_summary(''"nope"'')') #>> '{error,code}', 'invalid_args',
          'while a bad period is still invalid_args');
select is((pg_temp.rpc(:OWNER, 'api.get_sales_summary(''"last_week"'')') -> 'meta') ? 'as_of', true,
          'an internal error still carries meta.as_of');

select * from finish();
rollback;
