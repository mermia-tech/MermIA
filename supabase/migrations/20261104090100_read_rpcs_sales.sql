-- MR-24 (2 of 2): the sales read RPCs (09 section 4.1; C3 shapes in packages/contracts rpc.py):
-- get_sales_breakdown, get_cancellations, compare_locations. Same pattern as MR-17
-- (20261019200000_read_rpcs_first4.sql): SECURITY INVOKER functions in `api`, so RLS decides the
-- tenant and the locations. The money and percentage helpers come from
-- 20261104090000_read_rpcs_cost.sql.
--
-- Staff are named by first name only (09 section 4.2). Figures a source does not report stay
-- null or are flagged, never zero (MR-11 D23).

-- get_sales_breakdown -----------------------------------------------------------------------
-- The daily aggregate's payment mix, for payment_method on aggregate days. A new view, so the
-- MR-17 views stay as they are; the same "most recently applied batch" rule as app.v_daily_agg.
create view app.v_daily_payment_mix with (security_invoker = true) as
select distinct on (s.tenant_id, s.location_id, s.business_date)
       s.tenant_id, s.location_id, s.business_date, s.payment_mix
from public.daily_sales_agg s
join public.import_batch b on b.tenant_id = s.tenant_id and b.id = s.batch_id
where b.status = 'applied'
order by s.tenant_id, s.location_id, s.business_date, b.applied_at desc, s.id desc;

-- Paid tickets of applied batches over [f, t] (ticket grain).
create function app.paid_tickets(locs uuid[], d_from date, d_to date)
returns table (id uuid, location_id uuid, business_date date, total bigint, discount bigint, staff_id uuid,
               channel app.sale_channel, at timestamptz, timezone text)
language sql stable set search_path = ''
as $$
  select t.id, t.location_id, t.business_date, t.total, t.discount, t.staff_id, t.channel,
         coalesce(t.closed_at, t.opened_at), l.timezone
  from public.sale_ticket t
  join public.import_batch b on b.tenant_id = t.tenant_id and b.id = t.batch_id
  join public.location l on l.id = t.location_id
  where b.status = 'applied' and t.status = 'paid'
    and t.location_id = any (locs) and t.business_date between d_from and d_to
$$;

-- Staff as the agent may see them (09 section 4.2): the first name only, never the full name.
-- When two of the staff in one answer share a first name, each gets its last-name initial
-- ("Luis M.", "Luis R."), so their rows can be told apart. No staff (or none visible) is
-- "Sin asignar". One row per id in `ids` (null included).
create function app.staff_names(ids uuid[]) returns table (staff_id uuid, name text)
language sql stable set search_path = ''
as $$
  with n as (
    select u.id, w[1] as first, left(w[2], 1) as initial
    from (select distinct u.id from unnest(ids) u(id)) u
    left join public.staff s on s.id = u.id
    cross join lateral (select regexp_split_to_array(btrim(s.display_name), '\s+') as w) x
  ), f as (
    select n.id, coalesce(nullif(n.first, ''), 'Sin asignar') as first, nullif(n.initial, '') as initial from n
  )
  select f.id,
         case when f.id is not null and f.initial is not null and count(*) over (partition by f.first) > 1
              then f.first || ' ' || upper(f.initial) || '.' else f.first end
  from f
$$;

