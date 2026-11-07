-- MR-100: the nightly job's SQL. Service-role only; at most 31 days per call; insert only (a
-- rerun writes nothing and keeps row ids); the rows it writes are app.compute_dish_costs' rows.
begin;
select * from no_plan();

\set TENANT '''03299e41-28bd-5779-bcc6-0e5e76580fad'''
set local app.today = '2026-10-12';

-- privileges ---------------------------------------------------------------------------------
select ok(has_function_privilege('service_role', 'app.fill_dish_costs(uuid, date, date)', 'execute')
          and has_function_privilege('service_role', 'app.nightly_dish_cost_range(uuid, int)', 'execute')
          and has_function_privilege('service_role', 'app.business_today(uuid)', 'execute'),
          'the backend runs the nightly job');
select is((select count(*) from pg_proc p
           where p.oid in ('app.fill_dish_costs(uuid, date, date)'::regprocedure,
                           'app.nightly_dish_cost_range(uuid, int)'::regprocedure)
             and (has_function_privilege('authenticated', p.oid, 'execute') or has_function_privilege('anon', p.oid, 'execute'))),
          0::bigint, 'clients cannot call it');

-- arguments ----------------------------------------------------------------------------------
select throws_ok($$select app.fill_dish_costs('03299e41-28bd-5779-bcc6-0e5e76580fad', '2026-09-11', '2026-10-12')$$,
                 '22023', null, 'one call covers at most 31 days');
select lives_ok($$select app.fill_dish_costs('03299e41-28bd-5779-bcc6-0e5e76580fad', '2026-09-12', '2026-10-12')$$,
                '31 days is fine');
select throws_ok($$select app.nightly_dish_cost_range('03299e41-28bd-5779-bcc6-0e5e76580fad', 0)$$,
                 '22023', null, 'the window is at least one day');
select throws_ok($$select app.nightly_dish_cost_range('03299e41-28bd-5779-bcc6-0e5e76580fad', 401)$$,
                 '22023', null, 'and at most 400');
select is((select row(r.from_date, r.to_date)::text from app.nightly_dish_cost_range(:TENANT, 2) r),
          row(date '2026-10-11', date '2026-10-12')::text, 'yesterday and today by default');
select is((select row(r.from_date, r.to_date)::text from app.nightly_dish_cost_range(gen_random_uuid(), 2) r),
          row(null::date, null::date)::text, 'a tenant without locations has nothing to cost');

-- same rows as the engine, insert only -------------------------------------------------------
delete from public.dish_cost_snapshot where tenant_id = :TENANT;
create temp table filled as
  select s.id, s.menu_item_id, s.location_id, s.date, s.cost, s.price_net, s.margin, s.food_cost_pct, s.confidence
  from public.dish_cost_snapshot s where false;
select ok(app.fill_dish_costs(:TENANT, '2026-10-11', '2026-10-12') > 0, 'the fill writes the seed''s two days');
insert into filled
  select s.id, s.menu_item_id, s.location_id, s.date, s.cost, s.price_net, s.margin, s.food_cost_pct, s.confidence
  from public.dish_cost_snapshot s where s.tenant_id = :TENANT;
select is(app.fill_dish_costs(:TENANT, '2026-10-11', '2026-10-12'), 0, 'a rerun writes nothing');
select bag_eq($$select id from public.dish_cost_snapshot where tenant_id = '03299e41-28bd-5779-bcc6-0e5e76580fad'$$,
              'select id from filled', 'and keeps every row id');
select is(app.compute_dish_costs(:TENANT, '2026-10-11', '2026-10-12'), (select count(*)::int from filled),
          'the engine writes as many rows');
select bag_eq($$select menu_item_id, location_id, date, cost, price_net, margin, food_cost_pct, confidence
                from public.dish_cost_snapshot where tenant_id = '03299e41-28bd-5779-bcc6-0e5e76580fad'$$,
              'select menu_item_id, location_id, date, cost, price_net, margin, food_cost_pct, confidence from filled',
              'with the same values');

select * from finish();
rollback;
