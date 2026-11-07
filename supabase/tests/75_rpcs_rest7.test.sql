-- MR-24: the remaining 7 read RPCs against the El Güero seed (fixtures/el_guero/expected.json).
-- Dish costs come from the MR-25 engine: the backend's job is run first (as the owner role),
-- then every RPC runs as `authenticated` with member claims and the seed's "today".
begin;
select * from no_plan();

\set TENANT '03299e41-28bd-5779-bcc6-0e5e76580fad'
\set CENTRO '705e8e51-376b-5785-adbb-405eff4e2a22'
\set POLANCO 'fdda5e3b-6bcd-5c48-a6de-f524be37463e'
\set PASTOR 'f496f051-9f85-5f8a-a4b6-c1a814d37c73'
\set COCA '6ad0cd19-1e20-5d83-89d9-f35cb46afd05'
\set TORTA '6a076c57-be40-5ece-b48f-4ab124f4e65c'
\set ALAMBRE '81404715-16f4-518e-b9e7-07df075161eb'

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

-- the backend's cost job: snapshots for every day the tests ask about
select ok(app.compute_dish_costs(:'TENANT', '2026-09-01', '2026-10-12') > 0, 'dish cost snapshots computed by the engine');

-- privileges ------------------------------------------------------------------------------
select ok(has_function_privilege('authenticated', 'app.recipe_cost(uuid, date, int)', 'execute'), 'the cost drivers walk recipes as the caller');
select ok(not has_function_privilege('authenticated', 'app.compute_dish_costs(uuid, date, date)', 'execute'), 'but clients still cannot write snapshots');

-- get_dish_margin -------------------------------------------------------------------------
select is((pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) -> 'data') - 'cost_drivers'::text - 'confidence'::text,
          format('{"match": "resolved", "menu_item_id": "%s", "location_id": "%s", "name": "Tacos al pastor (orden de 3)",
            "cost": {"raw": 1840, "text": "$18.40"}, "price_gross": {"raw": 6500, "text": "$65.00"},
            "net_price": {"raw": 5603, "text": "$56.03"}, "margin": {"raw": 3763, "text": "$37.63"},
            "margin_pct": {"raw": 67.1604, "text": "67.2%%"}, "food_cost": {"raw": 32.8396, "text": "32.8%%"}}', :'PASTOR', :'CENTRO')::jsonb,
          'pastor at Centro: cost $18.40, net $56.03, margin 67.2% on the net price (13 H3 example 4)');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) #>> '{data,confidence}', 'estimated',
          'with the engine''s confidence: seed prices are older than 30 days');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) #> '{data,cost_drivers,0}',
          '{"ingredient": "Carne al pastor (adobada)", "share": {"raw": 73.5448, "text": "73.5%"}}', 'the meat drives 73.5% of the cost');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) #> '{data,cost_drivers}'), 3,
          'top 3 cost drivers');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) #> '{meta,period_resolved}',
          '{"from": "2026-10-12", "to": "2026-10-12"}', 'the snapshot day is the period');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', :'PASTOR', :'POLANCO')) #> '{data,net_price,raw}', '6207',
          'by id, at Polanco ($72.00 menu price)');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', 'tacos al pastor')) -> 'data',
          format('{"match": "needs_location", "menu_item_id": "%s", "name": "Tacos al pastor (orden de 3)",
            "locations": [{"location_id": "%s", "name": "Centro"}, {"location_id": "%s", "name": "Polanco"}]}', :'PASTOR', :'CENTRO', :'POLANCO')::jsonb,
          'prices differ by location and none was asked: needs_location (D24)');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_dish_margin(%L)', 'tacos al pastor')) #>> '{data,location_id}', :'POLANCO',
          'a Polanco manager sees one location: resolved there');
select is((select jsonb_agg(c ->> 'name') from jsonb_array_elements(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', 'pastor')) #> '{data,candidates}') c),
          '["Tacos al pastor (orden de 3)", "Gringa de pastor", "Volcán de pastor", "Torta de pastor"]',
          'a fuzzy name with several dishes is ambiguous, best sellers first');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'VOLCAN', :'CENTRO')) #>> '{data,name}', 'Volcán de pastor',
          'accents and case do not matter');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'coca cola', :'CENTRO')) #>> '{data,name}', 'Coca-Cola',
          'an exact name wins over a longer one (Coca-Cola Light)');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', 'pizza')) #>> '{error,code}', 'not_found', 'no dish, not_found');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'sprite', :'CENTRO')) #>> '{error,code}', 'no_data',
          'a dish without a recipe has no margin');
savepoint same_name;
insert into public.menu_item (tenant_id, name, normalized_name, kind) values (:'TENANT', 'Coca Cola', 'coca cola', 'drink');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'coca cola', :'CENTRO')) #>> '{data,menu_item_id}', :'COCA',
          'two items with the same name: the costed one');
insert into public.menu_item (tenant_id, name, kind) values (:'TENANT', 'Pambazo', 'dish'), (:'TENANT', 'pambazo.', 'dish');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', 'Pambazo')) #>> '{data,match}', 'ambiguous',
          'and neither costed: ambiguous, never an arbitrary pick');
rollback to savepoint same_name;
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', '  ')) #>> '{error,code}', 'invalid_args', 'a blank dish is invalid');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO'), '2026-08-20') #>> '{error,code}', 'no_data',
          'no snapshot on or before today: no margin');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO'), '2026-10-20') #> '{meta,period_resolved,from}',
          '"2026-10-12"', 'otherwise the latest snapshot, dated in the meta');

-- get_food_cost_pct -----------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L, %L, %L)', '"yesterday"', :'CENTRO', 'category')) -> 'data',
          '{"theoretical": {"raw": 37.4569, "text": "37.5%"}, "target": {"raw": 32, "text": "32.0%"},
            "coverage": {"raw": 71.3736, "text": "71.4%"},
            "by_category": [{"category": "Tacos", "food_cost": {"raw": 36.1709, "text": "36.2%"}},
                            {"category": "Especialidades", "food_cost": {"raw": 43.1795, "text": "43.2%"}},
                            {"category": "Bebidas", "food_cost": {"raw": 36.7929, "text": "36.8%"}}]}',
          'Centro yesterday: 37.5% on 71.4% of sales (expected.json food_cost_yesterday), categories by sales');
