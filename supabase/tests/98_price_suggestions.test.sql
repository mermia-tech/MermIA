-- MR-33 (part b): menu price suggestions. The formula against doc 12's sample messages, then the
-- writer on the El Güero seed (fixtures/README.md), evaluated as service_role on 2026-10-12.
begin;
select * from no_plan();

\set TENANT '03299e41-28bd-5779-bcc6-0e5e76580fad'
\set CENTRO '705e8e51-376b-5785-adbb-405eff4e2a22'
\set POLANCO 'fdda5e3b-6bcd-5c48-a6de-f524be37463e'
\set TORTA '6a076c57-be40-5ece-b48f-4ab124f4e65c'
\set ALAMBRE '81404715-16f4-518e-b9e7-07df075161eb'
\set VOLCAN '0ff2f280-6ded-5c20-930d-3990303ecdc0'
\set QUESADILLA '7724df82-1a06-5a9b-8bb9-6f56aeba7e37'
\set QUESO '5268568b-3d45-535f-9197-4b2f1873700e'
\set COCA '6ad0cd19-1e20-5d83-89d9-f35cb46afd05'

create function pg_temp.evaluate(tenant uuid, f date, t date) returns int
language plpgsql as $$
declare n int;
begin
  execute 'set local role service_role';
  select coalesce(sum(app.evaluate_cost_alerts(tenant, d::date, '2026-10-12')), 0) into n
  from generate_series(f, t, interval '1 day') d;
  reset role;
  return n;
end $$;

create function pg_temp.write(tenant uuid, on_date date) returns int
language plpgsql as $$
declare n int;
begin
  execute 'set local role service_role';
  n := app.write_price_suggestions(tenant, on_date);
  reset role;
  return n;
end $$;

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

-- privileges -------------------------------------------------------------------------------
select ok(has_function_privilege('service_role', 'app.write_price_suggestions(uuid, date)', 'execute'), 'the backend writes suggestions');
select ok(not has_function_privilege('authenticated', 'app.write_price_suggestions(uuid, date)', 'execute'), 'clients cannot');
select ok(not has_function_privilege('authenticated', 'app.suggest_menu_price(bigint, bigint, numeric, numeric)', 'execute'),
          'nor run the formula');
select ok(not has_table_privilege('authenticated', 'public.price_suggestion', 'insert,update,delete'), 'clients read suggestions only');
select throws_ok($$select app.write_price_suggestions(null, '2026-10-12')$$, '22023', null, 'a tenant is required');

-- the formula: doc 12 ------------------------------------------------------------------------
select results_eq(
  $$select f.* from (values (2980, 8900), (2790, 8500), (2460, 7900)) d(cost, price)
    cross join lateral app.suggest_menu_price(d.cost, d.price, 0.16, 32.0) f$$,
  $$values (10803::bigint, 9500::bigint, 36.3858::numeric), (10114, 9000, 35.9582), (8918, 8500, 33.5699)$$,
  'doc 12: Costra $89 -> $95 (36.4 %), Bistec $85 -> $90 (36.0 %; $101 reaches 32 %), Gringa $79 -> $85 (33.6 %)');
select is((select round(100.0 * (f.suggested_price - d.price) / d.price, 1)
           from (values (2980, 8900), (2790, 8500), (2460, 7900)) d(cost, price)
           cross join lateral app.suggest_menu_price(d.cost, d.price, null, 32.0) f
           order by d.cost desc limit 1), 6.7, 'Costra +6.7 %; a null rate is 16 %');
select is(array(select round(100.0 * (f.suggested_price - d.price) / d.price, 1)
                from (values (2980, 8900), (2790, 8500), (2460, 7900)) d(cost, price)
                cross join lateral app.suggest_menu_price(d.cost, d.price, 0.16, 32.0) f order by d.cost desc),
          array[6.7, 5.9, 7.6], 'the changes doc 12 quotes');

-- the formula: price points, cap, never a decrease -------------------------------------------
select is((select row(f.*) from app.suggest_menu_price(6050, 20000, 0.16, 32.0) f),
          row(21932::bigint, 22000::bigint, 31.8992::numeric), 'within the cap: up to the next $5 point, reaching the target');
select is((select row(f.*) from app.suggest_menu_price(9500, 30000, 0.16, 32.0) f),
          row(34438::bigint, 33000::bigint, 33.3943::numeric), 'at or above $250: $10 points ($330 = the +10 % cap)');
