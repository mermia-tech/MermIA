-- MR-17: the first 4 read RPCs (09 section 4.1; C3 shapes in packages/contracts rpc.py):
-- get_sales_summary, compare_periods, get_top_dishes, get_data_status.
--
-- Where they live. `public` holds domain tables only and no functions (MR-10 spec 7.5.3, approved),
-- and an RPC on `app` is not reachable through the Data API (spec V7). The RPCs go in a new schema
-- `api`, exposed in supabase/config.toml ([api].schemas) and, on the hosted project, in the Data
-- API settings. `api` holds functions only. Every RPC is SECURITY INVOKER (09 section 4.1), so RLS
-- decides the tenant and the locations; the helpers below run as the caller too.
--
-- Choices 09 leaves open (documented here and in the PR; open to change):
-- - "Today" is the business date in the location's time zone (the first visible location's when no
--   location is given; America/Mexico_City as a last resort). `app.today` (a custom setting) pins
--   it for tests; clients have no raw-SQL path to set it (spec 7.5.3).
-- - Weeks start on Monday. last_7d and last_30d end yesterday: today's sales arrive tomorrow.
-- - Only rows of applied batches count (09 section 2.6). One daily row per location and day: the
--   one from the most recently applied batch.
-- - Sales come from daily_sales_agg; a day with item rows but no daily row adds its item net to
--   net_sales and reports the other figures as unknown. Ticket grain (ERP push) joins in later
--   through the unified-grain views (09 section 2.6), not here.
-- - meta.coverage_pct is data coverage: business days with sales data over the days the period
--   should have (each visible location, up to yesterday), as 07 and 08 define it.
-- - Cost figures (margin, food cost) read dish_cost_snapshot, which the costing engine writes
--   (MR-25). IVA inside a net is round(net x 16 / 116), as in fixtures/README.md.

create schema api;
revoke all on schema api from public;
grant usage on schema api to authenticated;

-- Business date and periods ------------------------------------------------------------------
create function app.business_today(loc uuid default null) returns date
language sql stable set search_path = ''
as $$
  select coalesce(
    nullif(current_setting('app.today', true), '')::date,
    (now() at time zone coalesce(
      (select l.timezone from public.location l where l.id = loc),
      (select l.timezone from public.location l order by l.id limit 1),
      'America/Mexico_City'))::date)
$$;

-- A named period or an explicit {from, to}, both inclusive, as [from, to]. Raises 22023 when the
-- argument is not a valid period. An explicit range covers at most 366 days.
create function app.resolve_period(period jsonb, today date) returns date[]
language plpgsql immutable set search_path = ''
as $$
declare
  monday constant date := today - (extract(isodow from today)::int - 1);
  first constant date := date_trunc('month', today)::date;
  f date;
  t date;
begin
  if jsonb_typeof(period) = 'string' then
    case period #>> '{}'
      when 'today' then return array[today, today];
      when 'yesterday' then return array[today - 1, today - 1];
      when 'this_week' then return array[monday, today];
      when 'last_week' then return array[monday - 7, monday - 1];
      when 'prev_week' then return array[monday - 14, monday - 8];
      when 'this_month' then return array[first, today];
      when 'last_month' then return array[(first - interval '1 month')::date, first - 1];
      when 'last_7d' then return array[today - 7, today - 1];
      when 'last_30d' then return array[today - 30, today - 1];
      else null;
    end case;
  elsif jsonb_typeof(period) = 'object'
        and (select array_agg(k order by k) from jsonb_object_keys(period) k) = array['from', 'to']
        and period ->> 'from' ~ '^\d{4}-\d{2}-\d{2}$' and period ->> 'to' ~ '^\d{4}-\d{2}-\d{2}$' then
    begin
      f := (period ->> 'from')::date;
      t := (period ->> 'to')::date;
    exception when others then
      f := null;
    end;
    if f is not null and f <= t and t - f < 366 then
      return array[f, t];
    end if;
  end if;
  raise exception 'invalid period: %', period using errcode = '22023';
end
$$;

-- The previous equivalent period: the week before for weeks, the month before for months (same
-- days of the month, clamped), otherwise the same number of days just before.
create function app.previous_period(period jsonb, r date[]) returns date[]
language sql immutable set search_path = ''
as $$
  select case
    when period #>> '{}' in ('this_week', 'last_week', 'prev_week') then array[r[1] - 7, r[2] - 7]
    when period #>> '{}' = 'this_month' then
      array[(r[1] - interval '1 month')::date, (r[2] - interval '1 month')::date]
    when period #>> '{}' = 'last_month' then array[(r[1] - interval '1 month')::date, r[1] - 1]
    else array[r[1] - (r[2] - r[1] + 1), r[1] - 1]
  end