select is(pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{data,theoretical,raw}',
          pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L, %L)', 'food_cost_pct', '"yesterday"', '"yesterday"', :'CENTRO')) #>> '{data,a,raw}',
          'the same figure as compare_periods(food_cost_pct)');
select is(pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L, %L)', '"yesterday"', :'CENTRO')) #> '{data,by_category}', '[]', 'no grouping by default');
select is(pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{flags,0,code}', 'cost_estimated',
          'the figure carries its confidence');
select is(pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L)', '{"from":"2026-08-17","to":"2026-08-23"}')) #>> '{error,code}', 'no_data',
          'no snapshots, no food cost');
select is(pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L, group_by => %L)', '"yesterday"', 'dish')) #>> '{error,code}', 'invalid_args', 'unknown group_by');
savepoint confirmed;
update public.dish_cost_snapshot set confidence = 'confirmed';
select is(pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{flags,0,code}', 'cost_confirmed',
          'all snapshots confirmed: cost_confirmed');
rollback to savepoint confirmed;

-- get_sales_breakdown ---------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"yesterday"', 'payment_method', :'CENTRO')) #> '{data,rows}',
          '[{"key": "card", "net_sales": {"raw": 1778115, "text": "$17,781.15"}, "tickets": null, "share": {"raw": 57, "text": "57.0%"}},
            {"key": "cash", "net_sales": {"raw": 1123020, "text": "$11,230.20"}, "tickets": null, "share": {"raw": 36, "text": "36.0%"}},
            {"key": "transfer", "net_sales": {"raw": 218365, "text": "$2,183.65"}, "tickets": null, "share": {"raw": 7, "text": "7.0%"}}]',
          'payment mix of the daily aggregate; no ticket count per method (D23)');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"yesterday"', 'category', :'CENTRO')) #> '{data,rows,0}',
          '{"key": "Tacos", "net_sales": {"raw": 1523500, "text": "$15,235.00"}, "tickets": null, "share": {"raw": 48.838, "text": "48.8%"}}',
          'by category from item sales');
savepoint no_items;
update public.import_batch b set status = 'rolled_back'
where b.id in (select a.batch_id from public.item_sales_agg a where a.location_id = :'CENTRO' and a.period_from = '2026-10-11');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"last_week"', 'category', :'CENTRO')) #>> '{flags,0,code}', 'partial_data',
          'a day with a daily total but no item report makes the category breakdown partial');
rollback to savepoint no_items;
select is((select sum((x #>> '{net_sales,raw}')::bigint) from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L)', '"last_week"', 'weekday')) #> '{data,rows}') x),
          34524130::numeric, 'weekdays add up to last week''s net sales');
select is((select jsonb_agg(x ->> 'key') from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L)', '"last_week"', 'weekday')) #> '{data,rows}') x),
          '["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]', 'weekdays in week order');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L)', '"last_week"', 'staff')) #>> '{error,code}', 'no_data',
          'staff needs ticket data, which the seed has for paid sales nowhere');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L)', '"last_week"', 'table')) #>> '{error,code}', 'invalid_args', 'unknown dimension');

-- a paid ticket day at Centro: staff, hour, channel and payments come from tickets
savepoint paid_ticket;
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status, applied_at)
select 'eeeeeeee-0000-7000-8000-000000000101', s.tenant_id, s.id, s.location_id, 'sr.erp_push@v1', 'mr24-ticket', 'applied', '2026-10-12T09:00:00-06:00'
from public.source s where s.location_id = :'CENTRO' limit 1;
insert into public.sale_ticket (id, tenant_id, location_id, source_id, external_id, batch_id, business_date, opened_at, closed_at, channel, staff_id, subtotal, discount, tax, total, status)
select x.id::uuid, b.tenant_id, b.location_id, b.source_id, x.ext, b.id, '2026-10-11', x.at::timestamptz, x.at::timestamptz + interval '20 minutes', x.ch::app.sale_channel,
       (select st.id from public.staff st where st.display_name = x.waiter and st.location_id = :'CENTRO'), round(x.total / 1.16), x.disc, x.total - round(x.total / 1.16), x.total, 'paid'
from public.import_batch b,
     (values ('eeeeeeee-0000-7000-8000-0000000001a1', 'T-1', '2026-10-11T13:05:00-06:00', 'dine_in', 'Pepe', 13000, 0),
             ('eeeeeeee-0000-7000-8000-0000000001a2', 'T-2', '2026-10-11T13:20:00-06:00', 'takeout', 'Ana', 6000, 500),
             ('eeeeeeee-0000-7000-8000-0000000001a3', 'T-3', '2026-10-11T20:10:00-06:00', 'dine_in', 'Pepe', 3500, 0)) x(id, ext, at, ch, waiter, total, disc)
