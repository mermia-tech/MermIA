-- MR-25: costing engine rules on the El Güero seed (dish values are checked in
-- apps/api/tests/costing against fixtures/el_guero/expected.json).
begin;
select * from no_plan();

create temp table t as select id from public.tenant;
create temp table pastor as
select m.id as item, r.id as recipe from public.menu_item m join public.recipe r on r.menu_item_id = m.id where m.external_id = 'P001';
create temp table salsa as select r.id as recipe from public.recipe r where r.produces_ingredient_id is not null;

-- privileges ---------------------------------------------------------------------------------
select ok(has_function_privilege('service_role', 'app.compute_dish_costs(uuid, date, date)', 'execute'), 'the backend recomputes costs');
select ok(not has_function_privilege('authenticated', 'app.compute_dish_costs(uuid, date, date)', 'execute'), 'clients cannot');
select ok(not has_function_privilege('anon', 'app.compute_dish_costs(uuid, date, date)', 'execute'), 'nor can anon');

-- recipe structure (MR-53 item 6) --------------------------------------------------------------
select throws_ok($$insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base)
                   select (select id from t), recipe, recipe, 1 from salsa$$, '23514', null, 'a recipe cannot use itself');
select throws_ok($$insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base)
                   select (select id from t), (select recipe from salsa), recipe, 1 from pastor$$, '23514', null,
                 'a dish recipe cannot be a sub-recipe');
-- a second sub-recipe that uses the salsa; then the salsa using it is a cycle
insert into public.ingredient (id, tenant_id, name, base_unit) values ('dddddddd-0000-7000-8000-0000000000c1', (select id from t), 'Base de prueba', 'g');
insert into public.recipe (id, tenant_id, produces_ingredient_id, recipe_version, yield_qty, status)
values ('dddddddd-0000-7000-8000-0000000000c2', (select id from t), 'dddddddd-0000-7000-8000-0000000000c1', 1, 1000, 'confirmed');
insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base)
values ((select id from t), 'dddddddd-0000-7000-8000-0000000000c2', (select recipe from salsa), 100);
select throws_ok($$insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base)
                   select (select id from t), recipe, 'dddddddd-0000-7000-8000-0000000000c2', 1 from salsa$$, '23514', null,
                 'two sub-recipes cannot use each other');
select lives_ok($$insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base)
                  select (select id from t), recipe, 'dddddddd-0000-7000-8000-0000000000c2', 10 from pastor$$,
                'a dish may use a sub-recipe that uses another');

