-- MR-33 (part a): cost alert rules against the El Güero seed (fixtures/README.md: carne al pastor
-- $170 -> $195/kg on 2026-09-21, aguacate $55 -> $89/kg on 2026-09-28). The backend's cost job
-- computes snapshots, then the evaluator runs as service_role once per day of 2026-09-12..10-12,
-- as a catch-up on 2026-10-12 (urgency is judged against that day, not the day evaluated).
begin;
select * from no_plan();

\set TENANT '03299e41-28bd-5779-bcc6-0e5e76580fad'
\set CENTRO '705e8e51-376b-5785-adbb-405eff4e2a22'
\set POLANCO 'fdda5e3b-6bcd-5c48-a6de-f524be37463e'
\set PASTOR 'f496f051-9f85-5f8a-a4b6-c1a814d37c73'
\set VOLCAN '0ff2f280-6ded-5c20-930d-3990303ecdc0'
\set MEAT '356dfff4-d912-542b-b8b0-8ae42068eb7e'
\set AVOCADO 'd01b40d2-85f2-58c9-93b5-e4ab08393eba'
\set BISTEC '087dcd5c-41dc-5c06-986e-6d558ac6e593'
\set OTHER 'aaaaaaaa-0000-7000-8000-000000000033'
\set SUGAR '31c9177d-9581-50c2-bed4-01574d0c7e74'
\set MASA '26099fe1-626d-504d-8ddb-90d5343f7d5b'

-- the backend's job over a range of days, as service_role, run on `today` (a catch-up when today
-- is after the range)
create function pg_temp.evaluate(tenant uuid, f date, t date, today date) returns int
language plpgsql as $$
declare n int;
begin
  execute 'set local role service_role';
  select coalesce(sum(app.evaluate_cost_alerts(tenant, d::date, today)), 0) into n
  from generate_series(f, t, interval '1 day') d;
  reset role;
  return n;
end $$;

-- the daily job as it happens: each day evaluated on that day
create function pg_temp.evaluate_daily(tenant uuid, f date, t date) returns int
language plpgsql as $$
declare n int;
begin
  execute 'set local role service_role';
  select coalesce(sum(app.evaluate_cost_alerts(tenant, d::date, d::date)), 0) into n
  from generate_series(f, t, interval '1 day') d;
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

create function pg_temp.alerts_seen(claims text) returns bigint
language plpgsql as $$
declare n bigint;
begin
  execute 'set local role authenticated';
  perform set_config('request.jwt.claims', claims, true);
  select count(*) into n from public.alert;
  reset role;
  return n;
end $$;

\set OWNER '''{"tenant_id":"03299e41-28bd-5779-bcc6-0e5e76580fad","location_ids":null}'''
\set POLANCO_MGR '''{"tenant_id":"03299e41-28bd-5779-bcc6-0e5e76580fad","location_ids":["fdda5e3b-6bcd-5c48-a6de-f524be37463e"]}'''
\set OTHER_OWNER '''{"tenant_id":"aaaaaaaa-0000-7000-8000-000000000033","location_ids":null}'''

-- a second tenant with one dish and its own price jump (+50 % on 2026-09-30)
insert into public.tenant (id, name) values (:'OTHER', 'Otra taquería');
insert into public.location (id, tenant_id, name, timezone) values ('aaaaaaaa-0000-7000-8000-0000000003a1', :'OTHER', 'Única', 'America/Mexico_City');
insert into public.ingredient (id, tenant_id, name, base_unit) values ('aaaaaaaa-0000-7000-8000-0000000003b1', :'OTHER', 'Carne', 'g');
insert into public.menu_item (id, tenant_id, name) values ('aaaaaaaa-0000-7000-8000-0000000003c1', :'OTHER', 'Taco');
insert into public.recipe (id, tenant_id, menu_item_id, recipe_version, status)
values ('aaaaaaaa-0000-7000-8000-0000000003d1', :'OTHER', 'aaaaaaaa-0000-7000-8000-0000000003c1', 1, 'confirmed');
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base)
values (:'OTHER', 'aaaaaaaa-0000-7000-8000-0000000003d1', 'aaaaaaaa-0000-7000-8000-0000000003b1', 100);
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, effective_to, source)
values (:'OTHER', 'aaaaaaaa-0000-7000-8000-0000000003b1', 0.100, '2026-08-01', '2026-09-29', 'cfdi'),
       (:'OTHER', 'aaaaaaaa-0000-7000-8000-0000000003b1', 0.150, '2026-09-30', null, 'cfdi');

select ok(app.compute_dish_costs(:'TENANT', '2026-08-17', '2026-10-12') > 0, 'dish cost snapshots computed by the engine');
create temp table before_counts as
select (select count(*) from public.pending_change) as pending, (select count(*) from public.menu_item_price) as prices,
       (select count(*) from public.price_suggestion) as suggestions, (select count(*) from public.ingredient_price) as costs;

-- privileges -------------------------------------------------------------------------------
select ok(has_function_privilege('service_role', 'app.evaluate_cost_alerts(uuid, date, date)', 'execute'), 'the backend runs the evaluator');
select ok(not has_function_privilege('authenticated', 'app.evaluate_cost_alerts(uuid, date, date)', 'execute'), 'clients cannot');
select ok(not has_function_privilege('anon', 'app.evaluate_cost_alerts(uuid, date, date)', 'execute'), 'nor anon');
select ok(not has_function_privilege('authenticated', 'app.ingredient_spend(uuid, date, date)', 'execute'), 'spend ranking is the backend''s');
select ok(not has_function_privilege('authenticated', 'app.tenant_today(uuid)', 'execute'), 'and the tenant''s today');
select ok(has_function_privilege('authenticated', 'app.price_jumps(uuid, date, date)', 'execute'), 'get_cost_alerts uses the jump rule as the caller');
select ok(not has_table_privilege('authenticated', 'public.alert', 'insert,update,delete'), 'clients read alerts only');
select throws_ok($$select app.evaluate_cost_alerts(null, '2026-10-12')$$, '22023', null, 'a tenant is required');
select throws_ok($$select app.evaluate_cost_alerts('03299e41-28bd-5779-bcc6-0e5e76580fad', null)$$, '22023', null, 'and a day');

-- the seed, one run per day over 2026-09-12..10-12 -----------------------------------------
select is(pg_temp.evaluate(:'TENANT', '2026-09-12', '2026-10-12', '2026-10-12'), 19, '2 price jumps and 17 breaches');
select results_eq(
  $$select i.name, a.as_of, a.value, a.threshold, a.old_unit_price, a.new_unit_price, a.avg_unit_price, a.urgent, a.status, a.location_id
    from public.alert a join public.ingredient i on i.id = a.ingredient_id where a.rule = 'price_jump' order by a.as_of$$,
  $$values ('Carne al pastor (adobada)'::text, '2026-09-21'::date, 14.7059::numeric, 8.0::numeric, 0.170::numeric, 0.195::numeric, 0.170::numeric, false, 'open'::text, null::uuid),
           ('Aguacate Hass', '2026-09-28', 61.8182, 15.0, 0.055, 0.089, 0.055, false, 'open', null)$$,
  'the two seed jumps: pastor +14.7 % (8 % vs its 30-day average), aguacate +61.8 % (15 % vs the last price; a catch-up on 10-12 marks it not urgent: 14 days old)');