where b.id = 'eeeeeeee-0000-7000-8000-000000000101';
insert into public.payment (tenant_id, location_id, source_id, batch_id, ticket_id, method, amount)
select t.tenant_id, t.location_id, t.source_id, t.batch_id, t.id, case when t.external_id = 'T-1' then 'card' else 'cash' end::app.payment_method, t.total
from public.sale_ticket t where t.batch_id = 'eeeeeeee-0000-7000-8000-000000000101';
select is((select jsonb_agg(jsonb_build_array(x ->> 'key', x #> '{net_sales,raw}', x -> 'tickets')) from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"yesterday"', 'staff', :'CENTRO')) #> '{data,rows}') x),
          '[["Pepe", 16500, 2], ["Ana", 6000, 1]]', 'by staff: first names, ticket totals and counts');
select is((select jsonb_agg(x ->> 'key') from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"yesterday"', 'hour', :'CENTRO')) #> '{data,rows}') x),
          '["13:00", "20:00"]', 'by hour in the location''s time zone, in hour order');
select is((select jsonb_agg(jsonb_build_array(x ->> 'key', x -> 'tickets')) from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"yesterday"', 'payment_method', :'CENTRO')) #> '{data,rows}') x),
          '[["card", 1], ["cash", 2]]', 'a ticket day takes its payments from tickets, with counts');
select is(pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"last_week"', 'channel', :'CENTRO')) #>> '{flags,0,code}', 'partial_data',
          'only one day of the week has tickets: partial');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L, %L)', '"yesterday"', 'discounts', :'CENTRO')) #> '{data,by_staff}',
          '[{"name": "Ana", "count": 1, "amount": {"raw": 500, "text": "$5.00"}}]', 'discounted tickets by staff');
rollback to savepoint paid_ticket;

-- get_cancellations -----------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L, %L)', '{"from":"2026-10-10","to":"2026-10-10"}', 'cancellations', :'CENTRO')) -> 'data',
          '{"kind": "cancellations", "count": 17, "amount": {"raw": 265500, "text": "$2,655.00"},
            "top_items": [{"name": "Tacos al pastor (orden de 3)", "count": 7, "amount": {"raw": 45500, "text": "$455.00"}},
                          {"name": "Huarache de bistec", "count": 4, "amount": {"raw": 38000, "text": "$380.00"}},
                          {"name": "Churros (orden de 3)", "count": 6, "amount": {"raw": 27000, "text": "$270.00"}}],
            "by_staff": [{"name": "Pepe", "count": 8, "amount": {"raw": 152000, "text": "$1,520.00"}},
                         {"name": "Luis", "count": 5, "amount": {"raw": 46500, "text": "$465.00"}},
                         {"name": "Ana", "count": 3, "amount": {"raw": 55500, "text": "$555.00"}},
                         {"name": "Marta", "count": 1, "amount": {"raw": 11500, "text": "$115.00"}}]}',
          'the cancellation Saturday: 17 tickets, $2,655.00, by item and by waiter (13 H3 example 7)');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '{"from":"2026-08-17","to":"2026-08-17"}', :'CENTRO')) #>> '{data,count}', '3',
          'an aggregate-only day still has its count and amount');
savepoint null_count;
update public.daily_sales_agg set cancellations_count = null where location_id = :'CENTRO' and business_date = '2026-10-09';
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '"last_week"', :'CENTRO')) #>> '{flags,0,code}', 'partial_data',
          'a day that reports the amount but not the count is flagged, not counted as zero');
rollback to savepoint null_count;
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '{"from":"2026-08-17","to":"2026-08-17"}', :'CENTRO')) #>> '{flags,0,code}', 'no_detail',
          'and says it has no detail by item or waiter');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L)', '"last_week"', 'discounts')) #> '{data,top_items,0}',
          (select format('{"name": "Tacos al pastor (orden de 3)", "count": %s, "amount": {"raw": 83570, "text": "$835.70"}}', count(*))::jsonb
           from public.item_sales_agg a join public.menu_item m on m.id = a.menu_item_id
           where m.external_id = 'P001' and a.discount > 0 and a.period_from between '2026-10-05' and '2026-10-11'),
          'discounts: the Martes de pastor promotion, once per dish and day without tickets');
select is((select jsonb_agg(f ->> 'code') from jsonb_array_elements(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L)', '"last_week"', 'discounts')) -> 'flags') f),
          '["count_by_day", "partial_detail"]', 'and says how it counted, and that no waiter detail covers those days');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L)', '"last_week"', 'discounts')) #>> '{data,amount,raw}',
          (select sum(d.discounts)::text from public.daily_sales_agg d where d.business_date between '2026-10-05' and '2026-10-11'),
          'the discount amount is the daily figure');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L)', '"last_week"', 'voids')) #>> '{error,code}', 'invalid_args', 'unknown kind');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L)', '"today"')) #>> '{error,code}', 'no_data', 'nothing loaded today');

-- compare_locations -----------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L, %L)', 'net_sales', '"last_week"', array[:'CENTRO', :'POLANCO'])) -> 'data',
          format('{"metric": "net_sales", "rows": [
            {"location_id": "%s", "name": "Centro", "value": {"raw": 18432050, "text": "$184,320.50"}, "rank": 1, "diff_vs_best": {"raw": 0, "text": "$0.00"}},
            {"location_id": "%s", "name": "Polanco", "value": {"raw": 16092080, "text": "$160,920.80"}, "rank": 2, "diff_vs_best": {"raw": -2339970, "text": "-$23,399.70"}}]}',
            :'CENTRO', :'POLANCO')::jsonb,
          'last week: Centro first, Polanco $23,399.70 behind');
select is((select jsonb_agg(jsonb_build_array(x ->> 'name', x -> 'rank', x #>> '{diff_vs_best,text}')) from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L)', 'food_cost_pct', '"last_week"')) #> '{data,rows}') x),
          '[["Polanco", 1, "0.0 pts"], ["Centro", 2, "+3.5 pts"]]', 'food cost: the lowest is best');
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L)', 'food_cost_pct', '"last_week"')) #>> '{flags,0,code}', 'cost_estimated',
          'with its confidence');
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L, %L)', 'tickets', '"last_week"', array[:'CENTRO', :'CENTRO'])) #> '{data,rows,0,value,raw}',
          (select to_jsonb(sum(d.tickets)) from public.daily_sales_agg d where d.location_id = :'CENTRO' and d.business_date between '2026-10-05' and '2026-10-11'),
          'a repeated id counts once');
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L, %L)', 'net_sales', '"last_week"', '{}')) #>> '{error,code}', 'invalid_args', 'an empty list is invalid');
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L)', 'profit', '"last_week"')) #>> '{error,code}', 'invalid_args', 'unknown metric');
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L)', 'net_sales', '"today"')) #>> '{error,code}', 'no_data', 'no data for any location');

-- get_menu_engineering --------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.get_menu_engineering(%L, %L)', '"last_30d"', :'CENTRO')) -> 'data',
          '{"quadrants": [
            {"name": "star", "count": 5, "top_items": ["Tacos al pastor (orden de 3)", "Tacos de bistec (orden de 3)", "Tacos de suadero (orden de 3)"]},
            {"name": "plowhorse", "count": 5, "top_items": ["Coca-Cola", "Agua de horchata", "Cerveza Corona"]},
            {"name": "puzzle", "count": 3, "top_items": ["Tacos de longaniza (orden de 3)", "Torta de pastor", "Alambre de res"]},
            {"name": "dog", "count": 2, "top_items": ["Agua mineral", "Volcán de pastor"]}]}',
          'Centro, last 30 days: Kasavana-Smith over the 15 costed dishes');
