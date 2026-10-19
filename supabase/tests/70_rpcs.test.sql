-- MR-17: the first 4 read RPCs against the El Güero seed (fixtures/el_guero/expected.json).
-- Runs as `authenticated` with member claims; the business date is pinned to the seed's today.
begin;
select * from no_plan();

\set TENANT '03299e41-28bd-5779-bcc6-0e5e76580fad'
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
\set OTHER_TENANT '''{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000009","location_ids":null}'''

-- periods ---------------------------------------------------------------------------------
select is(app.resolve_period('"last_week"', '2026-10-12'), array['2026-10-05', '2026-10-11']::date[], 'last_week of a Monday is the week before');
select is(app.resolve_period('"prev_week"', '2026-10-12'), array['2026-09-28', '2026-10-04']::date[], 'prev_week is the week before last');
select is(app.resolve_period('"this_week"', '2026-10-14'), array['2026-10-12', '2026-10-14']::date[], 'this_week runs Monday to today');
select is(app.resolve_period('"this_week"', '2026-10-18'), array['2026-10-12', '2026-10-18']::date[], 'a Sunday closes the week');
select is(app.resolve_period('"last_7d"', '2026-10-12'), array['2026-10-05', '2026-10-11']::date[], 'last_7d ends yesterday');
select is(app.resolve_period('"last_30d"', '2026-10-12'), array['2026-09-12', '2026-10-11']::date[], 'last_30d ends yesterday');
select is(app.resolve_period('"this_month"', '2026-10-12'), array['2026-10-01', '2026-10-12']::date[], 'this_month');
select is(app.resolve_period('"last_month"', '2026-03-15'), array['2026-02-01', '2026-02-28']::date[], 'last_month');
select is(app.resolve_period('{"from":"2026-10-01","to":"2026-10-03"}', '2026-10-12'), array['2026-10-01', '2026-10-03']::date[], 'explicit range');
select throws_ok($$select app.resolve_period('{"from":"2026-10-03","to":"2026-10-01"}', '2026-10-12')$$, '22023', null, 'reversed range is invalid');
select throws_ok($$select app.resolve_period('{"from":"2026-10-01"}', '2026-10-12')$$, '22023', null, 'a range needs both dates');
select throws_ok($$select app.resolve_period('{"from":"2026-10-01","to":"2026-10-03","x":1}', '2026-10-12')$$, '22023', null, 'unknown keys are invalid');
select throws_ok($$select app.resolve_period('{"from":"2026-02-30","to":"2026-03-01"}', '2026-10-12')$$, '22023', null, 'an impossible date is invalid');
select throws_ok($$select app.resolve_period('{"from":"2025-01-01","to":"2026-10-01"}', '2026-10-12')$$, '22023', null, 'a range over 366 days is invalid');
select throws_ok($$select app.resolve_period('"tomorrow"', '2026-10-12')$$, '22023', null, 'unknown names are invalid');
select is(app.previous_period('"this_week"', array['2026-10-12', '2026-10-14']::date[]), array['2026-10-05', '2026-10-07']::date[], 'this_week compares with the same days last week');
select is(app.previous_period('"this_month"', array['2026-03-01', '2026-03-31']::date[]), array['2026-02-01', '2026-02-28']::date[], 'this_month compares with the same days last month, clamped');
select is(app.previous_period('"last_month"', array['2026-09-01', '2026-09-30']::date[]), array['2026-08-01', '2026-08-31']::date[], 'last_month compares with the whole month before');
select is(app.previous_period('{"from":"2026-10-01","to":"2026-10-03"}', array['2026-10-01', '2026-10-03']::date[]), array['2026-09-28', '2026-09-30']::date[], 'a range compares with the days just before');

