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

savepoint dismissed;
update public.price_suggestion set status = 'dismissed' where menu_item_id = :'TORTA' and location_id = :'CENTRO';
select is(pg_temp.write(:'TENANT', '2026-10-12'), 0, 'a dismissed row is never rewritten');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,suggestions}'),
          2, 'nor shown');
rollback to savepoint dismissed;

savepoint repriced;
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, effective_from)
values (:'TENANT', :'CENTRO', :'TORTA', 9000, '2026-10-12');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,suggestions}'),
          2, 'a suggestion whose current price is no longer the menu price is not shown');
rollback to savepoint repriced;

savepoint older;
-- an older day's row stays, but only the latest per dish is read
select ok(pg_temp.write(:'TENANT', '2026-10-11') > 0, 'the day before has its own rows');
select is((select count(*) from public.price_suggestion where location_id = :'CENTRO' and as_of = '2026-10-11'), 3::bigint,
          'three at Centro');
select is(jsonb_array_length(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,suggestions}'),
          3, 'one per dish');
rollback to savepoint older;

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

savepoint stale;
-- a dish the engine stopped costing a week ago gets nothing
delete from public.dish_cost_snapshot where date > '2026-10-05';
select is(pg_temp.write(:'TENANT', '2026-10-12'), 0, 'no fresh snapshot, no suggestion');
rollback to savepoint stale;

-- shape --------------------------------------------------------------------------------------
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, rule, value, threshold,
                          current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', 'margin_breach', 40, 35, 8000, 9000, 8000, 38, 'estimated', 'raise_capped')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'a raise must be above the current price');
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, rule, value, threshold,
                          current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', 'margin_breach', 40, 35, 8000, 9000, 8500, null, 'estimated', 'review_portion_cost')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'a review carries no price');
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, rule, value, threshold,
                          current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', 'margin_breach', 40, 35, 8000, 9000, 9500, 30, 'estimated', 'raise_capped')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'a capped raise stays under the target price');
select throws_ok(format($$insert into public.price_suggestion (tenant_id, location_id, menu_item_id, as_of, rule, value, threshold,
                          current_price, target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
                          values (%L, %L, %L, '2026-10-12', 'margin_breach', 40, 35, 8000, 9000, null, null, 'missing', 'review_portion_cost')$$,
                        :'TENANT', :'CENTRO', :'TORTA'), '23514', null, 'confidence is confirmed or estimated');

select * from finish();
rollback;