-- snapshots ----------------------------------------------------------------------------------
select is(app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12'), 30, 'the 15 costed dishes at 2 locations');
select is((select count(*) from public.dish_cost_snapshot where date = '2026-10-12' and margin <> price_net - cost), 0::bigint, 'margin = net price - cost');
select is((select count(*) from public.dish_cost_snapshot where date = '2026-10-12'
           and food_cost_pct <> round(100.0 * cost / price_net, 4)), 0::bigint, 'food cost % = cost / net price');
select is((select string_agg(distinct confidence::text, ',') from public.dish_cost_snapshot where date = '2026-10-12'), 'estimated',
          'seed prices are older than 30 days: estimated, never confirmed');
select is(app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12'), 30, 'recomputing rewrites, never duplicates');
select is((select count(*) from public.dish_cost_snapshot where date = '2026-10-12'), 30::bigint, 'still 30 rows');

-- a fresh CFDI price for every ingredient of a confirmed recipe makes the dish confirmed
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
select distinct (select id from t), rl.ingredient_id, (select unit_price_net from app.price_of_record(rl.ingredient_id, '2026-10-12')),
       '2026-10-12'::date, 'cfdi'::app.ingredient_price_source
from public.recipe_line rl where rl.recipe_id in ((select recipe from pastor), (select recipe from salsa)) and rl.ingredient_id is not null;
delete from public.recipe_line where recipe_id = (select recipe from pastor) and sub_recipe_id = 'dddddddd-0000-7000-8000-0000000000c2';
select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12');
select is((select string_agg(distinct s.confidence::text, ',') from public.dish_cost_snapshot s
           where s.menu_item_id = (select item from pastor) and s.date = '2026-10-12'), 'confirmed',
          'fresh CFDI prices on confirmed recipes (dish and salsa) give confirmed');
select is((select cost from public.dish_cost_snapshot s join public.location l on l.id = s.location_id
           where s.menu_item_id = (select item from pastor) and s.date = '2026-10-12' and l.name = 'Centro'), 1840::bigint,
          'same prices, same cost');

-- source priority on the same day: the CFDI wins over a manual price
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
select (select id from t), rl.ingredient_id, 999, '2026-10-12'::date, 'manual'::app.ingredient_price_source
from public.recipe_line rl where rl.recipe_id = (select recipe from pastor) and rl.ingredient_id is not null limit 1;
select is((select source::text from app.price_of_record((select rl.ingredient_id from public.recipe_line rl
           where rl.recipe_id = (select recipe from pastor) and rl.ingredient_id is not null limit 1), '2026-10-12')), 'cfdi',
          'on the same day a CFDI beats a manual price');

-- a dish with an unpriced ingredient gets no snapshot (missing, flagged by the RPCs)
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base)
select (select id from t), recipe, 'dddddddd-0000-7000-8000-0000000000c1', 5 from pastor;
select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12');
select is((select count(*) from public.dish_cost_snapshot where menu_item_id = (select item from pastor) and date = '2026-10-12'), 0::bigint,
          'an unpriced line leaves the dish without a cost');
select is((select count(*) from public.dish_cost_snapshot where date = '2026-10-12'), 28::bigint, 'the other dishes keep theirs');
select throws_ok($$select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-01')$$, '22023', null, 'a reversed range');

-- skeptic findings ----------------------------------------------------------------------------
delete from public.recipe_line where recipe_id = (select recipe from pastor) and ingredient_id = 'dddddddd-0000-7000-8000-0000000000c1';
-- a newer benchmark price never beats a real one (03 C.4)
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
select distinct (select id from t), rl.ingredient_id, 9999, '2026-10-12'::date, 'benchmark'::app.ingredient_price_source
from public.recipe_line rl where rl.recipe_id = (select recipe from pastor) and rl.ingredient_id is not null;
select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12');
select is((select s.cost from public.dish_cost_snapshot s join public.location l on l.id = s.location_id
           where s.menu_item_id = (select item from pastor) and s.date = '2026-10-12' and l.name = 'Centro'), 1840::bigint,
          'a newer benchmark price does not override the cost of record');
-- an undated draft revision never overrides the confirmed recipe
insert into public.recipe (id, tenant_id, menu_item_id, recipe_version, yield_qty, status)
select 'dddddddd-0000-7000-8000-0000000000d1', (select id from t), item, 99, 1, 'draft' from pastor;
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base)
select (select id from t), 'dddddddd-0000-7000-8000-0000000000d1', rl.ingredient_id, rl.qty_base * 3
from public.recipe_line rl where rl.recipe_id = (select recipe from pastor) and rl.ingredient_id is not null;
select is(app.recipe_of_record((select item from pastor), null, '2026-09-01'), (select recipe from pastor),
          'a draft never overrides a confirmed recipe');
delete from public.recipe_line where recipe_id = 'dddddddd-0000-7000-8000-0000000000d1';
delete from public.recipe where id = 'dddddddd-0000-7000-8000-0000000000d1';
-- a recipe for 4 portions costs one portion
update public.recipe r set yield_qty = 4 where r.id = (select recipe from pastor);
update public.recipe_line rl set qty_base = rl.qty_base * 4 where rl.recipe_id = (select recipe from pastor);
select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12');
select is((select s.cost from public.dish_cost_snapshot s join public.location l on l.id = s.location_id
           where s.menu_item_id = (select item from pastor) and s.date = '2026-10-12' and l.name = 'Centro'), 1840::bigint,
          'a 4-portion recipe with 4x the quantities costs the same per portion');
-- a near-free item does not abort the recompute
update public.menu_item_price p set price_gross = 100 where p.menu_item_id = (select item from pastor);
select lives_ok($$select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12')$$, 'a $1 dish does not abort the recompute');
select is((select count(*) from public.dish_cost_snapshot where date = '2026-10-12' and menu_item_id = (select item from pastor)
           and food_cost_pct is null), 2::bigint, 'its food cost % is unknown (null), not an error');
select is((select count(*) from public.dish_cost_snapshot where date = '2026-10-12'), 30::bigint, 'and every dish is still costed');
-- a recipe used as a sub-recipe cannot become a dish recipe
select throws_ok($$update public.recipe set produces_ingredient_id = null, menu_item_id = (select item from pastor)
                   where id = (select recipe from salsa)$$, '23514', null, 'a sub-recipe in use keeps producing an ingredient');

-- review on #62 ----------------------------------------------------------------------------------
-- the backend role runs the engine (invoker rights: it needs the helpers too)
select ok(has_function_privilege('service_role', 'app.recipe_cost(uuid, date, int)', 'execute')
          and has_function_privilege('service_role', 'app.recipe_of_record(uuid, uuid, date)', 'execute')
          and has_function_privilege('service_role', 'app.price_of_record(uuid, date)', 'execute'), 'service_role runs the helpers');
select ok(not has_function_privilege('authenticated', 'app.recipe_cost(uuid, date, int)', 'execute'), 'clients do not');
create function pg_temp.as_service_role() returns int language plpgsql as $$
declare n int;
begin
  execute 'set local role service_role';
  select app.compute_dish_costs((select id from public.tenant limit 1), '2026-10-11', '2026-10-11') into n;
  reset role;
  return n;
end $$;
select is(pg_temp.as_service_role(), 30, 'compute_dish_costs runs as service_role');

-- a cycle that closes only through another version of a recipe (the costing follows the
-- ingredient a sub-recipe produces, so the guard does too)
insert into public.ingredient (id, tenant_id, name, base_unit) values ('dddddddd-0000-7000-8000-0000000000e1', (select id from t), 'Base X', 'g');
insert into public.recipe (id, tenant_id, produces_ingredient_id, recipe_version, yield_qty, status)
values ('dddddddd-0000-7000-8000-0000000000e2', (select id from t), 'dddddddd-0000-7000-8000-0000000000e1', 1, 100, 'confirmed');
insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base)
values ((select id from t), 'dddddddd-0000-7000-8000-0000000000e2', (select recipe from salsa), 10);
insert into public.recipe (id, tenant_id, produces_ingredient_id, recipe_version, yield_qty, status)
select 'dddddddd-0000-7000-8000-0000000000e3', (select id from t), r.produces_ingredient_id, 2, r.yield_qty, 'confirmed'
from public.recipe r where r.id = (select recipe from salsa);
select throws_ok($$insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base)
                   values ((select id from t), 'dddddddd-0000-7000-8000-0000000000e3', 'dddddddd-0000-7000-8000-0000000000e2', 5)$$,
                 '23514', null, 'salsa v2 using a base made from salsa v1 is a cycle');