select is((select jsonb_agg(f ->> 'code') from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_menu_engineering(%L, %L)', '"last_30d"', :'CENTRO')) -> 'flags') f),
          '["cost_estimated", "uncosted_sales"]', 'confidence, and the dishes without a recipe are named as left out');
select is(pg_temp.rpc(:OWNER, format('api.get_menu_engineering(%L)', '{"from":"2026-08-17","to":"2026-08-23"}')) #>> '{error,code}', 'no_data',
          'no snapshots, no analysis');
select is(pg_temp.rpc(:OWNER, format('api.get_menu_engineering(%L)', '"never"')) #>> '{error,code}', 'invalid_args', 'a bad period');

-- get_cost_alerts -------------------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}',
          '[{"ingredient": "Carne al pastor (adobada)", "change": {"raw": 14.7059, "text": "+14.7%"},
             "new_unit_price": {"raw": 0.195, "base_unit": "g", "text": "$195.00/kg"}},
            {"ingredient": "Aguacate Hass", "change": {"raw": 61.8182, "text": "+61.8%"},
             "new_unit_price": {"raw": 0.089, "base_unit": "g", "text": "$89.00/kg"}}]',
          'the two price jumps of the seed, $170 to $195/kg and $55 to $89/kg');
savepoint zero_price;
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
select :'TENANT', i.id, 0, '2026-10-12', 'manual' from public.ingredient i where i.name = 'Aguacate Hass';
select is((select jsonb_agg(m ->> 'ingredient') from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}') m),
          '["Carne al pastor (adobada)"]', 'a zero price is not a move (the contract needs a price above zero)');
rollback to savepoint zero_price;
select is(pg_temp.rpc(:OWNER, 'api.get_cost_alerts()') #> '{data,price_moves}', '[]', 'neither is in the last 7 days');
select is(pg_temp.rpc(:OWNER, 'api.get_cost_alerts()') #> '{meta,period_resolved}', '{"from": "2026-10-05", "to": "2026-10-12"}',
          'the window runs from the start of `since` through today');
select is((select jsonb_agg(jsonb_build_array(b ->> 'name', b #> '{food_cost,raw}')) from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,breaches}') b),
          '[["Coca-Cola", 54.1377], ["Torta de pastor", 50.0072], ["Alambre de res", 49.088], ["Agua mineral", 46.4037], ["Cerveza Corona", 46.4037],
            ["Gringa de pastor", 43.054], ["Tacos de bistec (orden de 3)", 39.1587], ["Tacos de suadero (orden de 3)", 38.83], ["Volcán de pastor", 37.6901]]',
          'dishes above target + 3 pts, highest first (pastor at 32.8% is not one)');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,breaches,0,target}',
          '{"raw": 32, "text": "32.0%"}', 'against the 32% target');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #>> '{flags,0,code}', 'cost_estimated', 'breaches carry their confidence');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'POLANCO')) #> '{data,breaches}'),
          (select count(*)::int from public.dish_cost_snapshot s where s.location_id = :'POLANCO' and s.date = '2026-10-12' and s.food_cost_pct > 35),
          'Polanco has its own breaches');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L)', '"tomorrow"')) #>> '{error,code}', 'invalid_args', 'a bad since');

savepoint suggestions;
-- rows as app.write_price_suggestions writes them (98_price_suggestions tests the writer)
insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value, threshold,
                                     current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code, status)
select :'TENANT', x.loc, x.item, '2026-10-12', '2026-10-01', 'margin_breach', 50, 35, app.menu_price_on(x.item, x.loc, '2026-10-12'),
       12503, null, null, 'estimated', 'review_portion_cost', x.status
from (values (:'CENTRO'::uuid, :'TORTA'::uuid, 'open'), (:'CENTRO', :'ALAMBRE', 'applied'), (:'POLANCO', :'TORTA', 'open')) x(loc, item, status);
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(location_id => %L)', :'CENTRO')) #> '{data,suggestions}',
          format('[{"menu_item_id": "%s", "location_id": "%s", "name": "Torta de pastor",
                    "current_price": {"raw": 8000, "text": "$80.00"}, "target_price": {"raw": 12503, "text": "$125.03"},
                    "suggested_price": null, "change": null, "new_food_cost": null,
                    "confidence": "estimated", "rationale_code": "review_portion_cost"}]', :'TORTA', :'CENTRO')::jsonb,
          'open suggestions only, with the dish and its current price');
select is(pg_temp.rpc(:POLANCO_MGR, 'api.get_cost_alerts()') #>> '{data,suggestions,0,location_id}', :'POLANCO',
          'a Polanco manager sees Polanco''s suggestion only (RLS)');
select is(jsonb_array_length(pg_temp.rpc(:POLANCO_MGR, 'api.get_cost_alerts()') #> '{data,suggestions}'), 1,
          'and not Centro''s');
rollback to savepoint suggestions;

-- isolation: a location-limited manager and another tenant ----------------------------------
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) #>> '{error,code}', 'not_found',
          'get_dish_margin: a Polanco manager cannot ask for Centro');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_food_cost_pct(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{error,code}', 'not_found',
          'get_food_cost_pct: nor here');
select isnt(pg_temp.rpc(:POLANCO_MGR, format('api.get_food_cost_pct(%L)', '"yesterday"')) #>> '{data,theoretical,raw}',
            pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L)', '"yesterday"')) #>> '{data,theoretical,raw}',
            'get_food_cost_pct: without a location, the manager''s figure is Polanco''s only');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_sales_breakdown(%L, %L)', '"yesterday"', 'category')) #>> '{data,rows,0,net_sales,raw}',
          (select sum(a.net)::text from public.item_sales_agg a join public.menu_item m on m.id = a.menu_item_id
           join public.menu_category c on c.id = m.category_id where c.name = 'Tacos' and a.location_id = :'POLANCO' and a.period_from = '2026-10-11'),
          'get_sales_breakdown: Polanco''s sales only');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_cancellations(%L, location_id => %L)', '{"from":"2026-10-10","to":"2026-10-10"}', :'CENTRO')) #>> '{error,code}', 'not_found',
          'get_cancellations: Centro is not visible');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_cancellations(%L)', '{"from":"2026-10-10","to":"2026-10-10"}')) #> '{data,by_staff}', '[]',
          'and Centro''s waiters do not show up');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.compare_locations(%L, %L, %L)', 'net_sales', '"last_week"', array[:'CENTRO', :'POLANCO'])) #>> '{error,code}', 'not_found',
          'compare_locations: asking for Centro is not_found');