-- formatting ------------------------------------------------------------------------------
select is(app.fmt_money(18432050), '$184,320.50', 'money');
select is(app.fmt_money(-123456), '-$1,234.56', 'negative money');
select is(app.fmt_money(1241550, true), '+$12,415.50', 'a change carries its sign');
select is(app.fmt_money(0, true), '$0.00', 'no change has no sign');
select is(app.fmt_pct(7.2252, true), '+7.2%', 'percent change');
select is(app.fmt_pct(-0.04, true), '0.0%', 'a change that rounds to zero has no sign');
select is(app.fmt_pct(37.4567), '37.5%', 'percent, half away from zero');
select is(app.fmt_number(5880), '5,880', 'whole quantity');
select is(app.fmt_number(12.5), '12.5', 'decimal quantity');
select is(app.figure('food_cost_pct', -1.25, true), '{"raw": -1.25, "text": "-1.3 pts"}'::jsonb, 'a change of a percentage is in points');

-- unified-grain views (docs/superpowers/specs/2026-10-19-mr-17-read-rpc-sources-decision.md) ----
-- Mixed grain: Centro 2026-10-10 has the aggregate and 17 cancelled tickets, no paid ticket.
select is((select row(grain, net_sales, tickets, cancellations_amount, cancellations_count)::text from app.v_daily_sales
           where location_id = :'CENTRO' and business_date = '2026-10-10'),
          '(aggregate,3789500,134,265500,17)', 'cancelled tickets alone never override the aggregate: $37,895.00, 134 tickets');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"yesterday"', :'CENTRO'), '2026-10-11') #>> '{data,net_sales,raw}', '3789500',
          'and the RPC answers $37,895.00, neither replaced nor added to');
select is((select sum(units) from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-10'),
          (select sum(units) from public.item_sales_agg where location_id = :'CENTRO' and period_from = '2026-10-10'),
          'cancelled lines do not change the units sold on 2026-10-10');
select is((select count(*) from app.v_daily_sales v group by v.location_id, v.business_date having count(*) > 1 limit 1), null,
          'one row per location and day');
select is((select sum(net_sales) from app.v_daily_sales where location_id = :'CENTRO' and business_date between '2026-10-05' and '2026-10-11'),
          (select sum(d.net_sales) from public.daily_sales_agg d where d.location_id = :'CENTRO' and d.business_date between '2026-10-05' and '2026-10-11'),
          'Centro 2026-10-05..11 equals a direct sum of the seeded rows');
select is((select sum(net_sales) from app.v_daily_sales where location_id = :'CENTRO' and business_date between '2026-09-28' and '2026-10-04'),
          17190500::numeric, 'Centro 2026-09-28..10-04 is $171,905.00');
select throws_ok($$insert into public.sale_ticket (tenant_id, location_id, source_id, external_id, batch_id, business_date, subtotal, tax, total, status)
                   select s.tenant_id, s.location_id, s.id, 'no-batch', null, '2026-10-09', 0, 0, 0, 'paid' from public.source s
                   where s.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22' limit 1$$,
                 '23502', null, 'a ticket without a batch cannot exist (decision F)');

-- A paid ticket wins for its day: sales, tickets and items come from tickets only.
savepoint paid_ticket;
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status, applied_at)
select 'eeeeeeee-0000-7000-8000-000000000001', s.tenant_id, s.id, s.location_id, 'sr.erp_push@v1', 'paid-ticket-test', 'applied', '2026-10-10T09:00:00-06:00'
from public.source s where s.location_id = :'CENTRO' limit 1;
insert into public.sale_ticket (id, tenant_id, location_id, source_id, external_id, batch_id, business_date, guests, subtotal, discount, tax, total, status)
select 'eeeeeeee-0000-7000-8000-0000000000a1', b.tenant_id, b.location_id, b.source_id, 'P-1', b.id, '2026-10-09', 2, 10776, 0, 1724, 12500, 'paid'
from public.import_batch b where b.id = 'eeeeeeee-0000-7000-8000-000000000001';
insert into public.sale_line (tenant_id, location_id, source_id, batch_id, ticket_id, menu_item_id, qty, unit_price, discount, tax, net, is_void)
select t.tenant_id, t.location_id, t.source_id, t.batch_id, t.id, m.id, x.qty, 6500, x.disc, round((x.qty * 6500 - x.disc) * 16 / 116.0), x.qty * 6500 - x.disc, x.void
from public.sale_ticket t, public.menu_item m, (values (2, 500, false), (1, 0, true)) x(qty, disc, void)
where t.id = 'eeeeeeee-0000-7000-8000-0000000000a1' and m.external_id = 'P001';
select is((select row(grain, net_sales, tickets, guests, discounts)::text from app.v_daily_sales
           where location_id = :'CENTRO' and business_date = '2026-10-09'),
          '(ticket,12500,1,2,500)', 'a day with a paid ticket takes sales, tickets and discounts from tickets only');