select results_eq(
  $$select l.name, m.name, a.as_of, a.value, a.threshold, a.urgent
    from public.alert a join public.location l on l.id = a.location_id join public.menu_item m on m.id = a.menu_item_id
    where a.rule = 'margin_breach' order by l.name, m.name$$,
  $$values ('Centro'::text, 'Agua mineral'::text, '2026-08-17'::date, 46.4037::numeric, 35.0::numeric, false),
           ('Centro', 'Alambre de res', '2026-08-17', 49.0880, 35.0, false),
           ('Centro', 'Cerveza Corona', '2026-08-17', 46.4037, 35.0, false),
           ('Centro', 'Coca-Cola', '2026-08-17', 54.1377, 35.0, false),
           ('Centro', 'Gringa de pastor', '2026-08-17', 43.0540, 35.0, false),
           ('Centro', 'Tacos de bistec (orden de 3)', '2026-08-17', 39.1587, 35.0, false),
           ('Centro', 'Tacos de suadero (orden de 3)', '2026-08-17', 38.8300, 35.0, false),
           ('Centro', 'Torta de pastor', '2026-08-17', 50.0072, 35.0, false),
           ('Centro', 'Volcán de pastor', '2026-09-21', 37.6901, 35.0, false),
           ('Polanco', 'Agua mineral', '2026-08-17', 42.1793, 35.0, false),
           ('Polanco', 'Alambre de res', '2026-08-17', 44.4863, 35.0, false),
           ('Polanco', 'Cerveza Corona', '2026-08-17', 41.7633, 35.0, false),
           ('Polanco', 'Coca-Cola', '2026-08-17', 49.2091, 35.0, false),
           ('Polanco', 'Gringa de pastor', '2026-08-17', 38.9362, 35.0, false),
           ('Polanco', 'Tacos de bistec (orden de 3)', '2026-08-17', 35.3878, 35.0, false),
           ('Polanco', 'Tacos de suadero (orden de 3)', '2026-08-17', 35.2968, 35.0, false),
           ('Polanco', 'Torta de pastor', '2026-08-17', 45.4653, 35.0, false)$$,
  'one breach per dish and location above 35 %, dated from the start of the breach, valued at the latest run day (Volcán de pastor crossed with the pastor jump); none urgent (R3): each started weeks before the first run, so it is an existing problem for the weekly report');
select is((select count(*) from public.alert a
           left join public.dish_cost_snapshot s on s.tenant_id = a.tenant_id and s.location_id = a.location_id
                                                and s.menu_item_id = a.menu_item_id
                                                and s.date = (select max(x.date) from public.dish_cost_snapshot x
                                                              where x.tenant_id = a.tenant_id and x.location_id = a.location_id
                                                                and x.menu_item_id = a.menu_item_id and x.date <= '2026-10-12')
           where a.rule = 'margin_breach'
             and (a.confidence is null or a.confidence is distinct from s.confidence
                  or a.value is distinct from round(100.0 * s.cost / s.price_net, 4))), 0::bigint,
          'every open breach carries the value and confidence of its dish''s latest evaluated snapshot (the evaluator refreshes them)');
select is((select count(*) from public.alert a where a.rule = 'price_jump' and a.confidence is not null), 0::bigint,
          'a price jump carries no dish cost confidence');
select is((select count(*) from (select distinct s.location_id, s.menu_item_id from public.dish_cost_snapshot s
           where s.tenant_id = :'TENANT' and s.date between '2026-09-12' and '2026-10-12' and s.food_cost_pct > 35) x),
          (select count(*) from public.alert where rule = 'margin_breach'), 'exactly the dishes whose snapshots breach in the window');
select is((select count(*) from public.alert where rule = 'margin_breach' and menu_item_id = :'PASTOR'), 0::bigint,
          'tacos al pastor (32.8 %) is within target + 3');

select is(pg_temp.evaluate(:'TENANT', '2026-09-12', '2026-10-12', '2026-10-12'), 0, 'a rerun adds nothing');
select is((select count(*) from public.alert), 19::bigint, 'no duplicates');
select is((select count(*) from public.alert where tenant_id <> :'TENANT'), 0::bigint, 'nothing for another tenant');
select is((select row(count(*) filter (where status = 'open'), count(*) filter (where location_id is null)) from public.alert),
          row(19::bigint, 2::bigint), 'every alert open; price jumps are tenant-level (no location)');

-- never applied -----------------------------------------------------------------------------
select is((select row(b.pending, b.prices, b.suggestions, b.costs) from before_counts b),
          (select row(count(*), (select count(*) from public.menu_item_price), (select count(*) from public.price_suggestion),
                      (select count(*) from public.ingredient_price)) from public.pending_change),
          'no pending change, menu price, suggestion or ingredient price is written');

-- the other tenant: its own jump only --------------------------------------------------------
select is(pg_temp.evaluate(:'OTHER', '2026-09-12', '2026-10-12', '2026-10-12'), 1, 'the other tenant gets its own jump');
select results_eq($$select a.as_of, a.value, a.threshold, a.urgent from public.alert a where a.tenant_id = 'aaaaaaaa-0000-7000-8000-000000000033'$$,
                  $$values ('2026-09-30'::date, 50.0000::numeric, 15.0::numeric, false)$$,
                  '+50 %, not urgent: no sales, so not a top-20 ingredient by spend');
select is((select count(*) from public.alert where tenant_id = :'TENANT'), 19::bigint, 'and El Güero''s alerts are untouched');

-- reading alerts (RLS) ----------------------------------------------------------------------
select is(pg_temp.alerts_seen(:OWNER), 19::bigint, 'the owner sees El Güero''s alerts');
select is(pg_temp.alerts_seen(:POLANCO_MGR), 10::bigint, 'a Polanco manager sees Polanco''s 8 breaches and the 2 tenant-level jumps');
select is(pg_temp.alerts_seen(:OTHER_OWNER), 1::bigint, 'the other tenant sees its own only');
select is(pg_temp.alerts_seen('{}'), 0::bigint, 'no claims, no alerts');

-- get_cost_alerts uses the same rule ----------------------------------------------------------
select is((select jsonb_agg(jsonb_build_array(m ->> 'ingredient', m #> '{change,raw}')) from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}') m),
          (select jsonb_agg(jsonb_build_array(i.name, a.value) order by a.as_of) from public.alert a
           join public.ingredient i on i.id = a.ingredient_id where a.tenant_id = :'TENANT' and a.rule = 'price_jump'),
          'the RPC''s price moves are the alerts'' jumps, with the same change');
select is(pg_temp.rpc(:OTHER_OWNER, format('api.get_cost_alerts(%L)', '"last_30d"')) #> '{data,price_moves,0,change}',
          '{"raw": 50, "text": "+50.0%"}', 'and the other tenant''s RPC sees its own jump only');

savepoint moves;
-- pastor jumps again on 10-05 (+28.2 % vs $195), aguacate goes to zero on 10-12
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.250, '2026-10-05', 'cfdi'), (:'TENANT', :'AVOCADO', 0, '2026-10-12', 'manual');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}',
          '[{"ingredient": "Carne al pastor (adobada)", "change": {"raw": 47.0588, "text": "+47.1%"},
             "new_unit_price": {"raw": 0.25, "base_unit": "g", "text": "$250.00/kg"}}]',
          'two jumps on one ingredient: one move, from the price before the window ($170) to the one at its end; an ingredient at zero at the window''s end is left out');
rollback to savepoint moves;