select is(jsonb_array_length(pg_temp.rpc(:POLANCO_MGR, format('api.compare_locations(%L, %L)', 'net_sales', '"last_week"')) #> '{data,rows}'), 1,
          'and without a list only Polanco is compared');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_menu_engineering(%L, %L)', '"last_30d"', :'CENTRO')) #>> '{error,code}', 'not_found',
          'get_menu_engineering: Centro is not visible');
select is(pg_temp.rpc(:POLANCO_MGR, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #>> '{error,code}', 'not_found',
          'get_cost_alerts: Centro is not visible');

select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_dish_margin(%L)', 'tacos al pastor')) #>> '{error,code}', 'not_found',
          'get_dish_margin: another tenant does not find El Güero''s dishes');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_dish_margin(%L)', :'PASTOR')) #>> '{error,code}', 'not_found', 'not even by id');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_food_cost_pct(%L)', '"yesterday"')) #>> '{error,code}', 'no_data', 'get_food_cost_pct: another tenant has no costs');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_sales_breakdown(%L, %L)', '"yesterday"', 'payment_method')) #>> '{error,code}', 'no_data',
          'get_sales_breakdown: another tenant has no sales');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_cancellations(%L)', '"last_week"')) #>> '{error,code}', 'no_data', 'get_cancellations: nor cancellations');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.compare_locations(%L, %L, %L)', 'net_sales', '"last_week"', array[:'CENTRO'])) #>> '{error,code}', 'not_found',
          'compare_locations: El Güero''s locations do not exist for another tenant');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_menu_engineering(%L)', '"last_30d"')) #>> '{error,code}', 'no_data', 'get_menu_engineering: nothing');
select is(pg_temp.rpc(:OTHER_TENANT, format('api.get_cost_alerts(%L)', '"last_30d"')) -> 'data',
          '{"price_moves": [], "price_moves_total": 0, "breaches": [], "breaches_total": 0, "suggestions": [], "suggestions_total": 0}', 'get_cost_alerts: no prices, dishes or suggestions of El Güero');
select is(pg_temp.rpc('{}', format('api.get_cost_alerts(%L)', '"last_30d"')) -> 'data',
          '{"price_moves": [], "price_moves_total": 0, "breaches": [], "breaches_total": 0, "suggestions": [], "suggestions_total": 0}', 'no claims, no alerts');

-- PR #77 review fixes ---------------------------------------------------------------------
-- H1: a day that reports the amount but not the count adds to neither; no count at all is no_data
savepoint h1;
update public.daily_sales_agg set cancellations_count = null where location_id = :'CENTRO' and business_date = '2026-10-09';
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '"last_week"', :'CENTRO')) #> '{data,amount,raw}',
          (select to_jsonb(sum(d.cancellations_amount)) from public.daily_sales_agg d
           where d.location_id = :'CENTRO' and d.business_date between '2026-10-05' and '2026-10-11' and d.business_date <> '2026-10-09'),
          'H1: count and amount come from the same days (the day without a count is left out of both)');
update public.daily_sales_agg set cancellations_count = null where location_id = :'CENTRO';
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '"last_week"', :'CENTRO')) #>> '{error,code}', 'no_data',
          'H1: no day reports a count: no_data, never count 0');
rollback to savepoint h1;
savepoint h1_discounts;
update public.import_batch b set status = 'rolled_back'
where b.id in (select a.batch_id from public.item_sales_agg a where a.location_id = :'CENTRO');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L, %L)', '{"from":"2026-10-06","to":"2026-10-06"}', 'discounts', :'CENTRO')) #>> '{error,code}', 'no_data',
          'H1: discounts on an aggregate day with no item detail have no count: no_data, never count 0');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L, %L)', '"last_week"', 'discounts', :'CENTRO')) #> '{data,amount,raw}', '0',
          'H1: over the week, only the days with a count add to the amount (the discount days have none)');
select ok(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L, %L)', '"last_week"', 'discounts', :'CENTRO')) -> 'flags' @> '[{"code": "partial_data"}]',
          'H1: and they are flagged');
rollback to savepoint h1_discounts;

-- M1 / N1: the detail covers what the totals cover, and says so when it does not add up
select ok(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '"last_week"', :'CENTRO')) -> 'flags'
            @> '[{"code": "partial_detail"}]',
          'M1: last week''s detail (one day of tickets) does not add up to the totals: partial_detail');
select ok(not (pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L, %L)', '{"from":"2026-10-10","to":"2026-10-10"}', 'cancellations', :'CENTRO')) -> 'flags'
            @> '[{"code": "partial_detail"}]'), 'M1: the Saturday''s detail adds up: no flag');
savepoint ticket_cancel;
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status, applied_at)
select 'eeeeeeee-0000-7000-8000-000000000201', s.tenant_id, s.id, s.location_id, 'sr.erp_push@v1', 'mr24-cancel', 'applied', '2026-10-12T09:00:00-06:00'
from public.source s where s.location_id = :'CENTRO' limit 1;
insert into public.sale_ticket (id, tenant_id, location_id, source_id, external_id, batch_id, business_date, opened_at, closed_at, channel, staff_id, subtotal, discount, tax, total, status)
select x.id::uuid, b.tenant_id, b.location_id, b.source_id, x.ext, b.id, '2026-10-12', '2026-10-12T13:00:00-06:00', '2026-10-12T13:30:00-06:00', 'dine_in',
       (select st.id from public.staff st where st.display_name = x.waiter and st.location_id = :'CENTRO'), round(x.total / 1.16), 0, x.total - round(x.total / 1.16), x.total, x.status::app.ticket_status
from public.import_batch b,
     (values ('eeeeeeee-0000-7000-8000-0000000002a1', 'P-1', 'Pepe', 13000, 'paid'),
             ('eeeeeeee-0000-7000-8000-0000000002a2', 'C-1', 'Ana', 20000, 'cancelled')) x(id, ext, waiter, total, status)
where b.id = 'eeeeeeee-0000-7000-8000-000000000201';
insert into public.sale_line (tenant_id, location_id, source_id, batch_id, ticket_id, menu_item_id, qty, unit_price, net, is_void, voided_by)
select b.tenant_id, b.location_id, b.source_id, b.id, x.ticket::uuid, x.item::uuid, x.qty, x.net, x.net, x.void,
       case when x.void then (select st.id from public.staff st where st.display_name = 'Pepe' and st.location_id = :'CENTRO') end