select is((select f.suggested_price from app.suggest_menu_price(7000, 23000, 0.16, 32.0) f), 25000::bigint,
          'a cap of $253 rounds down to $250 (the $10 grid starts at $250)');
select is((select row(f.target_price, f.suggested_price, f.new_food_cost_pct) from app.suggest_menu_price(1400, 3000, 0.16, 32.0) f),
          row(5075::bigint, null::bigint, null::numeric), 'Coca-Cola $30: the cap ($33) rounds down to $30, so no price');
select is((select f.suggested_price from app.suggest_menu_price(1000, 6000, 0.16, 32.0) f), null::bigint,
          'never a decrease: a target below the current price gives no price');
select is((select row(f.target_price, f.suggested_price, f.new_food_cost_pct) from app.suggest_menu_price(2980, 8900, 0.08, 32.0) f),
          row(10058::bigint, 9500::bigint, 33.8790::numeric), 'IVA at the menu price''s own rate (8 %, border zone)');
select is((select count(*) from app.suggest_menu_price(0, 8900, 0.16, 32.0)), 0::bigint, 'no cost, no answer');
select is((select count(*) from app.suggest_menu_price(2980, 0, 0.16, 32.0)), 0::bigint, 'nor without a price');

-- resale (U2) --------------------------------------------------------------------------------
select ok(app.is_resale(:'COCA', '2026-10-12'), 'Coca-Cola is resale (one line, by the piece)');
select ok(not app.is_resale(:'QUESADILLA', '2026-10-12'), 'a quesadilla is not');

-- the seed -----------------------------------------------------------------------------------
select ok(app.compute_dish_costs(:'TENANT', '2026-08-17', '2026-10-12') > 0, 'dish cost snapshots computed by the engine');
create temp table before_counts as
select (select count(*) from public.pending_change) as pending, (select count(*) from public.menu_item_price) as prices;
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12'), 17, 'the evaluator still returns the alerts it added (17 breaches), not the suggestions');
select results_eq(
  $$select m.name, p.as_of, p.rule, p.value, p.threshold, p.current_price, p.target_price, p.suggested_price,
           p.new_food_cost_pct, p.confidence::text, p.rationale_code, p.status
    from public.price_suggestion p join public.menu_item m on m.id = p.menu_item_id
    where p.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22' order by p.value desc$$,
  $$values ('Torta de pastor'::text, '2026-10-12'::date, 'margin_breach'::text, 50.0072::numeric, 35.0::numeric, 8000::bigint,
            12503::bigint, null::bigint, null::numeric, 'estimated'::text, 'review_portion_cost'::text, 'open'::text),
           ('Alambre de res', '2026-10-12', 'margin_breach', 49.0880, 35.0, 14500, 22243, null, null, 'estimated', 'review_portion_cost', 'open'),
           ('Volcán de pastor', '2026-10-12', 'margin_breach', 37.6901, 35.0, 4500, 5300, null, null, 'estimated', 'review_portion_cost', 'open')$$,
  'Centro: the puzzles (torta, alambre) and the dog (volcán) get "revisa porción/costo", no price');
select is((select count(*) from public.price_suggestion p
           where p.menu_item_id in (select id from public.menu_item where name in ('Coca-Cola', 'Cerveza Corona', 'Agua mineral'))),
          0::bigint, 'U2: resale breaches (Coca-Cola, Corona, agua mineral) get no suggestion');
select is((select count(*) from public.alert a where a.rule = 'margin_breach' and a.location_id = :'CENTRO'
           and a.menu_item_id in (select id from public.menu_item where name in ('Coca-Cola', 'Cerveza Corona', 'Agua mineral'))),
          3::bigint, 'though they keep their breach alerts');
select is((select count(*) from public.price_suggestion p
           where p.location_id = :'CENTRO'
             and p.menu_item_id in (select id from public.menu_item where name in ('Gringa de pastor', 'Tacos de bistec (orden de 3)', 'Tacos de suadero (orden de 3)'))),
          0::bigint, 'U4: stars (gringa, bistec, suadero) are not raised');
select is((select count(*) from public.price_suggestion where tenant_id <> :'TENANT'), 0::bigint, 'nothing for another tenant');