-- the jump rule ------------------------------------------------------------------------------
savepoint creep;
-- bistec creeps: +7 % on 10-01 (no rule fires), +2.8 % more on 10-08: 8.2 % above its 30-day average
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'BISTEC', 0.2247, '2026-10-01', 'cfdi'), (:'TENANT', :'BISTEC', 0.231, '2026-10-08', 'cfdi');
select is((select row(j.started, j.avg_unit_price, j.threshold_pct, round(j.change_pct, 4))
           from app.price_jumps(:'TENANT', '2026-09-12', '2026-10-12') j where j.ingredient_id = :'BISTEC'),
          row('2026-10-08'::date, 0.213430::numeric, 8.0::numeric, round(100 * (0.231 - 0.21343) / 0.21343, 4)),
          'a creeping price fires the 30-day average rule (23 days at $210 and 7 at $224.70)');
select is((select m #> '{change,raw}' from jsonb_array_elements(
             pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}') m
           where m ->> 'ingredient' = 'Bistec de res'),
          '10'::jsonb, 'the RPC quotes the whole move over the window ($210 to $231), not the last step');
select is((select count(*) from app.price_jumps(:'TENANT', '2026-10-01', '2026-10-01')), 0::bigint, '+7 % alone is no jump');
rollback to savepoint creep;

savepoint lag;
-- after its +61.8 % jump on 09-28, aguacate eases from $89 to $87/kg on 10-05: -2.2 % vs the last
-- price, but still far above its lagging 30-day average, which it never crossed on the way down
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'AVOCADO', 0.087, '2026-10-05', 'nota');
select is((select count(*) from app.price_jumps(:'TENANT', '2026-10-05', '2026-10-05')), 0::bigint,
          'a small move after a jump is no jump, though the 30-day average still lags behind it');
select is(pg_temp.evaluate(:'TENANT', '2026-10-05', '2026-10-12', '2026-10-12'), 0, 'so no second aguacate alert');
select is((select jsonb_agg(jsonb_build_array(m ->> 'ingredient', m #> '{change,raw}', m #> '{new_unit_price,raw}'))
           from jsonb_array_elements(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}') m),
          '[["Carne al pastor (adobada)", 14.7059, 0.195], ["Aguacate Hass", 58.1818, 0.087]]',
          'the RPC quotes the move from the price before the window ($55) to the one at its end ($87)');
-- a fall back to $54 is a jump down (-37.9 %), but over the window the price barely moved: no row
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'AVOCADO', 0.054, '2026-10-12', 'nota');
select is((select jsonb_agg(jsonb_build_array(m ->> 'text', m #> '{new_unit_price,raw}'))
           from jsonb_array_elements(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_30d"', :'CENTRO')) #> '{data,price_moves}') x,
                lateral (select x || jsonb_build_object('text', x #>> '{change,text}')) y(m)
           where m ->> 'ingredient' = 'Aguacate Hass'),
          null, 'a move since undone (-1.8 % from $55) is left out, never quoted with the wrong sign');
select is((select count(*) from app.price_jumps(:'TENANT', '2026-10-12', '2026-10-12') j where j.ingredient_id = :'AVOCADO'),
          1::bigint, 'though the fall itself is a jump');
rollback to savepoint lag;

savepoint second_step;
-- pastor $170 -> $195 on 09-21, then $215 on 09-24: +10.3 % vs the last price, far above the
-- 30-day average ($172.50) it never came back to; the second step is a jump too
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.215, '2026-09-24', 'cfdi');
select is((select jsonb_agg(jsonb_build_array(j.started, j.old_unit_price, j.new_unit_price, j.threshold_pct, round(j.change_pct, 4))
                            order by j.started)
           from app.price_jumps(:'TENANT', '2026-09-12', '2026-10-12') j where j.ingredient_id = :'MEAT'),
          jsonb_build_array(jsonb_build_array('2026-09-21', 0.170, 0.195, 8.0, 14.7059),
                            jsonb_build_array('2026-09-24', 0.195, 0.215, 8.0, round(100 * (0.215 - 0.1725) / 0.1725, 4))),
          'both steps are jumps (the second on the 30-day average rule)');
select is(pg_temp.evaluate(:'TENANT', '2026-09-24', '2026-09-24', '2026-10-12'), 1, 'the second step is alerted');
select is((select count(*) from public.alert a where a.ingredient_id = :'MEAT' and a.rule = 'price_jump'), 2::bigint,
          'one alert per step');
select is(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO'), '2026-09-27') #> '{data,price_moves}',
          '[{"ingredient": "Carne al pastor (adobada)", "change": {"raw": 26.4706, "text": "+26.5%"},
             "new_unit_price": {"raw": 0.215, "base_unit": "g", "text": "$215.00/kg"}}]',
          'the RPC quotes the move from the price before the window ($170) to $215, not the first step');
rollback to savepoint second_step;

savepoint drops;
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.156, '2026-10-12', 'cfdi');
select is((select row(j.threshold_pct, round(j.change_pct, 4)) from app.price_jumps(:'TENANT', '2026-10-12', '2026-10-12') j),
          row(15.0::numeric, -20.0000::numeric), 'a 20 % drop is a jump too');
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 1, 'it is alerted');
select is((select row(a.value, a.urgent) from public.alert a where a.as_of = '2026-10-12' and a.rule = 'price_jump'),
          row(-20.0000::numeric, false), 'but a drop is never urgent');
rollback to savepoint drops;

savepoint zero;
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'AVOCADO', 0, '2026-10-12', 'manual');
select is((select count(*) from app.price_jumps(:'TENANT', '2026-10-12', '2026-10-12')), 0::bigint, 'a zero price is no jump');
rollback to savepoint zero;

savepoint benchmark;
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.400, '2026-10-12', 'benchmark');
select is((select count(*) from app.price_jumps(:'TENANT', '2026-10-12', '2026-10-12')), 0::bigint,
          'a benchmark price is never the price of record, so it is no jump');
rollback to savepoint benchmark;

savepoint retired;
update public.menu_item set is_active = false where tenant_id = :'TENANT';
select is((select count(*) from app.price_jumps(:'TENANT', '2026-09-12', '2026-10-12')), 0::bigint,
          'no live dish uses the ingredient: no jump');
rollback to savepoint retired;