from public.import_batch b,
     (values ('eeeeeeee-0000-7000-8000-0000000002a1', :'PASTOR', 2, 13000, false),
             ('eeeeeeee-0000-7000-8000-0000000002a1', :'PASTOR', 1, 15000, true),
             ('eeeeeeee-0000-7000-8000-0000000002a2', :'PASTOR', 0.4, 12000, false),
             ('eeeeeeee-0000-7000-8000-0000000002a2', :'COCA', -1, 8000, false)) x(ticket, item, qty, net, void)
where b.id = 'eeeeeeee-0000-7000-8000-000000000201';
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '"today"', :'CENTRO')) #> '{data,by_staff}',
          '[{"name": "Ana", "count": 1, "amount": {"raw": 20000, "text": "$200.00"}}]',
          'M1: a ticket day''s staff detail is its cancelled tickets, as its totals are (no voided line of a paid ticket)');
select is(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '"today"', :'CENTRO')) #> '{data,top_items}',
          '[{"name": "Tacos al pastor (orden de 3)", "count": 1, "amount": {"raw": 12000, "text": "$120.00"}},
            {"name": "Coca-Cola", "count": 0, "amount": {"raw": 8000, "text": "$80.00"}}]',
          'N2: a weighed line counts once and a negative quantity never makes a negative count');
rollback to savepoint ticket_cancel;

-- M2: IVA follows the menu price's tax rate in every cost RPC (8 % in the northern border zone)
savepoint border;
update public.menu_item_price set tax_rate = 0.08 where location_id = :'CENTRO';
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-11') > 0, 'M2: snapshots recomputed at 8 % IVA');
select is((pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{data,theoretical,raw}')::numeric,
          (select round(100 * sum(v.units * c.cost) / round(sum(v.net / 1.08)), 4)
           from app.v_item_sales_daily v join public.dish_cost_snapshot c
             on c.menu_item_id = v.menu_item_id and c.location_id = v.location_id and c.date = v.business_date
           where v.location_id = :'CENTRO' and v.business_date = '2026-10-11'),
          'M2: get_food_cost_pct takes IVA out at the item''s rate');
select is(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L, %L)', 'food_cost_pct', '"yesterday"', '"yesterday"', :'CENTRO')) #>> '{data,a,raw}',
          pg_temp.rpc(:OWNER, format('api.get_food_cost_pct(%L, %L)', '"yesterday"', :'CENTRO')) #>> '{data,theoretical,raw}',
          'M2: and compare_periods says the same');
select is((select (x #>> '{value,raw}')::numeric from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, %L, %s, %L)', '"yesterday"', 'margin', 'desc', 10, :'CENTRO')) #> '{data,rows}') x
           where x ->> 'menu_item_id' = :'PASTOR'),
          (select round(sum(v.net / 1.08) - sum(v.units * c.cost))
           from app.v_item_sales_daily v join public.dish_cost_snapshot c
             on c.menu_item_id = v.menu_item_id and c.location_id = v.location_id and c.date = v.business_date
           where v.location_id = :'CENTRO' and v.business_date = '2026-10-11' and v.menu_item_id = :'PASTOR'),
          'M2: get_top_dishes margins too');
rollback to savepoint border;

-- M3: a dish the engine stopped costing is flagged stale and never confirmed
savepoint stale;
update public.dish_cost_snapshot set confidence = 'confirmed';
delete from public.dish_cost_snapshot where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date > '2026-09-15';
select ok(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) -> 'flags' @> '[{"code": "stale_cost"}]',
          'M3: an old snapshot (newer ones exist for other dishes) is flagged stale_cost');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) #>> '{data,confidence}', 'estimated',
          'M3: and its confidence is estimated');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos de bistec', :'CENTRO')) -> 'flags', '[]',
          'M3: a current snapshot is not stale');
rollback to savepoint stale;


-- M5: the confidence flag qualifies the breaches only
savepoint breach_conf;
update public.dish_cost_snapshot set confidence = 'confirmed';
update public.dish_cost_snapshot set confidence = 'estimated' where menu_item_id = :'PASTOR';
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #>> '{flags,0,code}', 'cost_confirmed',
          'M5: every breach confirmed: cost_confirmed, whatever the dishes that do not breach');
rollback to savepoint breach_conf;

-- M6: the alert window ends today; a window that starts after today is invalid
savepoint future_price;
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
select :'TENANT', i.id, 0.300, '2026-10-25', 'cfdi' from public.ingredient i where i.name = 'Carne al pastor (adobada)';
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '{"from":"2026-10-09","to":"2026-11-01"}', :'CENTRO')) #> '{meta,period_resolved}',
          '{"from": "2026-10-09", "to": "2026-10-12"}', 'M6: a range that ends in the future still ends today');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '{"from":"2026-09-12","to":"2026-11-01"}', :'CENTRO')) #> '{data,price_moves,0,new_unit_price,raw}',
          '0.195', 'M6: a price that starts after today is not a move yet');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '{"from":"2026-10-13","to":"2026-10-20"}', :'CENTRO')) #>> '{error,code}', 'invalid_args',
          'M6: a window that starts after today is invalid');
rollback to savepoint future_price;

-- L2: a recipe nested too deep after its snapshot still gets an answer, without cost drivers
savepoint deep;
set local session_replication_role = replica;
insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base)
values (:'TENANT', '46faac9d-fc08-5876-af8d-6b3b958b52b3', '46faac9d-fc08-5876-af8d-6b3b958b52b3', 1);
set local session_replication_role = origin;
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L, %L)', 'tacos al pastor', :'CENTRO')) #>> '{data,match}', 'resolved',
          'L2: the margin is still answered');
rollback to savepoint deep;