select is((select count(*) from app.v_daily_sales where location_id = :'CENTRO' and business_date = '2026-10-09'), 1::bigint,
          'with no double count against the aggregate');
select is((select string_agg(grain || ':' || trim_scale(units), ',') from app.v_item_sales_daily
           where location_id = :'CENTRO' and business_date = '2026-10-09'),
          'ticket:2', 'items of that day come from non-voided ticket lines only');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '{"from":"2026-10-09","to":"2026-10-09"}', :'CENTRO')) #> '{data,avg_ticket,raw}',
          '12500', 'and the average ticket follows');
select is((select row(cancellations_amount, cancellations_count)::text from app.v_daily_sales
           where location_id = :'CENTRO' and business_date = '2026-10-09'),
          (select row(d.cancellations_amount, d.cancellations_count)::text from public.daily_sales_agg d
           where d.location_id = :'CENTRO' and d.business_date = '2026-10-09'),
          'cancellations stay with the aggregate on a ticket day (rule C)');
-- the same paid ticket in a batch that is not applied, then superseded, counts nowhere
update public.import_batch set status = 'received' where id = 'eeeeeeee-0000-7000-8000-000000000001';
select is((select grain from app.v_daily_sales where location_id = :'CENTRO' and business_date = '2026-10-09'), 'aggregate',
          'a paid ticket of a received batch does not take the day');
select is((select count(*) from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-09' and grain = 'ticket'), 0::bigint,
          'nor its lines');
update public.import_batch set status = 'superseded' where id = 'eeeeeeee-0000-7000-8000-000000000001';
select is((select grain from app.v_daily_sales where location_id = :'CENTRO' and business_date = '2026-10-09'), 'aggregate',
          'nor a superseded one');
select is((select count(*) from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-09' and grain = 'ticket'), 0::bigint,
          'nor its lines either');
rollback to savepoint paid_ticket;

-- Batch status: rows of non-applied and superseded batches appear in neither view.
savepoint batch_status;
update public.import_batch b set status = 'superseded'
where b.id in (select d.batch_id from public.daily_sales_agg d where d.location_id = :'CENTRO' and d.business_date = '2026-10-11'
               union select a.batch_id from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from = '2026-10-11');
select is((select count(*) from app.v_daily_sales where location_id = :'CENTRO' and business_date = '2026-10-11'), 0::bigint, 'superseded daily rows are out');
select is((select count(*) from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-11'), 0::bigint, 'superseded item rows are out');
update public.import_batch b set status = 'received'
where b.id in (select d.batch_id from public.daily_sales_agg d where d.location_id = :'CENTRO' and d.business_date = '2026-10-11'
               union select a.batch_id from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from = '2026-10-11');
select is((select count(*) from app.v_daily_sales where location_id = :'CENTRO' and business_date = '2026-10-11'), 0::bigint, 'received (not applied) daily rows are out');
select is((select count(*) from app.v_item_sales_daily where location_id = :'CENTRO' and business_date = '2026-10-11'), 0::bigint, 'received item rows are out');
rollback to savepoint batch_status;

-- The views follow RLS (security_invoker): a Polanco manager reads only Polanco through them.
select is(pg_temp.rpc(:POLANCO_MGR, '(select jsonb_agg(distinct location_id) from app.v_daily_sales)'), jsonb_build_array(:'POLANCO'), 'v_daily_sales follows RLS');
select is(pg_temp.rpc(:POLANCO_MGR, '(select jsonb_agg(distinct location_id) from app.v_item_sales_daily)'), jsonb_build_array(:'POLANCO'), 'v_item_sales_daily follows RLS');
select is(pg_temp.rpc(:OTHER_TENANT, '(select count(*)::text::jsonb from app.v_daily_sales)'), '0', 'another tenant reads nothing through them');

-- get_sales_summary -----------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO')) #> '{data,net_sales}',
          '{"raw": 18432050, "text": "$184,320.50"}', 'Centro last week: $184,320.50 (13 H3)');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO')) #> '{data,change_vs_previous}',
          '{"raw": 7.2223, "text": "+7.2%"}', 'up 7.2% on the week before ($171,905.00)');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO')) -> 'meta',
          '{"as_of": "2026-10-12T15:00:00+00:00", "coverage_pct": 100, "period_resolved": {"from": "2026-10-05", "to": "2026-10-11"}}',
          'meta: data as of the last applied batch, full coverage, resolved week');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"last_week"')) #>> '{data,net_sales,raw}', '34524130',
          'no location: every visible location (18,432,050 + 16,092,080)');