-- urgency (U3) ------------------------------------------------------------------------------
savepoint urgent;
-- meat to $300/kg today: a +53.8 % jump on the top ingredient by spend, and tacos al pastor (a
-- top-10 dish at both locations, on an estimated cost in the seed) breaches today
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-12', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-12', '2026-10-12') > 0, 'today recomputed');
select ok(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12') > 0, 'evaluated today');
select is((select row(a.value, a.threshold, a.urgent) from public.alert a where a.rule = 'price_jump' and a.as_of = '2026-10-12'),
          row(53.8462::numeric, 15.0::numeric, true), 'the meat jump is urgent');
select is((select array_agg(l.name || ' ' || a.confidence || ' ' || a.urgent order by l.name) from public.alert a
           join public.location l on l.id = a.location_id
           where a.rule = 'margin_breach' and a.menu_item_id = :'PASTOR' and a.as_of = '2026-10-12'),
          array['Centro estimated false', 'Polanco estimated false']::text[],
          'a new breach on a top-10 dish whose seed cost is estimated is recorded, tagged estimated, and not urgent');
select is((select count(*) from public.alert a where a.rule = 'margin_breach' and a.as_of < '2026-10-12' and a.urgent), 0::bigint,
          'ongoing breaches stay as they were');
rollback to savepoint urgent;

savepoint urgent_confidence;
-- owner decision 2026-11-07: the same-day message goes out only on a confirmed dish cost. Tacos al
-- pastor breach today at both locations, on a confirmed cost at Centro and an estimated one at
-- Polanco: Centro's is urgent, Polanco's is recorded (for the weekly report, marked as estimated)
-- but not urgent
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-12', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-12', '2026-10-12') > 0, 'today recomputed');
update public.dish_cost_snapshot set confidence = case location_id when :'CENTRO' then 'confirmed' else 'estimated' end::app.cost_confidence
where menu_item_id = :'PASTOR' and date = '2026-10-12';
select ok(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12') > 0, 'evaluated today');
select results_eq(
  $$select l.name, a.confidence::text, a.urgent from public.alert a join public.location l on l.id = a.location_id
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.as_of = '2026-10-12' order by l.name$$,
  $$values ('Centro'::text, 'confirmed'::text, true), ('Polanco', 'estimated', false)$$,
  'a fresh breach on a top-10 dish is urgent on a confirmed cost; on an estimated cost it is recorded, tagged, not urgent');
rollback to savepoint urgent_confidence;

savepoint confirm_flip;
-- owner decision 2026-11-07: a breach first seen on an estimated cost becomes urgent the first time
-- its cost is confirmed while it is still over the limit. Tacos al pastor at Centro (a top-10
-- dish) breach from 10-11: estimated on 10-11, confirmed on 10-12
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = case date when '2026-10-11' then 'estimated' else 'confirmed' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select ok(pg_temp.evaluate(:'TENANT', '2026-10-11', '2026-10-11', '2026-10-11') > 0, 'day 1 evaluated');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-11'::date, 'estimated'::text, false)$$, 'day 1: recorded on an estimated cost, not urgent');
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 0, 'day 2 adds no alert');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-11'::date, 'confirmed'::text, true)$$, 'day 2: the same row, now confirmed and urgent');
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 0, 'a rerun of day 2 adds nothing');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-11'::date, 'confirmed'::text, true)$$, 'and changes nothing: one row');
-- a late CFDI recompute makes day 3's cost estimated again: the tag follows and an estimated alert is never urgent (R1)
update public.dish_cost_snapshot set confidence = 'estimated'
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date = '2026-10-12';
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 0, 'rerun after a recompute adds nothing');
select results_eq(
  $$select a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('estimated'::text, false)$$, 'a recompute that downgrades the cost refreshes the tag and the alert is not urgent while estimated');
rollback to savepoint confirm_flip;

savepoint confirm_stays_estimated;
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = 'estimated'
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select ok(pg_temp.evaluate(:'TENANT', '2026-10-11', '2026-10-12', '2026-10-12') > 0, 'both days evaluated');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-11'::date, 'estimated'::text, false)$$, 'still estimated on day 2: stays not urgent');
rollback to savepoint confirm_stays_estimated;

savepoint flip_daily;
-- daily runs, estimated from the breach's start (10-01) to 10-11, confirmed on 10-12: the flip is
-- judged on the day it happens (10-12), not on the breach's start 11 days earlier
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-01', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-01', '2026-10-12') > 0, 'twelve days recomputed');
update public.dish_cost_snapshot set confidence = case when date = '2026-10-12' then 'confirmed' else 'estimated' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-01';
select ok(pg_temp.evaluate_daily(:'TENANT', '2026-10-01', '2026-10-11') > 0, 'estimated days evaluated daily');
select is((select a.urgent from public.alert a where a.rule = 'margin_breach' and a.menu_item_id = :'PASTOR' and a.location_id = :'CENTRO'),
          false, 'estimated for eleven days: not urgent');
select ok(pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12') >= 0, 'confirmation day evaluated');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-01'::date, 'confirmed'::text, true)$$, 'confirmed on 10-12 while still over the limit: the one row is confirmed and urgent');
rollback to savepoint flip_daily;

savepoint flip_value;
-- the flip takes the food cost with the tag: estimated 10-11 at a higher cost, confirmed 10-12
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = case date when '2026-10-11' then 'estimated' else 'confirmed' end::app.cost_confidence,
  cost = case date when '2026-10-11' then cost * 1.3 else cost end
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select pg_temp.evaluate_daily(:'TENANT', '2026-10-11', '2026-10-11');
select is((select a.value from public.alert a where a.rule = 'margin_breach' and a.menu_item_id = :'PASTOR' and a.location_id = :'CENTRO'),
          (select round(100.0 * s.cost / s.price_net, 4) from public.dish_cost_snapshot s
           where s.menu_item_id = :'PASTOR' and s.location_id = :'CENTRO' and s.date = '2026-10-11'), 'day 1: the estimated cost');
select pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent,
           a.value = (select round(100.0 * s.cost / s.price_net, 4) from public.dish_cost_snapshot s
                      where s.menu_item_id = a.menu_item_id and s.location_id = a.location_id and s.date = '2026-10-12'),
           a.value < (select round(100.0 * s.cost / s.price_net, 4) from public.dish_cost_snapshot s
                      where s.menu_item_id = a.menu_item_id and s.location_id = a.location_id and s.date = '2026-10-11')
    from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-11'::date, 'confirmed'::text, true, true, true)$$, 'day 2: confirmed, urgent, and the confirmed (lower) food cost, not the estimated one');
rollback to savepoint flip_value;

savepoint first_seen_confirmed;
-- one run on 10-12 for a breach that started on 10-11 on an estimated cost: confidence, value and
-- urgency come from the 10-12 snapshot (confirmed), as_of stays the start
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = case date when '2026-10-11' then 'estimated' else 'confirmed' end::app.cost_confidence,
  cost = case date when '2026-10-11' then cost * 1.3 else cost end
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent,
           a.value = (select round(100.0 * s.cost / s.price_net, 4) from public.dish_cost_snapshot s
                      where s.menu_item_id = a.menu_item_id and s.location_id = a.location_id and s.date = '2026-10-12')
    from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-11'::date, 'confirmed'::text, true, true)$$, 'first seen on 10-12: confirmed, urgent, the 10-12 cost, dated from its start');
rollback to savepoint first_seen_confirmed;

savepoint flip_catchup;
-- confirmed on 10-12 but evaluated on 10-25: the evidence is stale, so the tag follows and the alert stays not urgent
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = case date when '2026-10-11' then 'estimated' else 'confirmed' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select pg_temp.evaluate(:'TENANT', '2026-10-11', '2026-10-11', '2026-10-11');
select pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-25');
select results_eq(
  $$select a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('confirmed'::text, false)$$, 'a catch-up run confirms the tag but does not make it urgent');
rollback to savepoint flip_catchup;

savepoint flip_status;
-- an alert the owner already acknowledged or dismissed is never flipped or refreshed
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = case date when '2026-10-11' then 'estimated' else 'confirmed' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select pg_temp.evaluate(:'TENANT', '2026-10-11', '2026-10-11', '2026-10-11');
update public.alert set status = 'acknowledged' where rule = 'margin_breach' and menu_item_id = :'PASTOR' and location_id = :'CENTRO';
select pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12');
select results_eq(
  $$select a.status, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('acknowledged'::text, 'estimated', false)$$, 'an acknowledged alert is not flipped');
update public.alert set status = 'dismissed' where rule = 'margin_breach' and menu_item_id = :'PASTOR' and location_id = :'CENTRO';
select pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12');
select results_eq(
  $$select a.status, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('dismissed'::text, 'estimated', false)$$, 'a dismissed alert is not flipped');
rollback to savepoint flip_status;

savepoint flip_ended;
-- the confirmed 10-12 cost is back within the limit: the breach has ended, the row stays as it was
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = case date when '2026-10-11' then 'estimated' else 'confirmed' end::app.cost_confidence,
  cost = case date when '2026-10-12' then price_net / 4 else cost end
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select pg_temp.evaluate(:'TENANT', '2026-10-11', '2026-10-11', '2026-10-11');
create temp table before_end as
  select a.value, a.confidence, a.urgent from public.alert a
  where a.rule = 'margin_breach' and a.menu_item_id = :'PASTOR' and a.location_id = :'CENTRO';
select pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12');
select results_eq(
  $$select a.value, a.confidence, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$select value, confidence, urgent from before_end$$, 'a breach that ended on a confirmed cost is not flipped');
rollback to savepoint flip_ended;

savepoint catchup_downgrade;
-- R1 (B1): one catch-up over 10-11 (confirmed) and 10-12 (estimated), run on 10-12: the row ends
-- estimated and not urgent, though 10-11 alone would have made it urgent
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = case date when '2026-10-11' then 'confirmed' else 'estimated' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select pg_temp.evaluate(:'TENANT', '2026-10-11', '2026-10-12', '2026-10-12');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-11'::date, 'estimated'::text, false)$$, 'confirmed then estimated in one catch-up: one estimated row, not urgent');
rollback to savepoint catchup_downgrade;

savepoint first_run_existing;
-- R3: a first run on 10-12 with confirmed costs: breaches that started on 08-17 are existing
-- problems, none urgent
delete from public.alert;
update public.dish_cost_snapshot set confidence = 'confirmed' where tenant_id = :'TENANT';
select ok(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12') > 0, 'first run');
select is((select count(*) from public.alert a where a.rule = 'margin_breach' and a.urgent), 0::bigint,
          'a first run records the breaches that already existed as not urgent');
select ok((select count(*) from public.alert a where a.rule = 'margin_breach' and a.as_of = '2026-08-17') > 0, 'they are dated from their start');
rollback to savepoint first_run_existing;

savepoint new_breach_first_run;
-- R3: a breach that started 10-11, confirmed on 10-12, first run on 10-12: urgent
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'two days recomputed');
update public.dish_cost_snapshot set confidence = 'confirmed' where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-11'::date, 'confirmed'::text, true)$$, 'a new breach (started within 7 days) first seen on a confirmed fresh day is urgent');
rollback to savepoint new_breach_first_run;

savepoint flip_catchup_range;
-- m3: estimated to 10-04, confirmed from 10-05, catch-up 10-05..10-12 run on 10-12: 10-05 is not
-- fresh, so the flip waits for 10-06 and takes that day's cost
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-01', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-01', '2026-10-12') > 0, 'range recomputed');
update public.dish_cost_snapshot set confidence = case when date >= '2026-10-05' then 'confirmed' else 'estimated' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-01';
select pg_temp.evaluate_daily(:'TENANT', '2026-10-01', '2026-10-04');
select pg_temp.evaluate(:'TENANT', '2026-10-05', '2026-10-12', '2026-10-12');
select results_eq(
  $$select a.as_of, a.confidence::text, a.urgent,
           a.value = (select round(100.0 * s.cost / s.price_net, 4) from public.dish_cost_snapshot s
                      where s.menu_item_id = a.menu_item_id and s.location_id = a.location_id and s.date = '2026-10-12')
    from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values ('2026-10-01'::date, 'confirmed'::text, true, true)$$, 'a catch-up flips on the first confirmed day that is fresh');
select is((select a.awaits_confirmation from public.alert a where a.rule = 'margin_breach' and a.menu_item_id = :'PASTOR' and a.location_id = :'CENTRO'),
          false, 'and the flip uses up its one chance (R4)');
rollback to savepoint flip_catchup_range;

savepoint value_only_refresh;
-- m1: a same-confidence recompute moves the food cost; the alert follows, urgency untouched
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-12', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-12', '2026-10-12') > 0, 'today recomputed');
update public.dish_cost_snapshot set confidence = 'confirmed' where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date = '2026-10-12';
select pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12');
update public.dish_cost_snapshot set cost = cost * 1.3 where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date = '2026-10-12';
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 0, 'a refresh adds no row');
select results_eq(
  $$select a.urgent, a.value = (select round(100.0 * s.cost / s.price_net, 4) from public.dish_cost_snapshot s
                      where s.menu_item_id = a.menu_item_id and s.location_id = a.location_id and s.date = '2026-10-12')
    from public.alert a
    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73' and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
  $$values (true, true)$$, 'the value follows the snapshot and urgent is untouched');
rollback to savepoint value_only_refresh;

savepoint fresh;
-- urgent at insert (R1, R3): a confirmed cost, a breach that started within 7 days of the day
-- evaluated, a fresh day, a top-10 dish; bistec tacos are in
-- Centro's top 10 by net sales over 2026-07-20..08-18
delete from public.alert;
select ok(pg_temp.evaluate(:'TENANT', '2026-08-18', '2026-08-18', '2026-08-18') > 0, 'evaluated the second day of data');
select is((select array_agg(m.name order by m.name) from public.alert a join public.menu_item m on m.id = a.menu_item_id
           where a.rule = 'margin_breach' and a.location_id = :'CENTRO' and a.urgent),
          (select array_agg(m.name order by m.name) from public.alert a join public.menu_item m on m.id = a.menu_item_id
           where a.rule = 'margin_breach' and a.location_id = :'CENTRO'
             and a.menu_item_id in (select x.menu_item_id from (
               select v.menu_item_id, row_number() over (order by sum(v.net) desc, v.menu_item_id) as n
               from app.v_item_sales_daily v where v.location_id = :'CENTRO' and v.business_date between '2026-07-20' and '2026-08-18'
               group by v.menu_item_id) x where x.n <= 10)),
          'the breaches on Centro''s top 10 dishes are urgent, the others are not');
select ok((select bool_or(a.urgent) from public.alert a where a.menu_item_id = (select id from public.menu_item where name = 'Tacos de bistec (orden de 3)')
           and a.location_id = :'CENTRO'), 'tacos de bistec among them');