select is(pg_temp.write(:'TENANT', '2026-10-12'), 0, 'a rerun writes nothing');
select is((select count(*) from public.price_suggestion where version > 1), 0::bigint, 'and touches no row');
select is((select row(b.pending, b.prices) from before_counts b),
          (select row(count(*), (select count(*) from public.menu_item_price)) from public.pending_change),
          'no pending change or menu price is written');

-- read through get_cost_alerts ---------------------------------------------------------------
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,suggestions,0}',
          format('{"menu_item_id": "%s", "location_id": "%s", "name": "Torta de pastor",
                   "current_price": {"raw": 8000, "text": "$80.00"}, "target_price": {"raw": 12503, "text": "$125.03"},
                   "suggested_price": null, "change": null, "new_food_cost": null,
                   "confidence": "estimated", "rationale_code": "review_portion_cost"}', :'TORTA', :'CENTRO')::jsonb,
          'a review row: target price, no suggested price');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,suggestions}'),
          3, 'Centro''s three');
select is((select count(*)::int from jsonb_array_elements(pg_temp.rpc(:POLANCO_MGR, 'api.get_cost_alerts()') #> '{data,suggestions}') x
           where x ->> 'location_id' <> :'POLANCO'), 0, 'a Polanco manager sees Polanco''s only (RLS)');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO'), '2026-10-20') #> '{data,suggestions}'),
          0, 'a row evaluated before the window is not shown');

savepoint repriced;
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, effective_from)
values (:'TENANT', :'CENTRO', :'TORTA', 9000, '2026-10-12');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,suggestions}'),
          2, 'a suggestion whose current price is no longer the menu price is not shown');
rollback to savepoint repriced;

-- one row per breach episode ----------------------------------------------------------------
savepoint episode;
select ok(app.compute_dish_costs(:'TENANT', '2026-10-13', '2026-10-20') > 0, 'costs through 10-20');
select ok(pg_temp.write(:'TENANT', '2026-10-13') > 0, 'the next day refreshes the open rows');
select is((select count(*) from public.price_suggestion where location_id = :'CENTRO'), 3::bigint,
          'one row per episode, not per day');
select is((select array_agg(distinct as_of) from public.price_suggestion where location_id = :'CENTRO'),
          array['2026-10-13'::date], 'refreshed in place: as_of is the last day evaluated');
select is(pg_temp.write(:'TENANT', '2026-10-13'), 0, 'a rerun of that day writes nothing');
select is(pg_temp.write(:'TENANT', '2026-10-11'), 0, 'an older day writes nothing back');
select is((select array_agg(distinct as_of) from public.price_suggestion where location_id = :'CENTRO'),
          array['2026-10-13'::date], 'the rows keep the newer day');
rollback to savepoint episode;

savepoint dismissed;
-- dismissed (torta) and pending (alambre) on 10-12 stick for the episode
select ok(app.compute_dish_costs(:'TENANT', '2026-10-13', '2026-10-20') > 0, 'costs through 10-20');
update public.price_suggestion set status = 'dismissed' where menu_item_id = :'TORTA' and location_id = :'CENTRO';
update public.price_suggestion set status = 'pending' where menu_item_id = :'ALAMBRE' and location_id = :'CENTRO';
select is(pg_temp.write(:'TENANT', '2026-10-12'), 0, 'an acted-on row is never rewritten');
select ok(pg_temp.write(:'TENANT', '2026-10-13') >= 0, 'the 10-13 run');
select is((select array_agg(m.name || ': ' || p.status order by m.name)
           from public.price_suggestion p join public.menu_item m on m.id = p.menu_item_id
           where p.location_id = :'CENTRO'),
          array['Alambre de res: pending', 'Torta de pastor: dismissed', 'Volcán de pastor: open'],
          'no new open row for the dismissed torta nor the pending alambre');