select is((select sum(d.net_sales) from public.daily_sales_agg d where d.business_date between '2026-10-05' and '2026-10-11')::text, '34524130',
          'which is the seed total');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO')) #>> '{data,avg_ticket,raw}',
          (select round(sum(net_sales)::numeric / sum(tickets))::text from public.daily_sales_agg
           where location_id = :'CENTRO' and business_date between '2026-10-05' and '2026-10-11'),
          'avg ticket = net sales / tickets');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"yesterday"', :'CENTRO'), '2026-10-11') #>> '{data,cancellations,raw}',
          '265500', 'the cancellation Saturday: $2,655.00');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"today"')) #>> '{error,code}', 'no_data', 'nothing loaded for today yet');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"last_week"'), '2026-10-14') -> 'flags',
          '[]', 'a Wednesday asking for last week has nothing missing');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"this_week"'), '2026-10-14') #>> '{error,code}', 'no_data',
          'this week has no data in the seed');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '{"from":"2026-10-05","to":"2026-10-13"}'), '2026-10-14') #>> '{flags,0,code}',
          'missing_days', 'days without data are flagged');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '{"from":"2026-10-05","to":"2026-10-13"}'), '2026-10-14') #>> '{meta,coverage_pct}',
          '77.8', 'and lower the coverage (14 of 18 location-days)');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"nope"')) #>> '{error,code}', 'invalid_args', 'a bad period is invalid_args');

-- only applied batches count (each case rolled back afterwards)
savepoint daily_only;
update public.import_batch b set status = 'rolled_back'
where b.id in (select d.batch_id from public.daily_sales_agg d where d.location_id = :'CENTRO' and d.business_date = '2026-10-11');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"yesterday"', :'CENTRO')) #> '{data,net_sales,raw}',
          (select to_jsonb(sum(a.net)) from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from = '2026-10-11'),
          'a day with item rows but no daily row takes its net sales from the items');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{data,tickets}', null,
          'and reports the other figures as unknown');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{flags,0,code}', 'partial_data', 'flagged partial');
rollback to savepoint daily_only;
savepoint whole_day;
update public.import_batch b set status = 'rolled_back'
where b.id in (select d.batch_id from public.daily_sales_agg d where d.location_id = :'CENTRO' and d.business_date = '2026-10-11'
               union select a.batch_id from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from = '2026-10-11');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{error,code}', 'no_data',
          'a rolled-back batch is not counted');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO')) #>> '{flags,0,code}', 'missing_days',
          'and its day shows as missing');
rollback to savepoint whole_day;