-- the evidence day 08-18 run on 08-24 is in its 7th day, on 08-25 its 8th (freshness is the evidence's)
delete from public.alert;
select ok(pg_temp.evaluate(:'TENANT', '2026-08-18', '2026-08-18', '2026-08-24') > 0, 'the same day evaluated on 08-24');
select ok((select bool_or(a.urgent) from public.alert a where a.location_id = :'CENTRO'), 'day 7: still urgent');
delete from public.alert;
select ok(pg_temp.evaluate(:'TENANT', '2026-08-18', '2026-08-18', '2026-08-25') > 0, 'and on 08-25');
select is((select count(*) from public.alert a where a.urgent), 0::bigint, 'day 8: not urgent');
rollback to savepoint fresh;

savepoint daily;
-- the daily job on 09-28 itself sees the aguacate jump the day it starts: urgent
delete from public.alert;
select ok(pg_temp.evaluate_daily(:'TENANT', '2026-09-28', '2026-09-28') > 0, 'evaluated on 09-28');
select is((select a.urgent from public.alert a where a.rule = 'price_jump' and a.ingredient_id = :'AVOCADO'), true,
          'a fresh run marks the aguacate jump urgent (a top-20 ingredient)');
-- without `today` the evaluator uses the tenant's business today
delete from public.alert;
select set_config('app.today', '2026-09-28', true);
select ok(pg_temp.evaluate(:'TENANT', '2026-09-28', '2026-09-28', null) > 0, 'evaluated with no today');
select is((select a.urgent from public.alert a where a.rule = 'price_jump' and a.ingredient_id = :'AVOCADO'), true,
          'today defaults to the business today (09-28): urgent');
select set_config('app.today', '2026-10-12', true);
select ok(pg_temp.evaluate(:'TENANT', '2026-09-28', '2026-09-28', null) = 0, 'a rerun on 10-12 adds nothing');
delete from public.alert;
select ok(pg_temp.evaluate(:'TENANT', '2026-09-28', '2026-09-28', null) > 0, 'evaluated anew on 10-12');
select is((select a.urgent from public.alert a where a.rule = 'price_jump' and a.ingredient_id = :'AVOCADO'), false,
          'business today 10-12: 15 days old, not urgent');
rollback to savepoint daily;

savepoint jump_fresh;
-- meat to $300/kg on 10-05: urgent on its 7th day (10-11), not on its 8th (10-12)
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-05', 'cfdi');
select is(pg_temp.evaluate(:'TENANT', '2026-10-05', '2026-10-05', '2026-10-11'), 1, 'the meat jump, run on 10-11');
select is((select a.urgent from public.alert a where a.as_of = '2026-10-05'), true, 'day 7: urgent');
delete from public.alert where as_of = '2026-10-05';
select is(pg_temp.evaluate(:'TENANT', '2026-10-05', '2026-10-05', '2026-10-12'), 1, 'run on 10-12');
select is((select a.urgent from public.alert a where a.as_of = '2026-10-05'), false, 'day 8: not urgent');
rollback to savepoint jump_fresh;

savepoint top20;
-- azúcar (20th by spend) and masa (22nd) both rise 16 % today; masa's new price lifts it to 21st,
-- still outside the top 20
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
select :'TENANT', x.id, p.unit_price_net * 1.16, '2026-10-12', 'cfdi'
from (values (:'SUGAR'::uuid), (:'MASA'::uuid)) x(id) cross join lateral app.price_of_record(x.id, '2026-10-11') p;
select is((select array_agg(x.n order by x.n) from (
             select s.ingredient_id, row_number() over (order by s.spend desc, s.ingredient_id) as n
             from app.ingredient_spend(:'TENANT', '2026-09-13', '2026-10-12') s where s.spend > 0) x
           where x.ingredient_id in (:'SUGAR', :'MASA')),
          array[20, 21]::bigint[], 'azúcar ranks 20th by spend, masa 21st');
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 2, 'both jumps alerted');
select results_eq($$select a.ingredient_id, a.urgent from public.alert a where a.as_of = '2026-10-12' and a.rule = 'price_jump' order by a.urgent$$,
                  format($$values (%L::uuid, false), (%L::uuid, true)$$, :'MASA', :'SUGAR'),
                  'a +16 % jump on the 21st ingredient by spend is not urgent; on the 20th it is');
rollback to savepoint top20;

savepoint at_line;
-- tacos al pastor at Centro today at exactly 35.0 %: within target + 3; at 35.01 % a breach
update public.dish_cost_snapshot set price_net = 10000, cost = 3500
where location_id = :'CENTRO' and menu_item_id = :'PASTOR' and date = '2026-10-12';
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 0, 'exactly 35.0 %: no breach');
select is((select count(*) from jsonb_array_elements(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,breaches}') b
           where b ->> 'menu_item_id' = :'PASTOR'), 0::bigint, 'nor in the RPC');