$$;

-- The locations a call covers: every visible location, or the one asked for. Null when the asked
-- location is not visible (RLS), so the RPC answers not_found without saying whether it exists.
create function app.scope_locations(loc uuid) returns uuid[]
language sql stable set search_path = ''
as $$
  select case
    when loc is null then array(select l.id from public.location l order by l.id)
    when exists (select 1 from public.location l where l.id = loc) then array[loc]
  end
$$;

-- Formatting (es-MX numbers: comma thousands, point decimals) -------------------------------
create function app.fmt_money(cents numeric, signed boolean default false) returns text
language sql immutable set search_path = ''
as $$
  select case when cents < 0 then '-' when signed and cents > 0 then '+' else '' end
         || '$' || to_char(abs(cents) / 100.0, 'FM999,999,999,999,990.00')
$$;

create function app.fmt_number(x numeric, signed boolean default false) returns text
language sql immutable set search_path = ''
as $$
  select case when x < 0 then '-' when signed and x > 0 then '+' else '' end
         || rtrim(to_char(abs(x), 'FM999,999,999,999,990.999999'), '.')
$$;

-- One decimal; the sign follows the rounded value, so -0.04 shows as 0.0%.
create function app.fmt_pct(x numeric, signed boolean default false, suffix text default '%') returns text
language sql immutable set search_path = ''
as $$
  select case when round(x, 1) < 0 then '-' when signed and round(x, 1) > 0 then '+' else '' end
         || to_char(abs(round(x, 1)), 'FM999,999,990.0') || suffix
$$;

-- {raw, text} for a metric of compare_periods / get_top_dishes (METRIC_UNIT in rpc.py). A change
-- carries a sign; a change of a percentage is in points.
create function app.figure(metric text, v numeric, is_change boolean default false) returns jsonb
language sql immutable set search_path = ''
as $$
  select case
    when metric in ('net_sales', 'avg_ticket', 'revenue', 'margin') then
      jsonb_build_object('raw', round(v), 'text', app.fmt_money(round(v), is_change))
    when metric in ('tickets', 'guests') then
      jsonb_build_object('raw', round(v), 'text', app.fmt_number(round(v), is_change))
    when metric = 'units' then
      jsonb_build_object('raw', trim_scale(round(v, 6)), 'text', app.fmt_number(round(v, 6), is_change))
    when metric in ('food_cost_pct', 'margin_pct') then
      jsonb_build_object('raw', trim_scale(round(v, 4)),
                         'text', app.fmt_pct(v, is_change, case when is_change then ' pts' else '%' end))
  end
$$;

-- Envelope ----------------------------------------------------------------------------------
-- When the data was last updated: the latest applied batch the caller can see for these locations.
create function app.data_as_of(locs uuid[]) returns timestamptz
language sql stable set search_path = ''
as $$
  select coalesce(max(b.applied_at), now())
  from public.import_batch b
  where b.status = 'applied' and (b.location_id = any (locs) or b.location_id is null)
$$;

create function app.rpc_ok(
  data jsonb, locs uuid[], flags jsonb default '[]', coverage numeric default null, r date[] default null
) returns jsonb
language sql stable set search_path = ''
as $$
  select jsonb_build_object(
    'ok', true, 'data', data, 'flags', coalesce(flags, '[]'),
    'meta', jsonb_build_object(
      'as_of', app.data_as_of(locs),
      'coverage_pct', trim_scale(round(coverage, 1)),
      'period_resolved', case when r is not null then jsonb_build_object('from', r[1], 'to', r[2]) end))
$$;

create function app.rpc_error(code text, message text, locs uuid[] default '{}') returns jsonb
language sql stable set search_path = ''
as $$
  select jsonb_build_object(
    'ok', false, 'error', jsonb_build_object('code', code, 'message', message), 'flags', '[]'::jsonb,
    'meta', jsonb_build_object('as_of', app.data_as_of(locs)))
$$;

create function app.flag(code text, message text) returns jsonb
language sql immutable set search_path = ''
as $$
  select jsonb_build_object('code', code, 'message', message)
$$;

