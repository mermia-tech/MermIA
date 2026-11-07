-- MR-98: a location's normal closed weekdays are never reported as missing days.
-- Owner decisions (2026-11-07): the owner sets each location's normally closed weekdays at
-- onboarding; an open day without sales is still flagged; no holidays or one-off closures for now;
-- a change applies to every week (no history is kept).
--
-- location.closed_weekdays holds ISO weekdays (1 = Monday .. 7 = Sunday), strictly ascending,
-- at most 6 of them; '{}' means the location opens every day.
--
-- What changes:
-- - app.sales_totals: expected_days counts only the (location, day) pairs the location is open, and
--   expected_covered only the covered ones among them. net_sales, the other figures and
--   covered_days are unchanged: sales on a closed day still count, and coverage stays <= 100 %.
--   It feeds the missing_days and previous_partial flags and meta.coverage_pct of
--   get_sales_summary, compare_periods and get_top_dishes.
-- - api.get_data_status: missing_business_days comes from app.missing_business_days. The body is
--   the one from 20261019200000_read_rpcs_first4.sql, unchanged otherwise.
-- With no closed days every output is the same as before.

alter table public.location add column closed_weekdays smallint[] not null default '{}';

-- A CHECK cannot hold a subquery, so the rule lives in an immutable helper (as app.is_valid_timezone).
-- It refuses nulls, values outside 1..7, repeats, any order but ascending, multi-dimensional
-- arrays and all seven days (a location that never opens is not a location).
create function app.is_closed_weekdays(days smallint[])
returns boolean
language sql immutable set search_path = ''
as $$
  select case
    when days is null then false
    when cardinality(days) = 0 then true
    when array_ndims(days) <> 1 or cardinality(days) >= 7 then false
    else coalesce((
      select bool_and(d.v is not null and d.v between 1 and 7 and (d.prev is null or d.v > d.prev))
      from (select u.v, lag(u.v) over (order by u.o) as prev from unnest(days) with ordinality u(v, o)) d), false)
  end
$$;

revoke all on function app.is_closed_weekdays(smallint[]) from public, anon;
grant execute on function app.is_closed_weekdays(smallint[]) to service_role;

alter table public.location
  add constraint location_closed_weekdays_valid check (app.is_closed_weekdays(closed_weekdays)) not valid;
alter table public.location validate constraint location_closed_weekdays_valid;

-- The (location, day) pairs over [f, t] on which the location normally opens.
create function app.open_location_days(locs uuid[], f date, t date)
returns table (location_id uuid, day date)
language sql stable security invoker set search_path = ''
as $$
  select l.id, f + n
  from public.location l
  cross join generate_series(0, t - f) n
  where l.id = any (locs)
    and not (extract(isodow from f + n)::smallint = any (l.closed_weekdays))
$$;

-- The days over [f, t], sorted and distinct, on which some location is open and has neither
-- daily nor item sales (a json array of dates).
create function app.missing_business_days(locs uuid[], f date, t date)
returns jsonb
language sql stable security invoker set search_path = ''
as $$
  with covered as (
    select v.location_id, v.business_date from app.v_daily_sales v
    where v.location_id = any (locs) and v.business_date between f and t
    union
    select v.location_id, v.business_date from app.v_item_sales_daily v
    where v.location_id = any (locs) and v.business_date between f and t
  )
  select coalesce(jsonb_agg(distinct o.day order by o.day), '[]')
  from app.open_location_days(locs, f, t) o
  where not exists (select 1 from covered c where c.location_id = o.location_id and c.business_date = o.day)
$$;

revoke all on function
  app.open_location_days(uuid[], date, date), app.missing_business_days(uuid[], date, date)
  from public, anon;
grant execute on function
  app.open_location_days(uuid[], date, date), app.missing_business_days(uuid[], date, date)
  to authenticated;

-- Daily figures over [f, t] for the locations, from v_daily_sales. A nullable figure is
-- known only when every covered day reports it (not reported is not zero). Coverage compares
-- like with like: expected_days are the location-days up to yesterday on which the location
-- normally opens, and expected_covered counts the covered ones among them (a day loaded early,
-- like today, or on a closed day adds sales, not coverage).
create or replace function app.sales_totals(locs uuid[], f date, t date)
returns table (
  net_sales bigint, tickets bigint, guests bigint, discounts bigint, cancellations bigint,
  covered_days int, item_only_days int, expected_days int, expected_covered int
)
language sql stable set search_path = ''
as $$
  with w as (
    select least(t, app.business_today(locs[1]) - 1) as last_expected
  ), d as (
    select v.* from app.v_daily_sales v
    where v.location_id = any (locs) and v.business_date between f and t
  ), i as (
    select r.location_id, r.day, sum(r.net) as net
    from app.item_rows(locs, f, t) r
    where not exists (select 1 from d where d.location_id = r.location_id and d.business_date = r.day)
    group by r.location_id, r.day
  ), o as (
    select o.location_id, o.day from w, app.open_location_days(locs, f, w.last_expected) o
  )
  select
    (coalesce((select sum(d.net_sales) from d), 0) + coalesce((select sum(i.net) from i), 0))::bigint,
    case when not exists (select 1 from i) and not exists (select 1 from d where d.tickets is null)
      then (select sum(d.tickets) from d)::bigint end,
    case when not exists (select 1 from i) and not exists (select 1 from d where d.guests is null)
      then (select sum(d.guests) from d)::bigint end,
    case when not exists (select 1 from i) and not exists (select 1 from d where d.discounts is null)
      then (select sum(d.discounts) from d)::bigint end,
    case when not exists (select 1 from i) and not exists (select 1 from d where d.cancellations_amount is null)
      then (select sum(d.cancellations_amount) from d)::bigint end,
    ((select count(*) from d) + (select count(*) from i))::int,
    (select count(*) from i)::int,
    (select count(*) from o)::int,
    ((select count(*) from d join o on o.location_id = d.location_id and o.day = d.business_date)
     + (select count(*) from i join o on o.location_id = i.location_id and o.day = i.day))::int
$$;

-- Data health over the last 30 days: last applied batch per source kind, business days without
-- sales (days some location normally opens), ingredients whose cost is stale (newest price older
-- than 45 days, 03 C.3, or no price) among those used by current recipes, and the share of
-- business days with sales data.
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

  missing := app.missing_business_days(locs, today - 30, today - 1);

  select count(*) into stale
  from public.ingredient i
  where exists (
      select 1 from public.recipe_line rl join public.recipe rc on rc.id = rl.recipe_id
      where rl.ingredient_id = i.id
        and (rc.effective_from is null or rc.effective_from <= today)
        and (rc.effective_to is null or rc.effective_to >= today))
    and coalesce((select max(p.effective_from) from public.ingredient_price p
                  where p.ingredient_id = i.id and p.effective_from <= today), '-infinity') < today - 45;

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
