-- MR-24 review (PR #77, M2): IVA at the menu price's own rate in the MR-17 cost figures too.
--
-- 20261019200000_read_rpcs_first4.sql takes IVA out of item sales at 16 % (net - round(net x
-- 16 / 116)), while the engine nets each menu price at its tax_rate. In the northern border zone
-- (8 %) or for 0 % items, compare_periods('food_cost_pct'), compare_locations and get_top_dishes
-- (margin, margin_pct) then disagreed with get_dish_margin, get_food_cost_pct and the breaches.
-- They now read app.item_cost_rows (20261104090000_read_rpcs_cost.sql), whose net_ex_iva uses the
-- rate of the menu price in effect that day (16 % when unknown), summed unrounded and rounded
-- once. For a 16 % row nothing changes: round(sum(net) / 1.16) = sum(net) - round(sum(net) x
-- 16 / 116), since 29 is odd and the IVA is never a half centavo. Margins are rounded once per
-- dish over the period, no longer once per item and day. Same signatures, so the grants stay.

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
    when 'food_cost_pct' then
      (select 100 * sum(r.units * r.cost) / nullif(round(sum(r.net_ex_iva)), 0)
       from app.item_cost_rows(locs, f, t) r where r.cost is not null)
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
    select x.* from app.item_cost_rows(locs, r[1], r[2]) x
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