-- L6: a ticket day without payment records is not payment detail
savepoint no_payments;
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status, applied_at)
select 'eeeeeeee-0000-7000-8000-000000000401', s.tenant_id, s.id, s.location_id, 'sr.erp_push@v1', 'mr24-nopay', 'applied', '2026-10-12T09:00:00-06:00'
from public.source s where s.location_id = :'CENTRO' limit 1;
insert into public.sale_ticket (id, tenant_id, location_id, source_id, external_id, batch_id, business_date, opened_at, closed_at, channel, subtotal, discount, tax, total, status)
select 'eeeeeeee-0000-7000-8000-0000000004a1', b.tenant_id, b.location_id, b.source_id, 'N-1', b.id, '2026-10-11', '2026-10-11T13:00:00-06:00',
       '2026-10-11T13:30:00-06:00', 'dine_in', 11207, 0, 1793, 13000, 'paid'
from public.import_batch b where b.id = 'eeeeeeee-0000-7000-8000-000000000401';
select ok(pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"last_week"', 'payment_method', :'CENTRO')) -> 'flags'
            @> '[{"code": "partial_data"}]', 'L6: the ticket day has no payments: the payment breakdown is partial');
rollback to savepoint no_payments;

-- L8: a price move counts only for ingredients a live dish uses
savepoint retired;
update public.menu_item set is_active = false;
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}', '[]',
          'L8: no active dish uses the ingredients: no price moves');
rollback to savepoint retired;
select isnt(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}', '[]',
          'L8: the live dishes'' ingredients still move');

-- PR #77 review 1: with no location asked, the freshest location wins over a stale one
savepoint fresh_location;
update public.menu_item_price set price_gross = 6500 where menu_item_id = :'PASTOR' and location_id = :'POLANCO';
update public.dish_cost_snapshot set cost = 1840, price_net = 5603, margin = 3763 where menu_item_id = :'PASTOR';
delete from public.dish_cost_snapshot where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date > '2026-10-05';
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', 'tacos al pastor')) #>> '{data,location_id}', :'POLANCO',
          'R1: same numbers at both locations, Centro stale since 10-05: Polanco, the fresh one');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', 'tacos al pastor')) -> 'flags', '[]', 'R1: and not stale');
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', 'tacos al pastor')) #> '{meta,period_resolved}',
          '{"from": "2026-10-12", "to": "2026-10-12"}', 'R1: as of today''s snapshot');
update public.dish_cost_snapshot set confidence = 'confirmed';
select is(pg_temp.rpc(:OWNER, format('api.get_dish_margin(%L)', 'tacos al pastor')) #>> '{data,confidence}', 'confirmed',
          'R1: staleness alone does not make the locations disagree: Polanco, confirmed');
rollback to savepoint fresh_location;

-- PR #77 review 2: the day's tax rate is the price row in effect that day (newest start, then newest row)
savepoint rate_rows;
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from, effective_to)
values (:'TENANT', :'CENTRO', :'PASTOR', 6500, 0.08, '2026-10-11', '2026-10-11'),
       (:'TENANT', :'CENTRO', :'PASTOR', 6500, 0.00, '2026-10-01', null);
select is((select jsonb_object_agg(r.day, round(r.net_ex_iva / r.net, 6)) from app.item_cost_rows(array[:'CENTRO']::uuid[], '2026-10-10', '2026-10-11') r
           where r.menu_item_id = :'PASTOR'),
          '{"2026-10-10": 1.000000, "2026-10-11": 0.925926}', 'R2: each day nets IVA at the rate of the price row in effect');
rollback to savepoint rate_rows;

-- PR #77 review 3: get_top_dishes margins and compare_periods food cost carry their confidence
savepoint top_confirmed;
update public.dish_cost_snapshot set confidence = 'confirmed';
select ok(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, location_id => %L)', '"yesterday"', 'margin', :'CENTRO')) -> 'flags'
            @> '[{"code": "cost_confirmed"}]', 'R3: all confirmed: top dishes by margin say cost_confirmed');
select ok(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L, %L)', 'food_cost_pct', '"yesterday"', '"last_week"', :'CENTRO')) -> 'flags'
            @> '[{"code": "cost_confirmed"}]', 'R3: and compare_periods food cost cost_confirmed');
update public.dish_cost_snapshot set confidence = 'estimated' where date = '2026-10-05';
select ok(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L, %L)', 'food_cost_pct', '"yesterday"', '"last_week"', :'CENTRO')) -> 'flags'
            @> '[{"code": "cost_estimated"}]', 'R3: one estimated snapshot in either period: cost_estimated');
rollback to savepoint top_confirmed;

-- PR #77 review 4: two staff with the same first name are told apart by a last-name initial
savepoint same_first_name;
insert into public.staff (id, tenant_id, location_id, display_name)
values ('eeeeeeee-0000-7000-8000-000000000501', :'TENANT', :'CENTRO', 'Luis Martínez'),
       ('eeeeeeee-0000-7000-8000-000000000502', :'TENANT', :'CENTRO', 'Luis  Romero');
insert into public.import_batch (id, tenant_id, source_id, location_id, parser, slice_key, status, applied_at)
select 'eeeeeeee-0000-7000-8000-000000000601', s.tenant_id, s.id, s.location_id, 'sr.erp_push@v1', 'mr24-luis', 'applied', '2026-10-12T09:00:00-06:00'
from public.source s where s.location_id = :'CENTRO' limit 1;
insert into public.sale_ticket (id, tenant_id, location_id, source_id, external_id, batch_id, business_date, opened_at, closed_at, channel, staff_id, subtotal, discount, tax, total, status)
select x.id::uuid, b.tenant_id, b.location_id, b.source_id, x.ext, b.id, '2026-10-12', '2026-10-12T13:00:00-06:00', '2026-10-12T13:30:00-06:00', 'dine_in',
       x.staff::uuid, round(x.total / 1.16), x.disc, x.total - round(x.total / 1.16), x.total, x.status::app.ticket_status
from public.import_batch b,
     (values ('eeeeeeee-0000-7000-8000-0000000006a1', 'L-1', 'eeeeeeee-0000-7000-8000-000000000501', 13000, 500, 'paid'),
             ('eeeeeeee-0000-7000-8000-0000000006a2', 'L-2', 'eeeeeeee-0000-7000-8000-000000000502', 6000, 300, 'paid'),
             ('eeeeeeee-0000-7000-8000-0000000006a3', 'L-3', 'eeeeeeee-0000-7000-8000-000000000501', 2000, 0, 'cancelled'),
             ('eeeeeeee-0000-7000-8000-0000000006a4', 'L-4', 'eeeeeeee-0000-7000-8000-000000000502', 1500, 0, 'cancelled')) x(id, ext, staff, total, disc, status)