select is(array(select x ->> 'name' from jsonb_array_elements(
                  pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO'), '2026-10-13')
                  #> '{data,suggestions}') x),
          array['Alambre de res', 'Volcán de pastor'], 'get_cost_alerts on 10-13: no torta; the pending alambre still shows');
-- an open copy of a dismissed row (same episode, price and suggestion) is never shown
insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value, threshold,
                                     current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
select tenant_id, location_id, menu_item_id, '2026-10-13', episode_start, rule, value, threshold, current_price, target_price,
       suggested_price, new_food_cost_pct, confidence, rationale_code
from public.price_suggestion where menu_item_id = :'TORTA' and location_id = :'CENTRO';
select is((select count(*)::int from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO'), '2026-10-13') #> '{data,suggestions}') x
           where x ->> 'name' = 'Torta de pastor'), 0, 'the read path holds back an open copy of a dismissed row');
delete from public.price_suggestion where menu_item_id = :'TORTA' and location_id = :'CENTRO' and status = 'open';
-- the torta goes to $90 on 10-13: after a week at $90 (pacing) a new open row
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, effective_from)
values (:'TENANT', :'CENTRO', :'TORTA', 9000, '2026-10-13');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-13', '2026-10-20') > 0, 'recomputed at $90');
select is((select count(*)::int from generate_series('2026-10-14'::date, '2026-10-19', '1 day') d
           where pg_temp.write(:'TENANT', d::date) >= 0), 6, 'runs 10-14 .. 10-19');
select is((select count(*) from public.price_suggestion where menu_item_id = :'TORTA' and location_id = :'CENTRO'), 1::bigint,
          'no new row before a week at $90');
select ok(pg_temp.write(:'TENANT', '2026-10-20') > 0, 'the 10-20 run');
select is((select row(p.as_of, p.current_price, p.rationale_code) from public.price_suggestion p
           where p.menu_item_id = :'TORTA' and p.location_id = :'CENTRO' and p.status = 'open'),
          row('2026-10-20'::date, 9000::bigint, 'review_portion_cost'::text), 'the price change re-opens it');
select ok(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO'), '2026-10-20') #> '{data,suggestions}' @>
          format('[{"menu_item_id": "%s", "current_price": {"raw": 9000, "text": "$90.00"}}]', :'TORTA')::jsonb,
          'and get_cost_alerts shows it at $90');
rollback to savepoint dismissed;

savepoint new_episode;
-- the dismissed torta comes back within the line on 10-13 and breaches again from 10-14: a new episode, a new row
select ok(app.compute_dish_costs(:'TENANT', '2026-10-13', '2026-10-20') > 0, 'costs through 10-20');
update public.price_suggestion set status = 'dismissed' where menu_item_id = :'TORTA' and location_id = :'CENTRO';
update public.dish_cost_snapshot set cost = price_net * 30 / 100
where menu_item_id = :'TORTA' and location_id = :'CENTRO' and date = '2026-10-13';
select ok(pg_temp.write(:'TENANT', '2026-10-14') > 0, 'the 10-14 run');
select is((select array_agg(p.status || ' from ' || p.episode_start order by p.as_of) from public.price_suggestion p
           where p.menu_item_id = :'TORTA' and p.location_id = :'CENTRO'),
          array['dismissed from ' || (select episode_start from public.price_suggestion
                                      where menu_item_id = :'TORTA' and location_id = :'CENTRO' and status = 'dismissed'),
                'open from 2026-10-14'],
          'the dismissal held for its episode only');
rollback to savepoint new_episode;

-- an open row the writer stopped refreshing is removed, and never shown ----------------------
savepoint star_flip;
-- volcán (Centro's dog) turns into a star by 10-13: the 10-13 run does not refresh its 10-12 row, so it goes
select ok(app.compute_dish_costs(:'TENANT', '2026-10-13', '2026-10-20') > 0, 'costs through 10-20');
alter function app.menu_quadrants(uuid[], date, date) rename to menu_quadrants_seed;
create function app.menu_quadrants(locs uuid[], f date, t date) returns table (menu_item_id uuid, units numeric, quadrant text)
language sql stable set search_path = '' as $$
  select q.menu_item_id, q.units, case when q.menu_item_id = '0ff2f280-6ded-5c20-930d-3990303ecdc0' then 'star' else q.quadrant end
  from app.menu_quadrants_seed(locs, f, t) q $$;
grant execute on function app.menu_quadrants(uuid[], date, date) to service_role, authenticated;
select ok(pg_temp.write(:'TENANT', '2026-10-13') > 0, 'the 10-13 run');
select is((select array_agg(m.name || ': ' || p.as_of order by m.name)
           from public.price_suggestion p join public.menu_item m on m.id = p.menu_item_id where p.location_id = :'CENTRO'),
          array['Alambre de res: 2026-10-13', 'Torta de pastor: 2026-10-13'], 'a dish that became a star loses its open row');
select is(array(select x ->> 'name' from jsonb_array_elements(
                  pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO'), '2026-10-13') #> '{data,suggestions}') x),
          array['Torta de pastor', 'Alambre de res'], 'get_cost_alerts last_30d on 10-13: no volcán');
rollback to savepoint star_flip;

savepoint stopped_costing;
-- the engine stops costing the alambre and the (dismissed) torta after 10-12: on 10-20 the open alambre row goes,
-- the dismissed torta stays; the volcán is refreshed
select ok(app.compute_dish_costs(:'TENANT', '2026-10-13', '2026-10-20') > 0, 'costs through 10-20');
delete from public.dish_cost_snapshot
where location_id = :'CENTRO' and menu_item_id in (:'ALAMBRE', :'TORTA') and date > '2026-10-12';
update public.price_suggestion set status = 'dismissed' where menu_item_id = :'TORTA' and location_id = :'CENTRO';
select ok(pg_temp.write(:'TENANT', '2026-10-20') > 0, 'the 10-20 run');
select is((select array_agg(m.name || ': ' || p.status || ' ' || p.as_of order by m.name)
           from public.price_suggestion p join public.menu_item m on m.id = p.menu_item_id where p.location_id = :'CENTRO'),
          array['Torta de pastor: dismissed 2026-10-12', 'Volcán de pastor: open 2026-10-20'],
          'a dish no longer costed loses its open row; an acted-on row is never removed');
select is(array(select x ->> 'name' from jsonb_array_elements(
                  pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO'), '2026-10-20') #> '{data,suggestions}') x),
          array['Volcán de pastor'], 'get_cost_alerts last_30d on 10-20: the volcán only');
select is(pg_temp.write(:'TENANT', '2026-10-20'), 0, 'a rerun writes nothing');
select is(pg_temp.write(:'TENANT', '2026-10-19'), 0, 'nor does an older day, which removes nothing newer');
select is((select count(*) from public.price_suggestion where location_id = :'CENTRO'), 2::bigint, 'the two rows stay');
rollback to savepoint stopped_costing;

savepoint not_evaluated;
-- the evaluator has not run since 10-12: a row older than the dish's latest snapshot is not shown
select ok(app.compute_dish_costs(:'TENANT', '2026-10-13', '2026-10-20') > 0, 'costs through 10-20, no run');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO'), '2026-10-15')
                             #> '{data,suggestions}'), 0, 'on 10-15: the 10-12 rows are older than the 10-15 snapshots');
update public.price_suggestion set status = 'pending' where menu_item_id = :'ALAMBRE' and location_id = :'CENTRO';
select is(array(select x ->> 'name' from jsonb_array_elements(
                  pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO'), '2026-10-15') #> '{data,suggestions}') x),
          array['Alambre de res'], 'a pending row still shows');
rollback to savepoint not_evaluated;
-- nor without new snapshots: an open row is shown for a week after the day it was evaluated (the writer's freshness)
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO'), '2026-10-18')
                             #> '{data,suggestions}'), 3, 'on 10-18, six days on, the 10-12 rows still show');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO'), '2026-10-19')
                             #> '{data,suggestions}'), 0, 'on 10-19 they are a week old: not shown');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO'), '2026-11-05')
                             #> '{data,suggestions}'), 0, 'nor on 11-05');

-- one bad price row does not roll back the tenant's day (S1) -----------------------------------
savepoint bad_rate;
-- a torta price row at Centro with a -1.5 tax rate from 10-12 (same $80): its target price would be negative
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from)
values (:'TENANT', :'CENTRO', :'TORTA', 8000, -1.5, '2026-10-12');
delete from public.price_suggestion;
select lives_ok($$select pg_temp.write('03299e41-28bd-5779-bcc6-0e5e76580fad', '2026-10-12')$$, 'the run does not fail');
select is((select array_agg(m.name order by m.name)
           from public.price_suggestion p join public.menu_item m on m.id = p.menu_item_id where p.location_id = :'CENTRO'),
          array['Alambre de res', 'Volcán de pastor'], 'the torta is skipped; the others are written');
update public.menu_item_price set tax_rate = 1 where menu_item_id = :'TORTA' and location_id = :'CENTRO' and tax_rate = -1.5;
select lives_ok($$select pg_temp.write('03299e41-28bd-5779-bcc6-0e5e76580fad', '2026-10-12')$$, 'nor with a 100 % rate');
select is((select count(*) from public.price_suggestion where menu_item_id = :'TORTA' and location_id = :'CENTRO'), 0::bigint,
          'which is skipped too');
rollback to savepoint bad_rate;

-- the sticky rule ----------------------------------------------------------------------------
select ok(app.suggestion_reopens(6000, 6500, 6500, 7000), 'a new current price re-opens');
select ok(app.suggestion_reopens(20000, 21000, 20000, 22000), 'so does a higher price point');
select ok(not app.suggestion_reopens(20000, 22000, 20000, 21000), 'a lower one does not');
select ok(not app.suggestion_reopens(8000, null, 8000, null), 'nor the same review');
select ok(app.suggestion_reopens(8000, null, 8000, 8500), 'a price where a review stood re-opens');

-- the lists are capped -------------------------------------------------------------------------
select is((pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data}') - 'breaches'
            - 'price_moves' - 'suggestions',
          '{"price_moves_total": 2, "breaches_total": 9, "suggestions_total": 3}'::jsonb, 'the totals under the cap');
savepoint capped;
create or replace function app.cost_alerts_top_n() returns int language sql immutable set search_path = '' as $$ select 1 $$;
select is(array(select x ->> 'name' from jsonb_array_elements(
                  pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,suggestions}') x),
          array['Torta de pastor'], 'a cap of 1: the highest food cost');
select is(array(select x ->> 'ingredient' from jsonb_array_elements(
                  pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}') x),
          array['Aguacate Hass'], 'and the largest price move');
select is(array(select x ->> 'name' from jsonb_array_elements(
                  pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,breaches}') x),
          array['Coca-Cola'], 'and the highest food cost among the breaches');
select is((pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data}') - 'breaches'
            - 'price_moves' - 'suggestions',
          '{"price_moves_total": 2, "breaches_total": 9, "suggestions_total": 3}'::jsonb, 'the totals still count them all');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #>> '{flags,0,code}', 'cost_estimated',
          'the confidence flag still covers every breach');
rollback to savepoint capped;

-- a plowhorse that breaches twice gets a price ------------------------------------------------
-- quesadilla at Centro (plowhorse, $45, 28.4 %) is priced $60 from 08-17 (a newer row that day), and queso Oaxaca goes from
-- $140 to $280/kg on 09-28: cost $19.41 on a net of $51.72, 37.5 %
savepoint plowhorse;
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, effective_from)
values (:'TENANT', :'CENTRO', :'QUESADILLA', 6000, '2026-08-17');
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'QUESO', 0.280, '2026-09-28', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-09-01', '2026-10-12') > 0, 'costs recomputed');
select is(pg_temp.write(:'TENANT', '2026-10-12') > 0, true, 'written');
select is((select row(p.value, p.current_price, p.target_price, p.suggested_price, p.new_food_cost_pct, p.rationale_code)
           from public.price_suggestion p where p.menu_item_id = :'QUESADILLA' and p.location_id = :'CENTRO'),
          row(37.5290::numeric, 6000::bigint, 7037::bigint, 6500::bigint, 34.6422::numeric, 'raise_capped'::text),
          'quesadilla $60 -> $65 (the +10 % cap), 34.6 %; $70.37 would reach 32 %');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,suggestions}' @>
          format('[{"menu_item_id": "%s", "current_price": {"raw": 6000, "text": "$60.00"}, "suggested_price": {"raw": 6500, "text": "$65.00"},
                    "change": {"raw": 8.3333, "text": "+8.3%%"}, "new_food_cost": {"raw": 34.6422, "text": "34.6%%"},
                    "target_price": {"raw": 7037, "text": "$70.37"}, "rationale_code": "raise_capped"}]', :'QUESADILLA')::jsonb,
          true, 'get_cost_alerts quotes it with the change and the new food cost');
rollback to savepoint plowhorse;

savepoint one_observation;
-- the same, with queso going up on 10-08: on 10-05 the quesadilla was still within target
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, effective_from)
values (:'TENANT', :'CENTRO', :'QUESADILLA', 6000, '2026-08-17');
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'QUESO', 0.280, '2026-10-08', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-09-01', '2026-10-12') > 0, 'costs recomputed');
select is(pg_temp.write(:'TENANT', '2026-10-12') >= 0, true, 'written');
select is((select count(*) from public.price_suggestion p where p.menu_item_id = :'QUESADILLA'), 0::bigint,
          'one breaching observation is not enough (03: two, a week apart)');
rollback to savepoint one_observation;

savepoint pacing;
-- quesadilla at Centro $60 from 08-17 and queso $400/kg from 09-28: $65 on 10-12, applied on 10-13; at $65 it
-- still breaches, but the next step waits for a week at $65
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, effective_from)
values (:'TENANT', :'CENTRO', :'QUESADILLA', 6000, '2026-08-17');
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'QUESO', 0.400, '2026-09-28', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-09-01', '2026-10-20') > 0, 'costs recomputed');
select ok(pg_temp.write(:'TENANT', '2026-10-12') > 0, 'written');
select is((select row(p.current_price, p.suggested_price, p.rationale_code) from public.price_suggestion p
           where p.menu_item_id = :'QUESADILLA' and p.location_id = :'CENTRO'),
          row(6000::bigint, 6500::bigint, 'raise_capped'::text), '$60 -> $65');
update public.price_suggestion set status = 'applied' where menu_item_id = :'QUESADILLA' and location_id = :'CENTRO';
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, effective_from)
values (:'TENANT', :'CENTRO', :'QUESADILLA', 6500, '2026-10-13');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-13', '2026-10-20') > 0, 'recomputed at $65');
select ok((select bool_and(s.food_cost_pct > 35) from public.dish_cost_snapshot s
           where s.menu_item_id = :'QUESADILLA' and s.location_id = :'CENTRO' and s.date between '2026-10-13' and '2026-10-20'),
          'at $65 it still breaches');
select is((select count(*)::int from generate_series('2026-10-13'::date, '2026-10-19', '1 day') d
           where pg_temp.write(:'TENANT', d::date) >= 0), 7, 'runs 10-13 .. 10-19');
select is((select count(*) from public.price_suggestion where menu_item_id = :'QUESADILLA' and location_id = :'CENTRO'),
          1::bigint, 'no new suggestion in the first week at $65');
select is((select count(*)::int from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO'), '2026-10-13') #> '{data,suggestions}') x
           where x ->> 'menu_item_id' = :'QUESADILLA'), 0, 'nor in get_cost_alerts on 10-13');
select ok(pg_temp.write(:'TENANT', '2026-10-20') > 0, 'the 10-20 run');
select is((select row(p.as_of, p.current_price, p.suggested_price) from public.price_suggestion p
           where p.menu_item_id = :'QUESADILLA' and p.location_id = :'CENTRO' and p.status = 'open'),
          row('2026-10-20'::date, 6500::bigint, 7000::bigint), 'after a week at $65, the next step: $70');
rollback to savepoint pacing;

savepoint capped_flat;
-- at $45 the +10 % cap ($49.50) rounds down to $45: a breaching plowhorse with no price gets no row
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'QUESO', 0.280, '2026-09-28', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-09-01', '2026-10-12') > 0, 'costs recomputed');
select ok((select s.food_cost_pct > 35 from public.dish_cost_snapshot s
           where s.menu_item_id = :'QUESADILLA' and s.location_id = :'CENTRO' and s.date = '2026-10-12'), 'the quesadilla breaches');
select is(pg_temp.write(:'TENANT', '2026-10-12') >= 0, true, 'written');
select is((select count(*) from public.price_suggestion p where p.menu_item_id = :'QUESADILLA' and p.location_id = :'CENTRO'), 0::bigint,
          'no suggestion when the cap lands on the current price');
rollback to savepoint capped_flat;

savepoint piece_dishes;
-- a single line by the piece is resale only as one piece at 100 % yield: torta becomes "5 tortillas" and volcán
-- "2 huevos" (Centro's puzzle and dog), both still dishes that get a suggestion
insert into public.ingredient (tenant_id, name, base_unit) values (:'TENANT', 'Tortilla de harina (pieza)', 'pza')
returning id as tortilla \gset
insert into public.ingredient (tenant_id, name, base_unit) values (:'TENANT', 'Huevo blanco (pieza)', 'pza')
returning id as huevo \gset
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'tortilla', 6.0, '2026-08-01', 'cfdi'), (:'TENANT', :'huevo', 8.0, '2026-08-01', 'cfdi');
insert into public.recipe (tenant_id, menu_item_id, recipe_version, status, yield_qty)
select :'TENANT', d.item, (select max(r.recipe_version) + 1 from public.recipe r where r.menu_item_id = d.item), 'confirmed', 1
from (values (:'TORTA'::uuid), (:'VOLCAN'::uuid)) d(item);
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base)
select :'TENANT', app.recipe_of_record(d.item, null, '2026-10-12'), d.ingredient, d.qty
from (values (:'TORTA'::uuid, :'tortilla'::uuid, 5), (:'VOLCAN'::uuid, :'huevo'::uuid, 2)) d(item, ingredient, qty);
select ok(not app.is_resale(:'TORTA', '2026-10-12'), '"5 tortillas" is not resale');
select ok(not app.is_resale(:'VOLCAN', '2026-10-12'), 'nor "2 huevos"');
select ok(app.compute_dish_costs(:'TENANT', '2026-09-01', '2026-10-12') > 0, 'costs recomputed');
delete from public.price_suggestion;
select ok(pg_temp.write(:'TENANT', '2026-10-12') > 0, 'written');
select is((select array_agg(m.name || ': ' || p.rationale_code order by m.name)
           from public.price_suggestion p join public.menu_item m on m.id = p.menu_item_id
           where p.location_id = :'CENTRO' and p.menu_item_id in (:'TORTA', :'VOLCAN')),
          array['Torta de pastor: review_portion_cost', 'Volcán de pastor: review_portion_cost'],
          'the single-line piece dishes ("5 tortillas", "2 huevos") get their suggestion');
select is((select count(*) from public.price_suggestion p
           where p.menu_item_id in (select id from public.menu_item where name in ('Coca-Cola', 'Cerveza Corona', 'Agua mineral'))),
          0::bigint, 'Coca-Cola, Corona and agua mineral still do not');
update public.recipe_line set yield_override_pct = 90 where recipe_id = app.recipe_of_record(:'COCA', null, '2026-10-12');
select ok(not app.is_resale(:'COCA', '2026-10-12'), 'one piece at 90 % yield is not resale either');
rollback to savepoint piece_dishes;

savepoint stale;
-- a dish the engine stopped costing a week ago gets nothing
delete from public.dish_cost_snapshot where date > '2026-10-05';
select is(pg_temp.write(:'TENANT', '2026-10-12'), 0, 'no fresh snapshot, no suggestion');
rollback to savepoint stale;

-- shape --------------------------------------------------------------------------------------
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value,
                          threshold, current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', '2026-10-01', 'margin_breach', 40, 35, 8000, 9000, 8000, 38, 'estimated', 'raise_capped')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'a raise must be above the current price');
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value,
                          threshold, current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', '2026-10-01', 'margin_breach', 40, 35, 8000, 9000, 8500, null, 'estimated', 'review_portion_cost')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'a review carries no price');
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value,
                          threshold, current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', '2026-10-01', 'margin_breach', 40, 35, 8000, 9000, 9500, 30, 'estimated', 'raise_capped')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'a capped raise stays under the target price');
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value,
                          threshold, current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', '2026-10-01', 'margin_breach', 40, 35, 8000, 8800, 8805, 33, 'estimated', 'raise_to_target')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'a raise is at most +10 % ($88.05 on $80)');
select lives_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value,
                         threshold, current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code, status)
                         values (%L, %L, %L, '2026-10-12', '2026-10-01', 'margin_breach', 40, 35, 8000, 8800, 8800, 33, 'estimated', 'raise_to_target', 'dismissed')$$,
                       :'TENANT', :'CENTRO', :'TORTA'), 'exactly +10 % ($88 on $80) is allowed');
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value,
                          threshold, current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', '2026-10-01', 'margin_breach', 40, 35, 8000, 9000, null, null, 'missing', 'review_portion_cost')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'confidence is confirmed or estimated');

select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value,
                          threshold, current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code, status)
                          values (%L, %L, %L, '2026-10-12', '2026-10-13', 'margin_breach', 40, 35, 8000, 9000, null, null, 'estimated',
                                  'review_portion_cost', 'dismissed')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'an episode starts on or before the day evaluated');
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value,
                          threshold, current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', '2026-10-01', 'margin_breach', 40, 35, 8000, 9000, null, null, 'estimated',
                                  'review_portion_cost')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23505', null, 'one open suggestion per dish and location');

select * from finish();
rollback;
