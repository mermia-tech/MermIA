-- MR-24 review (PR #77, M2): IVA at the menu price's own rate in the MR-17 cost figures too.
--
-- 20261019200000_read_rpcs_first4.sql takes IVA out of item sales at 16 % (net - round(net x
-- 16 / 116)), while the engine nets each menu price at its tax_rate. In the northern border zone
-- (8 %) or for 0 % items, compare_periods('food_cost_pct'), compare_locations and get_top_dishes
-- (margin, margin_pct) then disagreed with get_dish_margin, get_food_cost_pct and the breaches.
-- They now read app.item_cost_rows (20261108090000_read_rpcs_cost.sql), whose net_ex_iva uses the
-- rate of the menu price in effect that day (16 % when unknown), summed unrounded and rounded
-- once. For a 16 % row nothing changes: round(sum(net) / 1.16) = sum(net) - round(sum(net) x
-- 16 / 116), since 29 is odd and the IVA is never a half centavo. Margins are rounded once per
-- dish over the period, no longer once per item and day. Same signatures, so the grants stay.
--
-- PR #77 review: units and revenue stay on app.item_rows (no IVA, no cost); the margins and the
-- food cost carry the answer's one confidence flag (cost_confirmed / cost_estimated, the weakest
-- snapshot behind the figures shown), as the MR-24 cost answers do.

-- Food cost over [f, t] and the confidence levels of the snapshots behind it.
create function app.food_cost(locs uuid[], f date, t date) returns table (pct numeric, levels app.cost_confidence[])
language sql stable set search_path = ''
as $$
  select 100 * sum(r.units * r.cost) / nullif(round(sum(r.net_ex_iva)), 0), array_agg(distinct r.confidence)
  from app.item_cost_rows(locs, f, t) r where r.cost is not null
$$;

create or replace function app.metric_value(metric text, locs uuid[], f date, t date) returns numeric
language sql stable set search_path = ''
as $$
  select case metric
    when 'net_sales' then (select case when s.covered_days > 0 then s.net_sales end from app.sales_totals(locs, f, t) s)
    when 'tickets' then (select s.tickets from app.sales_totals(locs, f, t) s where s.covered_days > 0)
    when 'guests' then (select s.guests from app.sales_totals(locs, f, t) s where s.covered_days > 0)
    when 'avg_ticket' then
      (select round(s.net_sales::numeric / s.tickets) from app.sales_totals(locs, f, t) s where s.tickets > 0)
    when 'units' then (select sum(r.units) from app.item_rows(locs, f, t) r)
    when 'food_cost_pct' then (select fc.pct from app.food_cost(locs, f, t) fc)
  end
$$;

create or replace function api.compare_periods(
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
  la app.cost_confidence[];
  lb app.cost_confidence[];
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
  if metric = 'food_cost_pct' then
    select fc.pct, fc.levels into a, la from app.food_cost(locs, ra[1], ra[2]) fc;
    select fc.pct, fc.levels into b, lb from app.food_cost(locs, rb[1], rb[2]) fc;
  else
    a := app.metric_value(metric, locs, ra[1], ra[2]);
    b := app.metric_value(metric, locs, rb[1], rb[2]);
  end if;
  if a is null or b is null then
    return app.rpc_error('no_data',
      format('No %s data for %s', metric, case when a is null then 'period_a' else 'period_b' end), locs);
  end if;
  -- raw figures are rounded to their scale before the change, so abs_change = a - b exactly
  a := ((app.figure(metric, a)) ->> 'raw')::numeric;
  b := ((app.figure(metric, b)) ->> 'raw')::numeric;

  if metric = 'food_cost_pct' then
    flags := flags || app.confidence_flag(la || lb);
  end if;
  select * into ca from app.sales_totals(locs, ra[1], ra[2]);
  select * into cb from app.sales_totals(locs, rb[1], rb[2]);
  if ca.expected_covered < ca.expected_days or cb.expected_covered < cb.expected_days then
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
    100.0 * (ca.expected_covered + cb.expected_covered) / nullif(ca.expected_days + cb.expected_days, 0), null);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

create or replace function api.get_top_dishes(
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
  levels app.cost_confidence[];
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
    select x.* from (
      select c.menu_item_id, c.units, c.net, c.cost, c.confidence, c.net_ex_iva
      from app.item_cost_rows(locs, r[1], r[2]) c where metric in ('margin', 'margin_pct')
      union all
      select i.menu_item_id, i.units, i.net, i.cost, null, null
      from app.item_rows(locs, r[1], r[2]) i where metric in ('units', 'revenue')
    ) x
    join public.menu_item m on m.id = x.menu_item_id
    left join public.menu_category c on c.id = m.category_id
    where category is null or lower(c.name) = lower(btrim(category))
  ), v as (
    select x.menu_item_id,
      case metric
        when 'units' then sum(x.units)
        when 'revenue' then sum(x.net)
        when 'margin' then round(sum(x.net_ex_iva)) - sum(x.units * x.cost)
        when 'margin_pct' then 100 * (round(sum(x.net_ex_iva)) - sum(x.units * x.cost))
                               / nullif(round(sum(x.net_ex_iva)), 0)
      end as value,
      array_agg(distinct x.confidence) filter (where x.confidence is not null) as levels
    from x
    where metric in ('units', 'revenue') or x.cost is not null
    group by x.menu_item_id
  ), ranked as (
    select v.menu_item_id, m.name, v.value, v.levels,
      row_number() over (order by case when "order" = 'desc' then v.value end desc nulls last,
                                  case when "order" = 'asc' then v.value end asc nulls last,
                                  m.name, v.menu_item_id) as rank
    from v join public.menu_item m on m.id = v.menu_item_id
    where v.value is not null
  )
  select jsonb_agg(jsonb_build_object('rank', ranked.rank, 'menu_item_id', ranked.menu_item_id,
                                      'name', ranked.name, 'value', app.figure(metric, ranked.value))
                   order by ranked.rank),
         (select count(*) from x where x.cost is null),
         (select array_agg(distinct l) from ranked k cross join unnest(k.levels) l where k.rank <= "limit")
  into rows, uncosted, levels
  from ranked where ranked.rank <= "limit";

  if rows is null then
    return app.rpc_error('no_data',
      case when metric in ('margin', 'margin_pct') then 'No costed dish sales for the period'
           else 'No dish sales loaded for the period' end, locs);
  end if;
  if metric in ('margin', 'margin_pct') then
    flags := flags || app.confidence_flag(levels);
  end if;
  if metric in ('margin', 'margin_pct') and uncosted > 0 then
    flags := flags || app.flag('uncosted_sales', 'Algunos platillos vendidos no tienen costo y no entran en el ranking.');
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

grant execute on function app.food_cost(uuid[], date, date) to authenticated;