where b.id = 'eeeeeeee-0000-7000-8000-000000000601';
insert into public.sale_ticket (id, tenant_id, location_id, source_id, external_id, batch_id, business_date, opened_at, closed_at, channel, staff_id, subtotal, discount, tax, total, status)
select 'eeeeeeee-0000-7000-8000-0000000006a5', b.tenant_id, b.location_id, b.source_id, 'L-5', b.id, '2026-10-12', '2026-10-12T14:00:00-06:00', '2026-10-12T14:30:00-06:00', 'dine_in',
       (select st.id from public.staff st where st.display_name = 'Pepe' and st.location_id = :'CENTRO'), 3448, 0, 552, 4000, 'paid'
from public.import_batch b where b.id = 'eeeeeeee-0000-7000-8000-000000000601';
select is((select jsonb_agg(x ->> 'key') from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_sales_breakdown(%L, %L, %L)', '"today"', 'staff', :'CENTRO')) #> '{data,rows}') x),
          '["Luis M.", "Luis R.", "Pepe"]', 'R4: sales by staff: one row per waiter, the two Luis told apart, Pepe by first name');
select is((select jsonb_agg(x ->> 'name') from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '"today"', :'CENTRO')) #> '{data,by_staff}') x),
          '["Luis M.", "Luis R."]', 'R4: cancellations by staff too');
select is((select jsonb_agg(x ->> 'name') from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, %L, %L)', '"today"', 'discounts', :'CENTRO')) #> '{data,by_staff}') x),
          '["Luis M.", "Luis R."]', 'R4: and discounts by staff');
select ok(pg_temp.rpc(:OWNER, format('api.get_cancellations(%L, location_id => %L)', '"today"', :'CENTRO'))::text !~* 'mart|romero',
          'R4: never a full last name');
rollback to savepoint same_first_name;

-- PR #77 review 5: two staff with the same first name and last initial get a number, never more of the name
savepoint same_initial;
insert into public.staff (id, tenant_id, location_id, display_name)
values ('eeeeeeee-0000-7000-8000-000000000511', :'TENANT', :'CENTRO', 'Luis Martínez'),
       ('eeeeeeee-0000-7000-8000-000000000512', :'TENANT', :'CENTRO', 'Luis Méndez'),
       ('eeeeeeee-0000-7000-8000-000000000513', :'TENANT', :'CENTRO', 'Luis Romero');
select is(pg_temp.rpc(:OWNER, $$(select jsonb_agg(n.name order by n.staff_id) from app.staff_names(array[
             'eeeeeeee-0000-7000-8000-000000000512', 'eeeeeeee-0000-7000-8000-000000000511',
             'eeeeeeee-0000-7000-8000-000000000513', null]::uuid[]) n)$$),
          '["Luis M.", "Luis M. (2)", "Luis R.", "Sin asignar"]', 'R5: the shared "Luis M." gets a number by staff id; Luis R. and Sin asignar keep theirs');
select ok(pg_temp.rpc(:OWNER, $$(select jsonb_agg(n.name) from app.staff_names(array[
             'eeeeeeee-0000-7000-8000-000000000511', 'eeeeeeee-0000-7000-8000-000000000512']::uuid[]) n)$$)::text !~* 'mart|m[eé]nd',
          'R5: never more of the last name');
rollback to savepoint same_initial;

-- MR-98 (PR-4): a location with no open day in the period gets a note, not "Sin datos para"
savepoint closed_location;
update public.location set closed_weekdays = '{6,7}' where id = :'POLANCO';
delete from public.daily_sales_agg where location_id = :'POLANCO' and business_date in ('2026-10-10', '2026-10-11');
delete from public.item_sales_agg where location_id = :'POLANCO' and period_from <= '2026-10-11' and period_to >= '2026-10-10';
delete from public.sale_line where ticket_id in
  (select id from public.sale_ticket where location_id = :'POLANCO' and business_date in ('2026-10-10', '2026-10-11'));
delete from public.sale_ticket where location_id = :'POLANCO' and business_date in ('2026-10-10', '2026-10-11');
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L)', 'net_sales', '"yesterday"')) -> 'flags',
          '[{"code": "closed_locations", "message": "Polanco no abre ese día."}]',
          'PR-4: yesterday, Polanco''s closed Sunday: the note, not "Sin datos para: Polanco"');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L)', 'net_sales', '"yesterday"')) #> '{data,rows}'), 1,
          'PR-4: Centro is still ranked');
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L)', 'net_sales', '{"from": "2026-10-10", "to": "2026-10-11"}')) -> 'flags',
          '[{"code": "closed_locations", "message": "Polanco no abre esos días."}]', 'PR-4: "esos días" for a longer period');
update public.location set closed_weekdays = '{}' where id = :'POLANCO';
select is(pg_temp.rpc(:OWNER, format('api.compare_locations(%L, %L)', 'net_sales', '"yesterday"')) #>> '{flags,0,message}',
          'Sin datos para: Polanco.', 'PR-4: the same gap on a day Polanco opens is still "Sin datos para"');
rollback to savepoint closed_location;

-- (outside any savepoint, so pgTAP's count keeps the savepoint tests above)
select ok(pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, location_id => %L)', '"yesterday"', 'margin_pct', :'CENTRO')) -> 'flags'
            @> '[{"code": "cost_estimated"}]', 'R3: top dishes by margin say cost_estimated');
select ok(not (pg_temp.rpc(:OWNER, format('api.get_top_dishes(%L, %L, location_id => %L)', '"yesterday"', 'units', :'CENTRO')) -> 'flags'
            @> '[{"code": "cost_estimated"}]'), 'R3: units are not a cost figure: no confidence flag');
select ok(pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L, %L)', 'food_cost_pct', '"yesterday"', '"last_week"', :'CENTRO')) -> 'flags'
            @> '[{"code": "cost_estimated"}]', 'R3: compare_periods food cost says cost_estimated');
select ok(not (pg_temp.rpc(:OWNER, format('api.compare_periods(%L, %L, %L, %L)', 'net_sales', '"yesterday"', '"last_week"', :'CENTRO')) -> 'flags'
            @> '[{"code": "cost_estimated"}]'), 'R3: net sales carry no confidence flag');

select * from finish();
rollback;