update public.dish_cost_snapshot set cost = 3501
where location_id = :'CENTRO' and menu_item_id = :'PASTOR' and date = '2026-10-12';
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 1, '35.01 %: a breach');
select is((select a.value from public.alert a where a.menu_item_id = :'PASTOR'), 35.0100::numeric, 'at its food cost');
select is((select count(*) from jsonb_array_elements(pg_temp.rpc(:OWNER, format('api.get_cost_alerts(%L, %L)', '"last_7d"', :'CENTRO')) #> '{data,breaches}') b
           where b ->> 'menu_item_id' = :'PASTOR'), 1::bigint, 'and in the RPC');
rollback to savepoint at_line;

-- breach episodes -----------------------------------------------------------------------------
savepoint episodes;
-- Volcán de pastor at Centro drops within target on 10-01 and breaches again from 10-02: a new
-- episode, alerted once
update public.dish_cost_snapshot set cost = price_net / 4 where location_id = :'CENTRO' and menu_item_id = :'VOLCAN' and date = '2026-10-01';
select is(pg_temp.evaluate(:'TENANT', '2026-10-02', '2026-10-12', '2026-10-12'), 1, 'a breach that ends and comes back is a new alert');
select is((select array_agg(a.as_of order by a.as_of) from public.alert a where a.location_id = :'CENTRO' and a.menu_item_id = :'VOLCAN'),
          array['2026-09-21', '2026-10-02']::date[], 'dated from its new start');
-- a recompute that moves an episode's start earlier does not alert it again
update public.dish_cost_snapshot set cost = price_net where location_id = :'CENTRO' and menu_item_id = :'VOLCAN' and date = '2026-09-20';
select is(pg_temp.evaluate(:'TENANT', '2026-09-21', '2026-09-30', '2026-10-12'), 0, 'an episode that now starts on 09-20 is still the 09-21 alert');
-- no snapshot, no alert (never a guess)
delete from public.alert where location_id = :'POLANCO';
delete from public.dish_cost_snapshot where location_id = :'POLANCO' and date = '2026-10-12';
select is(pg_temp.evaluate(:'TENANT', '2026-10-12', '2026-10-12', '2026-10-12'), 0, 'no Polanco snapshot today: no Polanco breach');
rollback to savepoint episodes;

-- owner rules R1-R4: urgency at most once, only for a new breach on a confirmed fresh day -------
\set QUESO '7724df82-1a06-5a9b-8bb9-6f56aeba7e37'
create function pg_temp.pastor_centro() returns table (as_of date, confidence text, urgent boolean, awaits boolean)
language sql as $$
  select a.as_of, a.confidence::text, a.urgent, a.awaits_confirmation from public.alert a
  where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73'
    and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22' $$;
create function pg_temp.version_of(item uuid) returns int
language sql as $$
  select a.version from public.alert a
  where a.rule = 'margin_breach' and a.menu_item_id = item and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22' $$;

savepoint p5_first_run_estimated;
-- P5 (R3): a first run on 10-11 on estimated costs records the breaches that started on 08-17;
-- their costs are confirmed on 10-12, a fresh day: none was new, so none waits or becomes urgent
delete from public.alert;
update public.dish_cost_snapshot set confidence = case when date = '2026-10-12' then 'confirmed' else 'estimated' end::app.cost_confidence
where tenant_id = :'TENANT';
select ok(pg_temp.evaluate_daily(:'TENANT', '2026-10-11', '2026-10-11') > 0, 'P5: first run on 10-11');
select is((select row(count(*), count(*) filter (where awaits_confirmation), count(*) filter (where urgent), min(as_of))
           from public.alert where rule = 'margin_breach'),
          row(17::bigint, 0::bigint, 0::bigint, '2026-08-17'::date), 'P5: the existing breaches are recorded estimated, none waiting, none urgent');
select is(pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12'), 0, 'P5: 10-12 adds no breach');
select is((select row(count(*) filter (where confidence = 'confirmed'), count(*) filter (where urgent))
           from public.alert where rule = 'margin_breach'),
          row(17::bigint, 0::bigint), 'P5: confirmed on 10-12, still none urgent');
rollback to savepoint p5_first_run_estimated;

savepoint p6_existing_blip;
-- P6 (R3): every cost confirmed, a first run on 10-12: none urgent; the costs turn estimated and
-- are confirmed again the same day: still none urgent
delete from public.alert;
update public.dish_cost_snapshot set confidence = 'confirmed' where tenant_id = :'TENANT';
select ok(pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12') > 0, 'P6: first run on 10-12');
select is((select count(*) from public.alert where rule = 'margin_breach' and urgent), 0::bigint, 'P6: none urgent');
update public.dish_cost_snapshot set confidence = 'estimated' where tenant_id = :'TENANT' and date = '2026-10-12';
select is(pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12'), 0, 'P6: rerun on estimated costs');
update public.dish_cost_snapshot set confidence = 'confirmed' where tenant_id = :'TENANT' and date = '2026-10-12';
select is(pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12'), 0, 'P6: rerun on confirmed costs again');
select is((select row(count(*) filter (where confidence = 'confirmed'), count(*) filter (where urgent), count(*) filter (where awaits_confirmation))
           from public.alert where rule = 'margin_breach'),
          row(17::bigint, 0::bigint, 0::bigint), 'P6: confirmed, none urgent, none waiting');
rollback to savepoint p6_existing_blip;

savepoint p7_no_regrant;
-- P7 (R4): urgent on 10-11, its cost turns estimated on 10-12 (not urgent, R1), then is confirmed
-- again: urgency is never granted twice, and the row stops changing
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-11', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-11', '2026-10-12') > 0, 'P7: two days recomputed');
update public.dish_cost_snapshot set confidence = 'confirmed' where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-11';
select pg_temp.evaluate_daily(:'TENANT', '2026-10-11', '2026-10-11');
select results_eq($$select * from pg_temp.pastor_centro()$$, $$values ('2026-10-11'::date, 'confirmed'::text, true, false)$$,
                  'P7: a new confirmed breach on a top-10 dish is urgent');
update public.dish_cost_snapshot set confidence = 'estimated' where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date = '2026-10-12';
select pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12');
select results_eq($$select * from pg_temp.pastor_centro()$$, $$values ('2026-10-11'::date, 'estimated'::text, false, false)$$,
                  'P7: estimated: not urgent, and not waiting again');
update public.dish_cost_snapshot set confidence = 'confirmed' where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date = '2026-10-12';
select pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12');
select results_eq($$select * from pg_temp.pastor_centro()$$, $$values ('2026-10-11'::date, 'confirmed'::text, false, false)$$,
                  'P7: confirmed again: stays not urgent (urgency at most once)');
create temp table p7_version as select pg_temp.version_of(:'PASTOR') as v;
select is(pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12'), 0, 'P7: an identical rerun adds nothing');
select is(pg_temp.version_of(:'PASTOR'), (select v from p7_version), 'P7: and writes no new version');
rollback to savepoint p7_no_regrant;

savepoint r2_daily_once;
-- R2: daily runs on a breach that starts on 10-08, estimated to 10-10, confirmed from 10-11: it
-- waits, becomes urgent once on 10-11 and stays so; reruns write nothing
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-08', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-08', '2026-10-12') > 0, 'R2: five days recomputed');
update public.dish_cost_snapshot set confidence = case when date >= '2026-10-11' then 'confirmed' else 'estimated' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-08';
select pg_temp.evaluate_daily(:'TENANT', '2026-10-08', '2026-10-10');
select results_eq($$select * from pg_temp.pastor_centro()$$, $$values ('2026-10-08'::date, 'estimated'::text, false, true)$$,
                  'R2: a new breach on an estimated cost waits, not urgent');
select pg_temp.evaluate_daily(:'TENANT', '2026-10-11', '2026-10-11');
select results_eq($$select * from pg_temp.pastor_centro()$$, $$values ('2026-10-08'::date, 'confirmed'::text, true, false)$$,
                  'R2: confirmed on a fresh day while still over the limit: urgent, the wait is over');
select pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12');
create temp table r2_version as select pg_temp.version_of(:'PASTOR') as v;
select is(pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12'), 0, 'R2: a rerun adds nothing');
select results_eq($$select * from pg_temp.pastor_centro()$$, $$values ('2026-10-08'::date, 'confirmed'::text, true, false)$$,
                  'R2: one row, still urgent');
select is(pg_temp.version_of(:'PASTOR'), (select v from r2_version), 'R2: and no new version');
rollback to savepoint r2_daily_once;

savepoint f4_chance_used;
-- F4 (R4): quesadilla de queso (Centro's 11th dish by net sales) breaches from 10-11 on an
-- estimated cost and waits; confirmed on a fresh 10-12 outside the top 10, the chance is used up
-- (not urgent), so it stays not urgent once it enters the top 10
update public.dish_cost_snapshot set cost = price_net / 2,
  confidence = case date when '2026-10-11' then 'estimated' else 'confirmed' end::app.cost_confidence
where menu_item_id = :'QUESO' and location_id = :'CENTRO' and date >= '2026-10-11';
select is(pg_temp.evaluate_daily(:'TENANT', '2026-10-11', '2026-10-11'), 1, 'F4: the new breach is recorded on 10-11');
select results_eq($$select a.confidence::text, a.urgent, a.awaits_confirmation from public.alert a
                    where a.rule = 'margin_breach' and a.menu_item_id = '7724df82-1a06-5a9b-8bb9-6f56aeba7e37'
                      and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
                  $$values ('estimated'::text, false, true)$$, 'F4: estimated, waiting');
select pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12');
select results_eq($$select a.confidence::text, a.urgent, a.awaits_confirmation from public.alert a
                    where a.rule = 'margin_breach' and a.menu_item_id = '7724df82-1a06-5a9b-8bb9-6f56aeba7e37'
                      and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
                  $$values ('confirmed'::text, false, false)$$, 'F4: confirmed on a fresh day outside the top 10: the wait is over, not urgent');
create temp table f4_version as select pg_temp.version_of(:'QUESO') as v;
select is(pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12'), 0, 'F4: an identical rerun adds nothing');
select is(pg_temp.version_of(:'QUESO'), (select v from f4_version), 'F4: and writes no new version');
update public.item_sales_agg set net = net + 1000000, gross = gross + 1000000
where tenant_id = :'TENANT' and location_id = :'CENTRO' and menu_item_id = :'QUESO' and period_from = '2026-10-11';
select ok((select x.n <= 10 from (
             select v.menu_item_id, row_number() over (order by sum(v.net) desc, v.menu_item_id) as n
             from app.v_item_sales_daily v where v.location_id = :'CENTRO' and v.business_date between '2026-09-13' and '2026-10-12'
             group by v.menu_item_id) x where x.menu_item_id = :'QUESO'), 'F4: a late-booked 10-11 sale lifts it into the top 10 (the seed''s last sales day)');
select pg_temp.evaluate_daily(:'TENANT', '2026-10-12', '2026-10-12');
select is((select a.urgent from public.alert a where a.rule = 'margin_breach' and a.menu_item_id = :'QUESO' and a.location_id = :'CENTRO'),
          false, 'F4: in the top 10 now, still not urgent: its chance was used');
rollback to savepoint f4_chance_used;

savepoint s1_range_rerun;
-- S1: the R2 daily runs (a breach from 10-08, estimated to 10-10, urgent on 10-11), then the
-- backend reruns 10-08..10-12 on 10-12: the older days never undo the state a later day set
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-08', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-08', '2026-10-12') > 0, 'S1: five days recomputed');
update public.dish_cost_snapshot set confidence = case when date >= '2026-10-11' then 'confirmed' else 'estimated' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-08';
select pg_temp.evaluate_daily(:'TENANT', '2026-10-08', '2026-10-12');
create temp table s1_before as
  select a.as_of, a.confidence::text as confidence, a.urgent, a.awaits_confirmation, a.value, a.version, a.evaluated_on from public.alert a
  where a.rule = 'margin_breach' and a.menu_item_id = :'PASTOR' and a.location_id = :'CENTRO';
select results_eq($$select as_of, confidence, urgent, awaits_confirmation, evaluated_on from s1_before$$,
                  $$values ('2026-10-08'::date, 'confirmed'::text, true, false, '2026-10-12'::date)$$,
                  'S1: urgent after the daily runs, evaluated through 10-12');
select is(pg_temp.evaluate(:'TENANT', '2026-10-08', '2026-10-12', '2026-10-12'), 0, 'S1: the range rerun adds nothing');
select results_eq($$select a.as_of, a.confidence::text, a.urgent, a.awaits_confirmation, a.value, a.version, a.evaluated_on from public.alert a
                    where a.rule = 'margin_breach' and a.menu_item_id = 'f496f051-9f85-5f8a-a4b6-c1a814d37c73'
                      and a.location_id = '705e8e51-376b-5785-adbb-405eff4e2a22'$$,
                  $$select * from s1_before$$, 'S1: still urgent, same value, no new version');
rollback to savepoint s1_range_rerun;

savepoint s2_catchup_estimated;
-- S2 (R3): after an outage, one catch-up over 10-01..10-12 on 10-12 for a breach from 10-02. Every
-- cost confirmed: recorded on a stale day, never urgent
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-02', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-01', '2026-10-12') > 0, 'S2: range recomputed');
update public.dish_cost_snapshot set confidence = 'confirmed'
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-01';
select pg_temp.evaluate(:'TENANT', '2026-10-01', '2026-10-12', '2026-10-12');
select results_eq($$select * from pg_temp.pastor_centro()$$, $$values ('2026-10-02'::date, 'confirmed'::text, false, false)$$,
                  'S2: all confirmed, first recorded on a stale day: not urgent');
rollback to savepoint s2_catchup_estimated;
savepoint s2_catchup_estimated;
-- the same with 10-02 estimated: it does not wait either, so it never turns urgent on a fresh day
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:'TENANT', :'MEAT', 0.300, '2026-10-02', 'cfdi');
select ok(app.compute_dish_costs(:'TENANT', '2026-10-01', '2026-10-12') > 0, 'S2: range recomputed again');
update public.dish_cost_snapshot set confidence = case when date = '2026-10-02' then 'estimated' else 'confirmed' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date >= '2026-10-01';
select pg_temp.evaluate(:'TENANT', '2026-10-01', '2026-10-12', '2026-10-12');
select results_eq($$select * from pg_temp.pastor_centro()$$, $$values ('2026-10-02'::date, 'confirmed'::text, false, false)$$,
                  'S2: 10-02 estimated, first recorded on a stale day: never waits, never urgent');
