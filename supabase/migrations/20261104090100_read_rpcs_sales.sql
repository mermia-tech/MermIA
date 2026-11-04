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

-- A staff member as the agent may see them: first name only (09 section 4.2).
create function app.first_name(staff uuid) returns text
language sql stable set search_path = ''
as $$
  select coalesce((select nullif(split_part(btrim(s.display_name), ' ', 1), '') from public.staff s where s.id = staff),
                  'Sin asignar')
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
    select app.first_name(pt.staff_id), sum(pt.total)::bigint, count(*), 0
    from app.paid_tickets(locs, f, t) pt group by pt.staff_id;
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
-- only some days have it the answer is flagged partial.
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
  if "by" in ('staff', 'hour', 'channel', 'payment_method') then
    select count(*) into detail_days from (
      select v.location_id, v.business_date from app.v_daily_sales v
      where v.location_id = any (locs) and v.business_date between r[1] and r[2]
        and (v.grain = 'ticket' or ("by" = 'payment_method' and exists (
          select 1 from app.v_daily_payment_mix x
          where x.location_id = v.location_id and x.business_date = v.business_date and x.payment_mix <> '{}')))) d;
    if detail_days < s.covered_days then
      flags := flags || app.flag('partial_data',
        format('Solo %s de %s días con ventas tienen este detalle.', detail_days, s.covered_days));
    end if;
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
-- Cancellations: count and amount follow each day's grain (the aggregate wins, MR-17 rule C);
-- the top 3 items (units and amount of cancelled or voided lines, largest amount first) and the
-- staff (a cancelled ticket counts once for its waiter, a voided line of a paid ticket once for
-- whoever voided it; most first) come from ticket records.
-- Discounts: the amount follows the day's grain; the top items are the dishes sold with a
-- discount (units of those rows and the discount); staff are the paid tickets with a discount.
-- `count` is the discounted units plus the tickets with a ticket-level discount.
create function app.cancellation_detail(locs uuid[], f date, t date)
returns table (part text, name text, n bigint, amount bigint)
language sql stable set search_path = ''
as $$
  with lines as (
    select l.menu_item_id, l.qty, l.net, coalesce(l.voided_by, tk.staff_id) as staff_id, tk.status
    from public.sale_line l
    join public.sale_ticket tk on tk.tenant_id = l.tenant_id and tk.id = l.ticket_id
    join public.import_batch b on b.tenant_id = tk.tenant_id and b.id = tk.batch_id
    where b.status = 'applied' and tk.location_id = any (locs) and tk.business_date between f and t
      and (l.is_void or tk.status = 'cancelled')
  ), tickets as (
    select tk.staff_id, tk.total
    from public.sale_ticket tk
    join public.import_batch b on b.tenant_id = tk.tenant_id and b.id = tk.batch_id
    where b.status = 'applied' and tk.status = 'cancelled'
      and tk.location_id = any (locs) and tk.business_date between f and t
  ), staff as (
    select tickets.staff_id, tickets.total as amount from tickets
    union all
    select lines.staff_id, lines.net from lines where lines.status = 'paid'
  )
  select 'item', m.name, round(sum(lines.qty))::bigint, sum(lines.net)::bigint
  from lines join public.menu_item m on m.id = lines.menu_item_id group by m.id, m.name
  union all
  select 'staff', app.first_name(staff.staff_id), count(*), sum(staff.amount)::bigint
  from staff group by staff.staff_id
$$;

create function app.discount_detail(locs uuid[], f date, t date)
returns table (part text, name text, n bigint, amount bigint)
language sql stable set search_path = ''
as $$
  select 'item', m.name, round(sum(v.units))::bigint, sum(v.discount)::bigint
  from app.v_item_sales_daily v join public.menu_item m on m.id = v.menu_item_id
  where v.location_id = any (locs) and v.business_date between f and t and v.discount > 0
  group by m.id, m.name
  union all
  select 'staff', app.first_name(x.staff_id), count(*), sum(x.discount)::bigint
  from (
    select pt.staff_id, pt.discount + coalesce((
      select sum(l.discount) from public.sale_line l where l.ticket_id = pt.id and not l.is_void), 0) as discount
    from app.paid_tickets(locs, f, t) pt
  ) x
  where x.discount > 0
  group by x.staff_id
  union all
  select 'ticket', null, count(*), sum(pt.discount)::bigint
  from app.paid_tickets(locs, f, t) pt where pt.discount > 0
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

  -- totals of the days that report the figure; a day that does not is flagged, never a zero
  select sum(case when kind = 'cancellations' then v.cancellations_count end)::bigint as n,
         sum(case when kind = 'cancellations' then v.cancellations_amount else v.discounts end)::bigint as amount,
         count(*) filter (where (case when kind = 'cancellations' then v.cancellations_amount else v.discounts end) is null)
           + s.item_only_days as unreported
  into tot
  from app.v_daily_sales v
  where v.location_id = any (locs) and v.business_date between r[1] and r[2];
  if tot.amount is null then
    return app.rpc_error('no_data', format('The source does not report %s for the period', kind), locs);
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
         else coalesce((select sum(d.n) from d where d.part in ('item', 'ticket')), 0) end
  into top_items, by_staff, n;

  if tot.unreported > 0 then
    flags := flags || app.flag('partial_data',
      format('%s de %s días no reportan %s.', tot.unreported, s.covered_days,
             case when kind = 'cancellations' then 'cancelaciones' else 'descuentos' end));
  end if;
  if tot.amount > 0 and top_items = '[]' and by_staff = '[]' then
    flags := flags || app.flag('no_detail', 'La fuente no detalla por platillo ni por mesero.');
  end if;
  if s.expected_covered < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.expected_covered, s.expected_days));
  end if;

  return app.rpc_ok(
    jsonb_build_object('kind', kind, 'count', coalesce(n, 0), 'amount', app.money(tot.amount),
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
  app.paid_tickets(uuid[], date, date), app.first_name(uuid), app.breakdown_rows(text, uuid[], date, date),
  app.cancellation_detail(uuid[], date, date), app.discount_detail(uuid[], date, date)
  to authenticated;
grant execute on function
  api.get_sales_breakdown(jsonb, text, uuid), api.get_cancellations(jsonb, text, uuid),
  api.compare_locations(text, jsonb, uuid[])
  to authenticated;