-- Breakdown rows (key, net_sales, tickets, order) for one dimension. `tickets` is null when a
-- row takes any sales from aggregate or item data, which carry no ticket count per row (D23).
create function app.breakdown_rows(dim text, locs uuid[], f date, t date)
returns table (key text, net_sales bigint, tickets bigint, ord int)
language plpgsql stable set search_path = ''
as $$
begin
  if dim = 'payment_method' then
    return query
    with d as (
      select v.location_id, v.business_date, v.grain from app.v_daily_sales v
      where v.location_id = any (locs) and v.business_date between f and t
    ), parts as (
      select p.method::text as k, p.amount::numeric as amount, p.ticket_id
      from public.payment p
      join public.import_batch b on b.tenant_id = p.tenant_id and b.id = p.batch_id
      join app.paid_tickets(locs, f, t) pt on pt.id = p.ticket_id
      where b.status = 'applied'
      union all
      select m.key, m.value::numeric, null::uuid
      from d join app.v_daily_payment_mix x
        on x.location_id = d.location_id and x.business_date = d.business_date
      cross join lateral jsonb_each_text(x.payment_mix) m
      where d.grain = 'aggregate'
    )
    select parts.k, round(sum(parts.amount))::bigint,
           case when bool_and(parts.ticket_id is not null) then count(distinct parts.ticket_id) end, 0
    from parts group by parts.k;
  elsif dim = 'staff' then
    return query
    with g as (
      select pt.staff_id, sum(pt.total)::bigint as net_sales, count(*) as tickets
      from app.paid_tickets(locs, f, t) pt group by pt.staff_id
    )
    select n.name, g.net_sales, g.tickets, 0
    from g join app.staff_names(array(select g.staff_id from g)) n on n.staff_id is not distinct from g.staff_id;
  elsif dim = 'channel' then
    return query
    select coalesce(pt.channel::text, 'unknown'), sum(pt.total)::bigint, count(*), 0
    from app.paid_tickets(locs, f, t) pt group by pt.channel;
  elsif dim = 'hour' then
    return query
    select coalesce(lpad(h::text, 2, '0') || ':00', 'unknown'), sum(x.total)::bigint, count(*), coalesce(h, 24)
    from (select pt.total, extract(hour from pt.at at time zone pt.timezone)::int as h
          from app.paid_tickets(locs, f, t) pt) x
    group by x.h;
  elsif dim = 'weekday' then
    return query
    with d as (
      select v.location_id, v.business_date, v.net_sales, v.tickets from app.v_daily_sales v
      where v.location_id = any (locs) and v.business_date between f and t
    ), i as (
      select r.location_id, r.day as business_date, sum(r.net) as net_sales, null::bigint as tickets
      from app.item_rows(locs, f, t) r
      where not exists (select 1 from d where d.location_id = r.location_id and d.business_date = r.day)
      group by r.location_id, r.day
    ), u as (
      select d.business_date, d.net_sales, d.tickets from d
      union all
      select i.business_date, i.net_sales, i.tickets from i
    )
    select (array['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
             [extract(isodow from u.business_date)::int],
           sum(u.net_sales)::bigint,
           case when bool_and(u.tickets is not null) then sum(u.tickets)::bigint end,
           extract(isodow from u.business_date)::int
    from u group by extract(isodow from u.business_date);
  elsif dim = 'category' then
    return query
    select coalesce(mc.name, 'Sin categoría'), sum(r.net)::bigint, null::bigint, 0
    from app.item_rows(locs, f, t) r
    join public.menu_item m on m.id = r.menu_item_id
    left join public.menu_category mc on mc.id = m.category_id
    group by coalesce(mc.name, 'Sin categoría');
  else
    raise exception 'unknown breakdown: %', dim using errcode = '22023';
  end if;
end
$$;

-- Rows are ordered by net sales (largest first), except hour and weekday, which keep their
-- order. Staff, hour and channel need ticket data: without it the answer is no_data, and when
-- only some days have it the answer is flagged partial. A day has payment detail when it is a
-- ticket day with payment records, or an aggregate day with a payment mix.
create function api.get_sales_breakdown(period jsonb, "by" text, location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  r date[];
  s record;
  rows jsonb;
  detail_days int;
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  if "by" is null or "by" not in ('payment_method', 'staff', 'hour', 'weekday', 'channel', 'category') then
    raise exception 'unknown breakdown: %', "by" using errcode = '22023';
  end if;
  r := app.resolve_period(period, app.business_today(location_id));

  select jsonb_agg(jsonb_build_object(
           'key', b.key, 'net_sales', app.money(b.net_sales), 'tickets', b.tickets,
           'share', app.pct(case when b.total > 0 then 100.0 * b.net_sales / b.total else 0 end))
         order by case when "by" in ('hour', 'weekday') then b.ord end, b.net_sales desc, b.key)
  into rows
  from (select x.*, sum(x.net_sales) over () as total
        from app.breakdown_rows("by", locs, r[1], r[2]) x) b;
  if rows is null then
    return app.rpc_error('no_data',
      case when "by" in ('staff', 'hour', 'channel') then format('The source has no ticket data to break sales down by %s', "by")
           else 'No sales loaded for the period' end, locs);
  end if;

  select * into s from app.sales_totals(locs, r[1], r[2]);
  if "by" = 'category' then
    select count(*) into detail_days from (
      select distinct v.location_id, v.business_date from app.v_item_sales_daily v
      where v.location_id = any (locs) and v.business_date between r[1] and r[2]) d;
  elsif "by" in ('staff', 'hour', 'channel', 'payment_method') then
    select count(*) into detail_days from (
      select v.location_id, v.business_date from app.v_daily_sales v
      where v.location_id = any (locs) and v.business_date between r[1] and r[2]
        and case when "by" <> 'payment_method' then v.grain = 'ticket'
                 when v.grain = 'ticket' then exists (
                   select 1 from app.paid_tickets(array[v.location_id], v.business_date, v.business_date) pt
                   join public.payment p on p.ticket_id = pt.id
                   join public.import_batch b on b.tenant_id = p.tenant_id and b.id = p.batch_id
                   where b.status = 'applied')
                 else exists (
                   select 1 from app.v_daily_payment_mix x
                   where x.location_id = v.location_id and x.business_date = v.business_date and x.payment_mix <> '{}')
            end) d;
  end if;
  if "by" <> 'weekday' and detail_days < s.covered_days then
    flags := flags || app.flag('partial_data',
      format('Solo %s de %s días con ventas tienen este detalle.', detail_days, s.covered_days));
  end if;
  if s.expected_covered < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.expected_covered, s.expected_days));
  end if;

  return app.rpc_ok(jsonb_build_object('by', "by", 'rows', rows), locs, flags,
                    100.0 * s.expected_covered / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- get_cancellations -------------------------------------------------------------------------
-- Not reported is never zero (MR-11 D23): a day counts only when it gives both the count and the
-- amount, and count and amount add up the same days; the others are flagged `partial_data`, and
-- with none the answer is no_data.
-- - Cancellations: count and amount follow each day's grain (the aggregate wins, MR-17 rule C;
--   a ticket day without one counts its cancelled tickets). The detail is the cancelled tickets
--   of those days, as the ticket-day totals are: the top 3 items (lines of cancelled tickets,
--   largest amount first; a line counts its quantity, a weighed or fractional one once, a
--   negative one never) and the staff (each cancelled ticket once for its waiter; most first).
--   Voided lines of paid tickets are not cancellations here (see the PR's contract questions).
-- - Discounts: the amount follows the day's grain. A ticket day gives the count; an aggregate day
--   gives it from its item report (each dish with a discount once per day, flagged
--   `count_by_day`), or when its discounts are zero. `count` is the items' counts plus the tickets
--   with a ticket-level discount; staff are the paid tickets with a discount.
-- - `partial_detail`: the staff (and, for discounts, the item) detail does not add up to the
--   totals, e.g. aggregate days whose cancelled tickets were not exported.
create function app.cancellation_days(kind text, locs uuid[], f date, t date)
returns table (location_id uuid, business_date date, reported boolean, n bigint, amount bigint)
language sql stable set search_path = ''
as $$
  select v.location_id, v.business_date,
         case when kind = 'cancellations' then v.cancellations_amount is not null and v.cancellations_count is not null
              else v.discounts is not null and (v.grain = 'ticket' or v.discounts = 0 or exists (
                     select 1 from app.v_item_sales_daily i
                     where i.location_id = v.location_id and i.business_date = v.business_date and i.discount > 0))
         end,
         case when kind = 'cancellations' then v.cancellations_count end,
         case when kind = 'cancellations' then v.cancellations_amount else v.discounts end
  from app.v_daily_sales v
  where v.location_id = any (locs) and v.business_date between f and t
$$;

create function app.cancellation_detail(locs uuid[], f date, t date)
returns table (part text, name text, n bigint, amount bigint)
language sql stable set search_path = ''
as $$
  with tickets as (
    select tk.id, tk.tenant_id, tk.staff_id, tk.total
    from public.sale_ticket tk
    join public.import_batch b on b.tenant_id = tk.tenant_id and b.id = tk.batch_id
    join app.cancellation_days('cancellations', locs, f, t) d
      on d.reported and d.location_id = tk.location_id and d.business_date = tk.business_date
    where b.status = 'applied' and tk.status = 'cancelled'
  ), lines as (
    select l.menu_item_id, l.net,
           case when l.qty <= 0 then 0 when l.qty = trunc(l.qty) then l.qty else 1 end as n
    from public.sale_line l join tickets tk on tk.tenant_id = l.tenant_id and tk.id = l.ticket_id
  )
  select 'item', m.name, sum(lines.n)::bigint, sum(lines.net)::bigint
  from lines join public.menu_item m on m.id = lines.menu_item_id group by m.id, m.name
  union all
  select 'staff', n.name, count(*), sum(tickets.total)::bigint
  from tickets join app.staff_names(array(select tickets.staff_id from tickets)) n
    on n.staff_id is not distinct from tickets.staff_id
  group by tickets.staff_id, n.name
$$;

create function app.discount_detail(locs uuid[], f date, t date)
returns table (part text, name text, n bigint, amount bigint)
language sql stable set search_path = ''
as $$
  -- a discounted ticket line counts once; an aggregate row has no line detail, so a dish counts
  -- once per day it had a discount ('item_day' rows are also returned, to flag that)
  with d as (
    select * from app.cancellation_days('discounts', locs, f, t) where reported
  ), pt as (
    select pt.* from app.paid_tickets(locs, f, t) pt
    join d on d.location_id = pt.location_id and d.business_date = pt.business_date
  ), x as (
    select l.menu_item_id, l.discount, false as by_day
    from pt join public.sale_line l on l.ticket_id = pt.id
    where not l.is_void and l.discount > 0
    union all
    select v.menu_item_id, v.discount, true
    from app.v_item_sales_daily v
    join d on d.location_id = v.location_id and d.business_date = v.business_date
    where v.grain = 'aggregate' and v.discount > 0
  ), sd as (
    -- paid tickets with a discount (ticket-level or on a line), for the staff detail
    select y.* from (
      select pt.staff_id, pt.discount + coalesce((
        select sum(l.discount) from public.sale_line l where l.ticket_id = pt.id and not l.is_void), 0) as discount
      from pt
    ) y where y.discount > 0
  )
  select 'item', m.name, count(*), sum(x.discount)::bigint
  from x join public.menu_item m on m.id = x.menu_item_id
  group by m.id, m.name
  union all
  select 'item_day', null, count(*), null from x where x.by_day having count(*) > 0
  union all
  select 'staff', n.name, count(*), sum(sd.discount)::bigint
  from sd join app.staff_names(array(select sd.staff_id from sd)) n on n.staff_id is not distinct from sd.staff_id
  group by sd.staff_id, n.name
  union all
  select 'ticket', null, count(*), sum(pt.discount)::bigint
  from pt where pt.discount > 0
$$;

create function api.get_cancellations(period jsonb, kind text default 'cancellations', location_id uuid default null)
returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  r date[];
  s record;
  tot record;
  n bigint;
  top_items jsonb;
  by_staff jsonb;
  adds_up boolean;
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  if kind is null or kind not in ('cancellations', 'discounts') then
    raise exception 'kind must be cancellations or discounts' using errcode = '22023';
  end if;
  r := app.resolve_period(period, app.business_today(location_id));
  select * into s from app.sales_totals(locs, r[1], r[2]);
  if s.covered_days = 0 then
    return app.rpc_error('no_data', 'No sales loaded for the period', locs);
  end if;

  -- totals of the days that report both figures; a day that does not is flagged, never a zero
  select sum(d.n) filter (where d.reported)::bigint as n,
         sum(d.amount) filter (where d.reported)::bigint as amount,
         count(*) filter (where d.reported) as reported,
         count(*) filter (where not d.reported) + s.item_only_days as unreported
  into tot
  from app.cancellation_days(kind, locs, r[1], r[2]) d;
  if tot.reported = 0 then
    return app.rpc_error('no_data', format('The source does not report %s with their count for the period', kind), locs);
  end if;

  with d as (
    select * from app.cancellation_detail(locs, r[1], r[2]) where kind = 'cancellations'
    union all
    select * from app.discount_detail(locs, r[1], r[2]) where kind = 'discounts'
  )
  select
    (select coalesce(jsonb_agg(jsonb_build_object('name', x.name, 'count', x.n, 'amount', app.money(x.amount))
                               order by x.amount desc, x.name), '[]')
     from (select * from d where d.part = 'item' order by d.amount desc, d.name limit 3) x),
    (select coalesce(jsonb_agg(jsonb_build_object('name', x.name, 'count', x.n, 'amount', app.money(x.amount))
                               order by x.n desc, x.amount desc, x.name), '[]')
     from d x where x.part = 'staff'),
    case when kind = 'cancellations' then tot.n
         else coalesce((select sum(d.n) from d where d.part in ('item', 'ticket')), 0) end,
    case when kind = 'cancellations' then
           coalesce((select sum(d.n) from d where d.part = 'staff'), 0) = tot.n
           and coalesce((select sum(d.amount) from d where d.part = 'staff'), 0) = tot.amount
         else coalesce((select sum(d.amount) from d where d.part = 'staff'), 0) = tot.amount
           and coalesce((select sum(d.amount) from d where d.part in ('item', 'ticket')), 0) = tot.amount end
  into top_items, by_staff, n, adds_up;

  if tot.unreported > 0 then
    flags := flags || app.flag('partial_data',
      format('%s de %s días no reportan %s con su número: quedan fuera de las cifras.', tot.unreported, s.covered_days,
             case when kind = 'cancellations' then 'cancelaciones' else 'descuentos' end));
  end if;
  if kind = 'discounts' and exists (select 1 from app.discount_detail(locs, r[1], r[2]) d where d.part = 'item_day') then
    flags := flags || app.flag('count_by_day', 'Sin detalle por ticket: cada platillo con descuento cuenta una vez por día.');
  end if;
  if tot.amount > 0 and top_items = '[]' and by_staff = '[]' then
    flags := flags || app.flag('no_detail', 'La fuente no detalla por platillo ni por mesero.');
  elsif not adds_up then
    flags := flags || app.flag('partial_detail',
      'El detalle por platillo o mesero no cubre todo el total: algunos días no lo traen completo.');
  end if;
  if s.expected_covered < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.expected_covered, s.expected_days));
  end if;

  return app.rpc_ok(
    jsonb_build_object('kind', kind, 'count', n, 'amount', app.money(tot.amount),
                       'top_items', top_items, 'by_staff', by_staff),
    locs, flags, 100.0 * s.expected_covered / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- compare_locations -------------------------------------------------------------------------
-- The compare_periods metric per location (app.metric_value), ranked best first: highest first,
-- except food_cost_pct, where the lowest is best. diff_vs_best = value - the best value. A
-- location with no data for the metric is left out and named in a flag.
create function api.compare_locations(metric text, period jsonb, location_ids uuid[] default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[];
  r date[];
  s record;
  rows jsonb;
  missing text;
  levels app.cost_confidence[];
  flags jsonb := '[]';
begin
  if location_ids is null then
    locs := app.scope_locations(null);
  elsif cardinality(location_ids) = 0 then
    raise exception 'location_ids must not be empty' using errcode = '22023';
  else
    locs := array(select distinct u from unnest(location_ids) u where u is not null order by u);
    if cardinality(locs) <> (select count(*) from public.location l where l.id = any (locs))
       or cardinality(locs) <> cardinality(array(select distinct u from unnest(location_ids) u)) then
      return app.rpc_error('not_found', 'location not found');
    end if;
  end if;
  if metric is null or metric not in ('net_sales', 'tickets', 'avg_ticket', 'guests', 'food_cost_pct', 'units') then
    raise exception 'unknown metric: %', metric using errcode = '22023';
  end if;
  r := app.resolve_period(period, app.business_today(locs[1]));

  with v as (
    select l.id, l.name, (app.figure(metric, app.metric_value(metric, array[l.id], r[1], r[2])) ->> 'raw')::numeric as value
    from public.location l where l.id = any (locs)
  ), ranked as (
    select v.*, rank() over (order by case when metric = 'food_cost_pct' then v.value end asc,
                                      case when metric <> 'food_cost_pct' then v.value end desc) as rank,
           first_value(v.value) over (order by case when metric = 'food_cost_pct' then v.value end asc,
                                               case when metric <> 'food_cost_pct' then v.value end desc) as best
    from v where v.value is not null
  )
  select (select jsonb_agg(jsonb_build_object('location_id', x.id, 'name', x.name, 'value', app.figure(metric, x.value),
                                              'rank', x.rank, 'diff_vs_best', app.figure(metric, x.value - x.best, true))
                           order by x.rank, x.name, x.id) from ranked x),
         (select string_agg(v.name, ', ' order by v.name) from v where v.value is null)
  into rows, missing;

  if rows is null then
    return app.rpc_error('no_data', format('No %s data for the period', metric), locs);
  end if;
  if missing is not null then
    flags := flags || app.flag('missing_locations', 'Sin datos para: ' || missing || '.');
  end if;
  if metric = 'food_cost_pct' then
    select array_agg(distinct c.confidence) into levels
    from app.item_cost_rows(locs, r[1], r[2]) c where c.confidence is not null;
    flags := flags || app.confidence_flag(levels);
  end if;
  select * into s from app.sales_totals(locs, r[1], r[2]);
  if s.expected_covered < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.expected_covered, s.expected_days));
  end if;

  return app.rpc_ok(jsonb_build_object('metric', metric, 'rows', rows), locs, flags,
                    100.0 * s.expected_covered / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- Privileges --------------------------------------------------------------------------------
grant select on app.v_daily_payment_mix to authenticated;
grant execute on function
  app.paid_tickets(uuid[], date, date), app.staff_names(uuid[]), app.breakdown_rows(text, uuid[], date, date),
  app.cancellation_days(text, uuid[], date, date), app.cancellation_detail(uuid[], date, date),
  app.discount_detail(uuid[], date, date)
  to authenticated;
grant execute on function
  api.get_sales_breakdown(jsonb, text, uuid), api.get_cancellations(jsonb, text, uuid),
  api.compare_locations(text, jsonb, uuid[])
  to authenticated;