rollback to savepoint s2_catchup_estimated;

savepoint s5_episode_merge;
-- S5 (R4): two breaches (10-05, 10-07..10-08) are recorded waiting; a recompute makes 10-06 breach
-- too, so they are one episode from 10-05. Confirmed on a fresh 10-11: only the earliest row
-- (the episode's) turns urgent, the later one is left as it was
update public.dish_cost_snapshot set cost = price_net / 2,
  confidence = case when date <= '2026-10-08' then 'estimated' else 'confirmed' end::app.cost_confidence
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date in ('2026-10-05', '2026-10-07', '2026-10-08', '2026-10-11', '2026-10-12');
select pg_temp.evaluate_daily(:'TENANT', '2026-10-05', '2026-10-08');
select results_eq($$select * from pg_temp.pastor_centro() order by as_of$$,
                  $$values ('2026-10-05'::date, 'estimated'::text, false, true), ('2026-10-07', 'estimated', false, true)$$,
                  'S5: two breaches, both waiting');
update public.dish_cost_snapshot set cost = price_net / 2, confidence = 'estimated'
where menu_item_id = :'PASTOR' and location_id = :'CENTRO' and date in ('2026-10-06', '2026-10-09', '2026-10-10');
select pg_temp.evaluate_daily(:'TENANT', '2026-10-09', '2026-10-12');
select results_eq($$select * from pg_temp.pastor_centro() order by as_of$$,
                  $$values ('2026-10-05'::date, 'confirmed'::text, true, false), ('2026-10-07', 'estimated', false, true)$$,
                  'S5: merged into one episode: one urgent row, the later row untouched');
rollback to savepoint s5_episode_merge;

-- the alert row's shape -------------------------------------------------------------------------
select throws_ok(format($$insert into public.alert (tenant_id, rule, menu_item_id, as_of, value, threshold) values (%L, 'mix_shift', %L, '2026-10-12', 1, 1)$$, :'TENANT', :'PASTOR'),
                 '23514', null, 'only known rules');
select throws_ok(format($$insert into public.alert (tenant_id, rule, ingredient_id, as_of, value, threshold) values (%L, 'price_jump', %L, '2026-10-12', 1, 1)$$, :'TENANT', :'MEAT'),
                 '23514', null, 'a price jump carries its prices');
select throws_ok(format($$insert into public.alert (tenant_id, rule, menu_item_id, as_of, value, threshold) values (%L, 'margin_breach', %L, '2026-10-12', 40, 35)$$, :'TENANT', :'PASTOR'),
                 '23514', null, 'a breach carries its location');
select throws_ok(format($$insert into public.alert (tenant_id, location_id, rule, menu_item_id, as_of, value, threshold) values (%L, %L, 'margin_breach', %L, '2026-10-12', 40, 35)$$, :'TENANT', :'CENTRO', :'PASTOR'),
                 '23514', null, 'a breach carries its cost confidence');
select throws_ok(format($$insert into public.alert (tenant_id, location_id, rule, menu_item_id, as_of, value, threshold, confidence, status) values (%L, %L, 'margin_breach', %L, '2026-10-12', 40, 35, 'confirmed', 'closed')$$, :'TENANT', :'CENTRO', :'PASTOR'),
                 '23514', null, 'only known statuses');
select throws_ok(format($$insert into public.alert (tenant_id, location_id, rule, menu_item_id, as_of, value, threshold, confidence) values (%L, %L, 'margin_breach', %L, '2026-10-12', 40, 35, 'confirmed')$$, :'OTHER', :'CENTRO', :'PASTOR'),
                 '23503', null, 'a dish and a location of another tenant are refused');
select throws_ok(format($$insert into public.alert (tenant_id, location_id, rule, menu_item_id, as_of, value, threshold, confidence, urgent) values (%L, %L, 'margin_breach', %L, '2026-10-12', 40, 35, 'estimated', true)$$, :'TENANT', :'CENTRO', :'PASTOR'),
                 '23514', null, 'an urgent breach on an estimated cost is refused (R1)');
select throws_ok(format($$insert into public.alert (tenant_id, location_id, rule, menu_item_id, as_of, value, threshold, confidence, urgent, awaits_confirmation) values (%L, %L, 'margin_breach', %L, '2026-10-12', 40, 35, 'confirmed', true, true)$$, :'TENANT', :'CENTRO', :'PASTOR'),
                 '23514', null, 'an urgent breach still waiting is refused (R4)');
select throws_ok(format($$insert into public.alert (tenant_id, rule, ingredient_id, as_of, value, threshold, old_unit_price, new_unit_price, avg_unit_price, awaits_confirmation) values (%L, 'price_jump', %L, '2026-10-12', 20, 15, 0.1, 0.12, 0.1, true)$$, :'TENANT', :'MEAT'),
                 '23514', null, 'a price jump never waits for a confirmed cost');
select lives_ok(format($$insert into public.alert (tenant_id, rule, ingredient_id, as_of, value, threshold, old_unit_price, new_unit_price, avg_unit_price, urgent) values (%L, 'price_jump', %L, '2026-10-13', 20, 15, 0.1, 0.12, 0.1, true)$$, :'TENANT', :'MEAT'),
                'an urgent price jump (no dish cost) is allowed');

select * from finish();
rollback;