-- coverage counts only the days it expects (up to yesterday); a day loaded early adds sales only
savepoint early_day;
update public.import_batch b set status = 'rolled_back'
where b.id in (select d.batch_id from public.daily_sales_agg d where d.location_id = :'CENTRO' and d.business_date = '2026-10-07'
               union select a.batch_id from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from = '2026-10-07');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"this_week"'), '2026-10-11') #>> '{flags,0,code}', 'missing_days',
          'today''s early upload does not hide a missing day');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '"this_week"'), '2026-10-11') #>> '{meta,coverage_pct}', '91.7',
          'coverage: 11 of 12 expected location-days');
rollback to savepoint early_day;
select is(pg_temp.rpc(:OWNER, format('api.get_sales_summary(%L)', '{"from":"2026-10-10","to":"2026-10-11"}'), '2026-10-11') #>> '{meta,coverage_pct}', '100',
          'coverage never goes over 100');

-- two applied batches with item rows for the same location and day count once (the latest)
savepoint dup_items;
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status, applied_at)
select 'dddddddd-0000-7000-8000-000000000001', b.tenant_id, b.source_id, b.location_id, b.parser, 'dup-test', 'applied', b.applied_at + interval '1 hour'
from public.import_batch b where b.id = (select a.batch_id from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from = '2026-10-11' limit 1);
insert into public.item_sales_agg (tenant_id, location_id, source_id, batch_id, period_from, period_to, menu_item_id, units, gross, discount, net)
select a.tenant_id, a.location_id, a.source_id, 'dddddddd-0000-7000-8000-000000000001', a.period_from, a.period_to, a.menu_item_id, a.units, a.gross, a.discount, a.net
from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from = '2026-10-11';
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, location_id => %L)', '"yesterday"', 'units', :'CENTRO')) #> '{data,rows,0,value,raw}',
          (select to_jsonb(trim_scale(a.units)) from public.item_sales_agg a join public.menu_item m on m.id = a.menu_item_id
           where m.external_id = 'P001' and a.location_id = :'CENTRO' and a.period_from = '2026-10-11' and a.batch_id <> 'dddddddd-0000-7000-8000-000000000001'),
          'a re-sent item report does not double the units');
rollback to savepoint dup_items;

-- compare_periods -------------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L, %L)', 'net_sales', '"last_week"', '"prev_week"', :'POLANCO')) -> 'data',
          '{"metric": "net_sales", "period_a": {"from": "2026-10-05", "to": "2026-10-11"}, "period_b": {"from": "2026-09-28", "to": "2026-10-04"},
            "a": {"raw": 16092080, "text": "$160,920.80"}, "b": {"raw": 16161960, "text": "$161,619.60"},
            "abs_change": {"raw": -69880, "text": "-$698.80"}, "pct_change": {"raw": -0.4324, "text": "-0.4%"}}',
          'Polanco week on week (expected.json weekly_net_sales)');
select is(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L)', 'units', '"last_week"', '"prev_week"')) #>> '{data,abs_change,text}', '+225', 'units');
select is(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L)', 'food_cost_pct', '"last_week"', '"prev_week"')) #>> '{error,code}', 'no_data',
          'food cost needs dish costs (MR-25 writes them)');
select is(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L)', 'profit', '"last_week"', '"prev_week"')) #>> '{error,code}', 'invalid_args', 'unknown metric');