-- 8% IVA (border zone): net = gross - IVA at that rate
update public.menu_item_price p set tax_rate = 0.08
where p.menu_item_id = (select item from pastor) and p.location_id = (select id from public.location where name = 'Centro');
select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12');
select is((select s.price_net from public.dish_cost_snapshot s join public.location l on l.id = s.location_id
           where s.menu_item_id = (select item from pastor) and s.date = '2026-10-12' and l.name = 'Centro'),
          (select p.price_gross - round(p.price_gross * 0.08 / 1.08) from public.menu_item_price p join public.location l on l.id = p.location_id
           where p.menu_item_id = (select item from pastor) and l.name = 'Centro' and p.effective_from <= '2026-10-12'
             and (p.effective_to is null or p.effective_to >= '2026-10-12') order by p.effective_from desc limit 1)::bigint,
          'a location with 8% IVA takes 8% out of the menu price');

-- confidence edges: a nota marked confirmed counts; a price exactly 30 days old does not
update public.recipe_line rl set qty_base = rl.qty_base / 4 where rl.recipe_id = (select recipe from pastor);
update public.recipe set yield_qty = 1 where id = (select recipe from pastor);
delete from public.ingredient_price p where p.effective_from = '2026-10-12';
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source, confidence)
select distinct (select id from t), rl.ingredient_id, (select unit_price_net from app.price_of_record(rl.ingredient_id, '2026-10-12')),
       '2026-10-12'::date, 'nota'::app.ingredient_price_source, 'confirmed'
from public.recipe_line rl where rl.recipe_id in ((select recipe from pastor), (select recipe from salsa)) and rl.ingredient_id is not null;
select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12');
select is((select string_agg(distinct confidence::text, ',') from public.dish_cost_snapshot
           where menu_item_id = (select item from pastor) and date = '2026-10-12'), 'confirmed', 'a nota marked confirmed counts as confirmed');
select app.compute_dish_costs((select id from t), '2026-11-11', '2026-11-11');
select is((select string_agg(distinct confidence::text, ',') from public.dish_cost_snapshot
           where menu_item_id = (select item from pastor) and date = '2026-11-11'), 'estimated', 'a price exactly 30 days old is no longer fresh');

-- a sub-recipe that does not say what it yields cannot cost per unit
update public.recipe set yield_qty = null
where produces_ingredient_id = (select produces_ingredient_id from public.recipe where id = (select recipe from salsa));  -- v1 and v2
select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12');
select is((select count(*) from public.dish_cost_snapshot where menu_item_id = (select item from pastor) and date = '2026-10-12'), 0::bigint,
          'a sub-recipe without yield_qty leaves the dish uncosted');

-- an inactive item is not costed
update public.menu_item set is_active = false where external_id = 'P002';
select app.compute_dish_costs((select id from t), '2026-10-12', '2026-10-12');
select is((select count(*) from public.dish_cost_snapshot s join public.menu_item m on m.id = s.menu_item_id
           where m.external_id = 'P002' and s.date = '2026-10-12'), 0::bigint, 'an inactive item is not costed');
select throws_ok($$select app.compute_dish_costs((select id from t), '2025-01-01', '2026-02-05')$$, '22023', null, 'more than 400 days');

select * from finish();
rollback;