-- Sales over a range ------------------------------------------------------------------------
-- Daily figures over [f, t] for the locations, from applied batches only. A nullable figure is
-- known only when every covered day reports it (not reported is not zero).
create function app.sales_totals(locs uuid[], f date, t date)
returns table (
  net_sales bigint, tickets bigint, guests bigint, discounts bigint, cancellations bigint,
  covered_days int, item_only_days int, expected_days int
)
language sql stable set search_path = ''
as $$
  with d as (
    select distinct on (s.location_id, s.business_date) s.*
    from public.daily_sales_agg s
    join public.import_batch b on b.tenant_id = s.tenant_id and b.id = s.batch_id
    where b.status = 'applied' and s.location_id = any (locs) and s.business_date between f and t
    order by s.location_id, s.business_date, b.applied_at desc, s.id desc
  ), i as (
    select a.location_id, a.period_from as day, sum(a.net) as net
    from public.item_sales_agg a
    join public.import_batch b on b.tenant_id = a.tenant_id and b.id = a.batch_id
    where b.status = 'applied' and a.location_id = any (locs)
      and a.period_from = a.period_to and a.period_from between f and t
      and not exists (select 1 from d where d.location_id = a.location_id and d.business_date = a.period_from)
    group by a.location_id, a.period_from
  ), e as (
    select greatest(least(t, app.business_today(locs[1]) - 1) - f + 1, 0) * coalesce(cardinality(locs), 0) as n
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
    (select e.n from e)::int
$$;

-- Item sales of applied batches, single-day rows only, joined to the dish cost of that day.
create function app.item_rows(locs uuid[], f date, t date)
returns table (menu_item_id uuid, units numeric, net bigint, cost bigint)
language sql stable set search_path = ''
as $$
  select a.menu_item_id, a.units, a.net, c.cost
  from public.item_sales_agg a
  join public.import_batch b on b.tenant_id = a.tenant_id and b.id = a.batch_id
  left join public.dish_cost_snapshot c
    on c.tenant_id = a.tenant_id and c.menu_item_id = a.menu_item_id
   and c.location_id = a.location_id and c.date = a.period_from
  where b.status = 'applied' and a.location_id = any (locs)
    and a.period_from = a.period_to and a.period_from between f and t
$$;

-- The value of a compare_periods metric over [f, t]; null when the data cannot give it.
create function app.metric_value(metric text, locs uuid[], f date, t date) returns numeric
language sql stable set search_path = ''
as $$
  select case metric
    when 'net_sales' then (select case when s.covered_days > 0 then s.net_sales end from app.sales_totals(locs, f, t) s)
    when 'tickets' then (select s.tickets from app.sales_totals(locs, f, t) s where s.covered_days > 0)
    when 'guests' then (select s.guests from app.sales_totals(locs, f, t) s where s.covered_days > 0)
    when 'avg_ticket' then
      (select round(s.net_sales::numeric / s.tickets) from app.sales_totals(locs, f, t) s where s.tickets > 0)
    when 'units' then (select sum(r.units) from app.item_rows(locs, f, t) r)
    when 'food_cost_pct' then
      (select 100 * sum(r.units * r.cost) / nullif(sum(r.net) - round(sum(r.net) * 16 / 116.0), 0)
       from app.item_rows(locs, f, t) r where r.cost is not null)
  end
$$;

-- The RPCs ----------------------------------------------------------------------------------
create function api.get_sales_summary(period jsonb, location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  r date[];
  p date[];
  s record;
  prev record;
  change numeric;
  missing text[] := '{}';
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  r := app.resolve_period(period, app.business_today(location_id));
  select * into s from app.sales_totals(locs, r[1], r[2]);
  if s.covered_days = 0 then
    return app.rpc_error('no_data', 'No sales loaded for the period', locs);
  end if;

  p := app.previous_period(period, r);
  select * into prev from app.sales_totals(locs, p[1], p[2]);
  if prev.covered_days > 0 and prev.net_sales > 0 then
    change := round(100.0 * (s.net_sales - prev.net_sales) / prev.net_sales, 4);
    if prev.covered_days < prev.expected_days then
      flags := flags || app.flag('previous_partial', 'Faltan días en el periodo anterior: la comparación es aproximada.');
    end if;
  end if;

  if s.covered_days < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.covered_days, s.expected_days));
  end if;
  if s.tickets is null then missing := missing || 'tickets'::text; end if;
  if s.guests is null then missing := missing || 'comensales'::text; end if;
  if s.discounts is null then missing := missing || 'descuentos'::text; end if;
  if s.cancellations is null then missing := missing || 'cancelaciones'::text; end if;
  if cardinality(missing) > 0 then
    flags := flags || app.flag('partial_data', 'La fuente no reporta: ' || array_to_string(missing, ', ') || '.');
  end if;

  return app.rpc_ok(
    jsonb_build_object(
      'net_sales', jsonb_build_object('raw', s.net_sales, 'text', app.fmt_money(s.net_sales)),
      'tickets', s.tickets,
      'avg_ticket', case when s.tickets > 0 then jsonb_build_object(
        'raw', round(s.net_sales::numeric / s.tickets),
        'text', app.fmt_money(round(s.net_sales::numeric / s.tickets))) end,
      'guests', s.guests,
      'discounts', case when s.discounts is not null then
        jsonb_build_object('raw', s.discounts, 'text', app.fmt_money(s.discounts)) end,
      'cancellations', case when s.cancellations is not null then
        jsonb_build_object('raw', s.cancellations, 'text', app.fmt_money(s.cancellations)) end,
      'change_vs_previous', case when change is not null then
        jsonb_build_object('raw', trim_scale(change), 'text', app.fmt_pct(change, true)) end),
    locs, flags, 100.0 * s.covered_days / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

create function api.compare_periods(
  metric text, period_a jsonb, period_b jsonb, location_id uuid default null
) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  ra date[];
  rb date[];
  a numeric;
  b numeric;
  ca record;
  cb record;
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  if metric is null or metric not in ('net_sales', 'tickets', 'avg_ticket', 'guests', 'food_cost_pct', 'units') then
    raise exception 'unknown metric: %', metric using errcode = '22023';
  end if;
  today := app.business_today(location_id);
  ra := app.resolve_period(period_a, today);
  rb := app.resolve_period(period_b, today);
  a := app.metric_value(metric, locs, ra[1], ra[2]);
  b := app.metric_value(metric, locs, rb[1], rb[2]);
  if a is null or b is null then
    return app.rpc_error('no_data',
      format('No %s data for %s', metric, case when a is null then 'period_a' else 'period_b' end), locs);
  end if;
  -- raw figures are rounded to their scale before the change, so abs_change = a - b exactly
  a := ((app.figure(metric, a)) ->> 'raw')::numeric;
  b := ((app.figure(metric, b)) ->> 'raw')::numeric;

  select * into ca from app.sales_totals(locs, ra[1], ra[2]);
  select * into cb from app.sales_totals(locs, rb[1], rb[2]);
  if ca.covered_days < ca.expected_days or cb.covered_days < cb.expected_days then
    flags := flags || app.flag('missing_days', 'Algún periodo tiene días sin datos: la comparación es aproximada.');
  end if;

  return app.rpc_ok(
    jsonb_build_object(
      'metric', metric,
      'period_a', jsonb_build_object('from', ra[1], 'to', ra[2]),
      'period_b', jsonb_build_object('from', rb[1], 'to', rb[2]),
      'a', app.figure(metric, a),
      'b', app.figure(metric, b),
      'abs_change', app.figure(metric, a - b, true),
      'pct_change', case when b <> 0 then jsonb_build_object(
        'raw', trim_scale(round(100 * (a - b) / b, 4)), 'text', app.fmt_pct(100 * (a - b) / b, true)) end),
    locs, flags,
    100.0 * (ca.covered_days + cb.covered_days) / nullif(ca.expected_days + cb.expected_days, 0), null);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

create function api.get_top_dishes(
  period jsonb, metric text, "order" text default 'desc', "limit" int default 5,
  location_id uuid default null, category text default null
) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  r date[];
  s record;
  rows jsonb;
  uncosted bigint;
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  if metric is null or metric not in ('units', 'revenue', 'margin', 'margin_pct') then
    raise exception 'unknown metric: %', metric using errcode = '22023';
  end if;
  if "order" is null or "order" not in ('asc', 'desc') then
    raise exception 'order must be asc or desc' using errcode = '22023';
  end if;
  if "limit" is null or "limit" not between 1 and 10 then
    raise exception 'limit must be between 1 and 10' using errcode = '22023';
  end if;
  if category is not null and not exists (
    select 1 from public.menu_category c where lower(c.name) = lower(btrim(category))) then
    return app.rpc_error('not_found', 'category not found', locs);
  end if;
  r := app.resolve_period(period, app.business_today(location_id));

  with x as (
    select x.* from app.item_rows(locs, r[1], r[2]) x
    join public.menu_item m on m.id = x.menu_item_id
    left join public.menu_category c on c.id = m.category_id
    where category is null or lower(c.name) = lower(btrim(category))
  ), v as (
    select x.menu_item_id,
      case metric
        when 'units' then sum(x.units)
        when 'revenue' then sum(x.net)
        when 'margin' then sum(x.net - round(x.net * 16 / 116.0)) - sum(x.units * x.cost)
        when 'margin_pct' then 100 * (sum(x.net - round(x.net * 16 / 116.0)) - sum(x.units * x.cost))
                               / nullif(sum(x.net - round(x.net * 16 / 116.0)), 0)
      end as value
    from x
    where metric in ('units', 'revenue') or x.cost is not null
    group by x.menu_item_id
  ), ranked as (
    select v.menu_item_id, m.name, v.value,
      row_number() over (order by case when "order" = 'desc' then v.value end desc nulls last,
                                  case when "order" = 'asc' then v.value end asc nulls last,
                                  m.name, v.menu_item_id) as rank
    from v join public.menu_item m on m.id = v.menu_item_id
    where v.value is not null
  )
  select jsonb_agg(jsonb_build_object('rank', ranked.rank, 'menu_item_id', ranked.menu_item_id,
                                      'name', ranked.name, 'value', app.figure(metric, ranked.value))
                   order by ranked.rank),
         (select count(*) from x where x.cost is null)
  into rows, uncosted
  from ranked where ranked.rank <= "limit";

  if rows is null then
    return app.rpc_error('no_data',
      case when metric in ('margin', 'margin_pct') then 'No costed dish sales for the period'
           else 'No dish sales loaded for the period' end, locs);
  end if;
  if metric in ('margin', 'margin_pct') and uncosted > 0 then
    flags := flags || app.flag('uncosted_sales', 'Algunos platillos vendidos no tienen costo y no entran en el ranking.');
  end if;
  select * into s from app.sales_totals(locs, r[1], r[2]);
  if s.covered_days < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.covered_days, s.expected_days));
  end if;

  return app.rpc_ok(jsonb_build_object('metric', metric, 'rows', rows), locs, flags,
                    100.0 * s.covered_days / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- Data health over the last 30 days: last applied batch per source kind, business days without
-- sales, ingredients whose cost is stale (newest price older than 45 days, 03 C.3, or no price)
-- among those used by current recipes, and the share of business days with sales data.
create function api.get_data_status(location_id uuid default null) returns jsonb
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
    where src.location_id = any (locs) or src.location_id is null
    group by src.kind
  ) k;

  select coalesce(jsonb_agg(d.day order by d.day), '[]') into missing
  from generate_series(today - 30, today - 1, interval '1 day') as g(ts)
  cross join lateral (select g.ts::date as day) d
  where exists (
    select 1 from unnest(locs) l(id)
    where not exists (select 1 from app.sales_totals(array[l.id], d.day, d.day) t where t.covered_days > 0));

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
  coverage := round(100.0 * s.covered_days / nullif(s.expected_days, 0), 4);

  return app.rpc_ok(
    jsonb_build_object(
      'sources', sources,
      'missing_business_days', missing,
      'stale_costs', stale,
      'coverage', jsonb_build_object('raw', trim_scale(coalesce(coverage, 0)), 'text', app.fmt_pct(coalesce(coverage, 0)))),
    locs, '[]', coverage, null);
end
$$;

-- Privileges --------------------------------------------------------------------------------
-- The RPCs run as the caller, so the caller needs the helpers they call. None of them reads
-- anything RLS would not let the caller read directly.
grant execute on function
  app.business_today(uuid), app.resolve_period(jsonb, date), app.previous_period(jsonb, date[]),
  app.scope_locations(uuid), app.fmt_money(numeric, boolean), app.fmt_number(numeric, boolean),
  app.fmt_pct(numeric, boolean, text), app.figure(text, numeric, boolean), app.data_as_of(uuid[]),
  app.rpc_ok(jsonb, uuid[], jsonb, numeric, date[]), app.rpc_error(text, text, uuid[]),
  app.flag(text, text), app.sales_totals(uuid[], date, date), app.item_rows(uuid[], date, date),
  app.metric_value(text, uuid[], date, date)
  to authenticated;
grant execute on function
  api.get_sales_summary(jsonb, uuid), api.compare_periods(text, jsonb, jsonb, uuid),
  api.get_top_dishes(jsonb, text, text, int, uuid, text), api.get_data_status(uuid)
  to authenticated;