-- get_top_dishes --------------------------------------------------------------------------
select is((select jsonb_agg(jsonb_build_array(x ->> 'name', x #> '{value,raw}'))
           from jsonb_array_elements(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, location_id => %L)', '"this_month"', 'units', :'CENTRO')) #> '{data,rows}') x),
          '[["Tacos al pastor (orden de 3)", 656], ["Coca-Cola", 456], ["Tacos de bistec (orden de 3)", 308], ["Agua de horchata", 296], ["Tacos de suadero (orden de 3)", 270]]',
          'Centro top 5 this month by units (expected.json)');
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, %L, 1)', '"this_month"', 'units', 'asc')) #>> '{data,rows,0,rank}', '1', 'asc ranks from 1');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, "limit" => 10)', '"last_30d"', 'revenue')) #> '{data,rows}'), 10, 'limit 10');
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, "limit" => 11)', '"last_30d"', 'revenue')) #>> '{error,code}', 'invalid_args', 'limit over 10');
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, category => %L)', '"this_month"', 'units', 'bebidas')) #>> '{data,rows,0,name}', 'Coca-Cola',
          'category filter, case-insensitive');
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, category => %L)', '"this_month"', 'units', 'Mariscos')) #>> '{error,code}', 'not_found', 'unknown category');
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L)', '"this_month"', 'margin')) #>> '{error,code}', 'no_data', 'margin without dish costs');

-- margin from dish cost snapshots: pastor costs 1840 on 2026-10-11 at Centro
insert into public.dish_cost_snapshot (tenant_id, menu_item_id, location_id, date, cost, price_net, margin, confidence)
select :'TENANT', m.id, :'CENTRO', '2026-10-11', 1840, 5603, 3763, 'confirmed' from public.menu_item m where m.external_id = 'P001';
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, location_id => %L)', '"yesterday"', 'margin', :'CENTRO')) #> '{data,rows,0,value,raw}',
          (select to_jsonb((a.net - round(a.net * 16 / 116.0)) - a.units * 1840) from public.item_sales_agg a join public.menu_item m on m.id = a.menu_item_id
           where m.external_id = 'P001' and a.location_id = :'CENTRO' and a.period_from = '2026-10-11'),
          'margin = net without IVA - units x cost');
select is(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, location_id => %L)', '"yesterday"', 'margin', :'CENTRO')) #>> '{flags,0,code}', 'uncosted_sales',
          'dishes without a cost are flagged, not ranked');

-- get_data_status -------------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, 'api.get_data_status()') #> '{data,sources}', '[{"source_kind": "sr_report", "last_batch_at": "2026-10-12T15:00:00+00:00"}]', 'last batch per source kind');
select is(pg_temp.rpc(:OWNER, 'api.get_data_status()', '2026-10-15') #> '{data,missing_business_days}', '["2026-10-12", "2026-10-13", "2026-10-14"]',
          'business days without sales, up to yesterday');
select is(pg_temp.rpc(:OWNER, 'api.get_data_status()', '2026-10-15') #>> '{data,coverage,text}', '90.0%', 'coverage over the last 30 days (54 of 60 location-days)');
select is(pg_temp.rpc(:OWNER, 'api.get_data_status()') #>> '{data,stale_costs}',
          (select count(*)::text from public.ingredient i where exists (select 1 from public.recipe_line rl where rl.ingredient_id = i.id)
             and (select max(p.effective_from) from public.ingredient_price p where p.ingredient_id = i.id) < '2026-10-12'::date - 45),
          'stale costs: recipe ingredients whose newest price is over 45 days old');

-- isolation -------------------------------------------------------------------------------
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO')) #>> '{error,code}', 'not_found',
          'a Polanco manager cannot ask for Centro');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_sales_summary(%L)', '"last_week"')) #>> '{data,net_sales,raw}', '16092080',
          'and sees only Polanco without a location');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_top_dishes(%L, %L)', '"this_month"', 'units')) #>> '{data,rows,0,value,raw}', '552',
          'top dishes count only Polanco sales');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_sales_summary(%L)', '"last_week"')) #>> '{error,code}', 'no_data', 'another tenant sees no sales');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_sales_summary(%L, %L)', '"last_week"', :'CENTRO')) #>> '{error,code}', 'not_found',
          'nor El Güero''s locations');
select is(pg_temp.rpc(:OTHER_TENANT, 'api.get_data_status()') #> '{data,sources}', '[]', 'nor its sources');
select is(pg_temp.rpc('{}', format('api.get_sales_summary(%L)', '"last_week"')) #>> '{error,code}', 'no_data', 'no claims, no data');

select * from finish();
rollback;
