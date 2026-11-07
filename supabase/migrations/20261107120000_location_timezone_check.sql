-- MR-98: a location's timezone must be a real IANA zone name. A bad one ('America/Mexico City')
-- makes app.business_today raise 22023, which the RPCs report to the owner as invalid_args.

-- A CHECK cannot hold a subquery, so the catalog lookup lives in a helper. It is declared
-- IMMUTABLE only so a CHECK may call it: the zone list ships with the Postgres install and changes
-- only on a server upgrade, and a stored row is never re-evaluated unless it is updated. Names
-- only: offsets like '+05' and '' are rejected (a fixed offset has no daylight-saving rules, and
-- the dashboards need a real place).
create function app.is_valid_timezone(tz text)
returns boolean
language sql immutable set search_path = ''
as $$
  select exists (select 1 from pg_catalog.pg_timezone_names n where n.name = tz)
$$;

revoke all on function app.is_valid_timezone(text) from public, anon;
grant execute on function app.is_valid_timezone(text) to service_role;

alter table public.location
  add constraint location_timezone_valid check (app.is_valid_timezone(timezone)) not valid;
alter table public.location validate constraint location_timezone_valid;

