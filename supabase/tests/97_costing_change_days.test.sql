-- MR-86: the change-day engine writes the same dish_cost_snapshot rows as MR-25's day-by-day
-- engine (kept below as app.compute_dish_costs_reference, inside this test's transaction only), on
-- the seed and on a synthetic tenant built to move every input; a tap or backfill rewrites only the
-- dishes its change can move; a tenant in two time zones recomputes each location's own today.
begin;
select * from no_plan();

\set TENANT '''03299e41-28bd-5779-bcc6-0e5e76580fad'''
\set OWNER '''eb52f6ad-4d75-5b06-9881-9f68f4fb05a0'''
\set PASTOR '''f496f051-9f85-5f8a-a4b6-c1a814d37c73'''
\set CARNE '''356dfff4-d912-542b-b8b0-8ae42068eb7e'''
\set SYN '''cccccccc-0000-7000-8000-000000000001'''

-- privileges ---------------------------------------------------------------------------------
select ok(has_function_privilege('service_role', 'app.compute_dish_costs_for(uuid, uuid[], date, date)', 'execute'),
          'the backend recomputes chosen dishes');
select is((select count(*) from pg_proc p
           where p.oid in ('app.compute_dish_costs_for(uuid, uuid[], date, date)'::regprocedure,
                           'app.dish_cost_change_days(uuid, date, date)'::regprocedure,
                           'app.dish_cost_items_using(uuid, uuid)'::regprocedure,
                           'app.dish_cost_items(public.pending_change)'::regprocedure,
                           'app.tenant_days(uuid)'::regprocedure,
                           'app.recompute_after_change(uuid, date, uuid[])'::regprocedure)
             and (has_function_privilege('authenticated', p.oid, 'execute') or has_function_privilege('anon', p.oid, 'execute'))),
          0::bigint, 'clients cannot call the new functions');

-- MR-25's engine, verbatim, as the reference ----------------------------------------------------
create function app.compute_dish_costs_reference(tenant uuid, from_date date, to_date date) returns int
language plpgsql set search_path = ''
as $$
declare
  d date;
  item record;
  c record;
  written int := 0;
  n int;
begin
  if from_date > to_date or to_date - from_date >= 400 then  -- at most 400 days
    raise exception 'invalid range % .. %', from_date, to_date using errcode = '22023';
  end if;
  -- one recompute per tenant at a time (a price job and a batch job may overlap)
  perform pg_advisory_xact_lock(hashtextextended('dish_cost_snapshot:' || tenant::text, 0));
  delete from public.dish_cost_snapshot s
  where s.tenant_id = tenant and s.date between from_date and to_date;

  for d in select g::date from generate_series(from_date, to_date, interval '1 day') g loop
    for item in
      select m.id as menu_item_id, app.recipe_of_record(m.id, null, d) as recipe_id
      from public.menu_item m
      where m.tenant_id = tenant and m.is_active  -- any kind with a recipe (dish, drink, modifier, combo)
    loop
      continue when item.recipe_id is null;
      begin
        select * into c from app.recipe_cost(item.recipe_id, d);
      exception when sqlstate '54001' then
        continue;  -- a recipe nested too deep (a cycle that slipped in) costs this dish nothing
      end;
      continue when not c.complete;
      insert into public.dish_cost_snapshot
        (tenant_id, menu_item_id, location_id, date, cost, price_net, margin, food_cost_pct, confidence)
      select tenant, item.menu_item_id, mp.location_id, d, x.cost, x.price_net, x.price_net - x.cost,
             -- numeric(7,4): a near-free item (cost over ~10x its price) has no food cost %; the
             -- rounded value is tested, since 999.99996 rounds to 1000.0000
             case when x.price_net > 0 and round(100.0 * x.cost / x.price_net, 4) < 1000
                  then round(100.0 * x.cost / x.price_net, 4) end,
             (case when c.firm then 'confirmed' else 'estimated' end)::app.cost_confidence
      from (
        select distinct on (p.location_id) p.location_id, p.price_gross, p.tax_rate
        from public.menu_item_price p
        where p.tenant_id = tenant and p.menu_item_id = item.menu_item_id
          and p.effective_from <= d and (p.effective_to is null or p.effective_to >= d)
        order by p.location_id, p.effective_from desc, p.created_at desc
      ) mp
      cross join lateral (
        select round(c.cost)::bigint as cost,
               (mp.price_gross - round(mp.price_gross * coalesce(mp.tax_rate, 0.16) / (1 + coalesce(mp.tax_rate, 0.16))))::bigint
                 as price_net
      ) x;
      get diagnostics n = row_count;
      written := written + n;
    end loop;
  end loop;
  return written;
end
$$;

-- every snapshot column but the row's id and timestamps
create function pg_temp.rows(tenant uuid, from_date date, to_date date) returns setof text language sql stable as $$
  select row(s.menu_item_id, s.location_id, s.date, s.cost, s.price_net, s.margin, s.currency, s.food_cost_pct,
             s.confidence)::text
  from public.dish_cost_snapshot s where s.tenant_id = tenant and s.date between from_date and to_date
$$;
-- run both engines on the same range; keep the reference's rows and count
create temp table ref (tenant uuid, r text);
create temp table ref_n (tenant uuid, n int);
create function pg_temp.reference(tenant uuid, from_date date, to_date date) returns void language sql as $$
  insert into ref_n values (tenant, app.compute_dish_costs_reference(tenant, from_date, to_date));
  insert into ref select tenant, x from pg_temp.rows(tenant, from_date, to_date) x;
$$;

-- the seed: every day from before its first price to past its last ------------------------------
set local app.today = '2026-10-12';
select pg_temp.reference(:TENANT, '2026-07-01', '2026-11-30');
select is(app.compute_dish_costs(:TENANT, '2026-07-01', '2026-11-30'), (select n from ref_n where tenant = :TENANT),
          'seed: the same number of snapshots');
select bag_eq(format('select * from pg_temp.rows(%L, ''2026-07-01'', ''2026-11-30'')', :TENANT),
              format('select r from ref where tenant = %L', :TENANT), 'seed: the same rows, value for value');
select cmp_ok((select n from ref_n where tenant = :TENANT), '>', 0, 'seed: snapshots were written');

-- a synthetic tenant that moves every input ------------------------------------------------------
-- 3 locations; 25 ingredients with dated prices from every source (same-day ties, benchmark-only,
-- effective_to, notas confirmed or not, CFDIs every 45 days for the confirmed grade), one never
-- priced; a sub-recipe in 4 versions (dated, a draft, an end date, one without a yield) that uses
-- another sub-recipe; 12 dishes with dated recipe versions and drafts, menu prices that change per
-- location with end dates and unknown tax rates, a near-free dish, a dish missing a location, an
-- inactive dish and one without a recipe.
select setseed(0.86);
insert into public.tenant (id, name) values (:SYN, 'Sintética');
insert into public.location (id, tenant_id, name, timezone)
select ('cccccccc-0000-7000-8000-0000000001' || lpad(g::text, 2, '0'))::uuid, :SYN, 'Local ' || g, 'America/Mexico_City'
from generate_series(1, 3) g;
create temp table syn_loc as select id from public.location where tenant_id = :SYN;
insert into public.ingredient (id, tenant_id, name, base_unit, default_yield_pct)
select ('cccccccc-0000-7000-8000-0000000002' || lpad(g::text, 2, '0'))::uuid, :SYN, 'Insumo ' || g, 'g',
       case when g % 5 = 0 then 80 else 100 end
from generate_series(1, 27) g;
create function pg_temp.ing(n int) returns uuid language sql immutable as $$
  select ('cccccccc-0000-7000-8000-0000000002' || lpad(n::text, 2, '0'))::uuid
$$;
-- ingredients 1-24 bought; 25 never priced; 26 and 27 made by sub-recipes
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, effective_to, source, confidence)
select :SYN, pg_temp.ing(g), round((0.02 + random() * 0.3)::numeric, 6), f,
       case when random() < 0.15 then f + (random() * 60)::int end,
       (array['cfdi', 'nota', 'sr_import', 'manual', 'benchmark'])[1 + floor(random() * 5)::int]::app.ingredient_price_source,
       case when random() < 0.5 then 'confirmed' end
from generate_series(2, 24) g, generate_series(1, 9) k,
     lateral (select date '2025-09-01' + (random() * 520)::int + k - k as f) x;
-- same-day ties between sources, and a benchmark-only ingredient
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
select :SYN, pg_temp.ing(g), 0.11 + g / 1000.0, date '2026-02-14', s::app.ingredient_price_source
from generate_series(2, 6) g, unnest(array['cfdi', 'manual', 'sr_import']) s;
delete from public.ingredient_price where ingredient_id = pg_temp.ing(24) and source <> 'benchmark';
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
values (:SYN, pg_temp.ing(24), 0.09, '2025-10-01', 'benchmark'), (:SYN, pg_temp.ing(24), 0.12, '2026-05-01', 'benchmark');
-- ingredient 1: a CFDI every 45 days, so its dishes go confirmed and back to estimated
insert into public.ingredient_price (tenant_id, ingredient_id, unit_price_net, effective_from, source)
select :SYN, pg_temp.ing(1), 0.10 + k / 100.0, date '2025-08-01' + 45 * k, 'cfdi' from generate_series(0, 12) k;

-- sub-recipes: 27 (a base) and 26 (a salsa that uses the base)
create function pg_temp.rec(n int) returns uuid language sql immutable as $$
  select ('cccccccc-0000-7000-8000-0000000003' || lpad(n::text, 2, '0'))::uuid
$$;
insert into public.recipe (id, tenant_id, produces_ingredient_id, recipe_version, effective_from, effective_to, yield_qty, status) values
  (pg_temp.rec(1), :SYN, pg_temp.ing(27), 1, null, null, 500, 'confirmed'),
  (pg_temp.rec(2), :SYN, pg_temp.ing(27), 2, '2026-04-10', null, 450, 'confirmed'),
  (pg_temp.rec(3), :SYN, pg_temp.ing(26), 1, null, null, 1000, 'confirmed'),
  (pg_temp.rec(4), :SYN, pg_temp.ing(26), 2, '2026-01-20', '2026-06-30', 900, 'confirmed'),
  (pg_temp.rec(5), :SYN, pg_temp.ing(26), 3, '2026-03-01', null, 800, 'draft'),
  (pg_temp.rec(6), :SYN, pg_temp.ing(26), 4, '2026-08-15', '2026-09-10', null, 'confirmed');
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, sub_recipe_id, qty_base, yield_override_pct) values
  (:SYN, pg_temp.rec(1), pg_temp.ing(2), null, 300, null),
  (:SYN, pg_temp.rec(1), pg_temp.ing(3), null, 250, 90),
  (:SYN, pg_temp.rec(2), pg_temp.ing(4), null, 400, null),
  (:SYN, pg_temp.rec(3), pg_temp.ing(5), null, 600, null),
  (:SYN, pg_temp.rec(3), null, pg_temp.rec(1), 200, null),
  (:SYN, pg_temp.rec(4), pg_temp.ing(6), null, 700, null),
  (:SYN, pg_temp.rec(4), null, pg_temp.rec(2), 150, null),
  (:SYN, pg_temp.rec(5), pg_temp.ing(7), null, 500, null),
  (:SYN, pg_temp.rec(6), pg_temp.ing(8), null, 500, null);

-- dishes 1-12: dish 11 is inactive, dish 12 has no recipe
insert into public.menu_item (id, tenant_id, name, is_active)
select ('cccccccc-0000-7000-8000-0000000004' || lpad(g::text, 2, '0'))::uuid, :SYN, 'Platillo ' || g, g <> 11
from generate_series(1, 12) g;
create function pg_temp.dish(n int) returns uuid language sql immutable as $$
  select ('cccccccc-0000-7000-8000-0000000004' || lpad(n::text, 2, '0'))::uuid
$$;
-- versions: v1 undated and confirmed; v2 dated (some ending); v3 a later draft
insert into public.recipe (id, tenant_id, menu_item_id, recipe_version, effective_from, effective_to, yield_qty, status)
select ('cccccccc-0000-7000-8000-000000005' || lpad(g::text, 2, '0') || v::text)::uuid, :SYN, pg_temp.dish(g), v,
       f.d, case when v = 2 and g % 3 = 0 then f.d + 60 + 10 * g end,
       case when g % 4 = 0 then 2 end,
       case when v = 3 then 'draft' else 'confirmed' end::app.recipe_status
from generate_series(1, 11) g, generate_series(1, 3) v,
     lateral (select case v when 1 then null else date '2025-10-01' + (random() * 400)::int + 0 * g end as d) f
where v = 1 or (v = 2 and g % 2 = 0) or (v = 3 and g % 5 = 0);
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base, yield_override_pct)
select :SYN, r.id, pg_temp.ing(2 + (abs(hashtext(r.id::text || k)) % 23)), 20 + (abs(hashtext(k || r.id::text)) % 200),
       case when k = 1 and r.recipe_version = 2 then 85 end
from public.recipe r, generate_series(1, 3) k
where r.tenant_id = :SYN and r.menu_item_id is not null;
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, sub_recipe_id, qty_base)
select :SYN, r.id, case when n = 1 then pg_temp.ing(1) end, case when n = 2 then pg_temp.rec(3) end, 75
from public.recipe r, generate_series(1, 2) n
where r.tenant_id = :SYN and r.menu_item_id in (pg_temp.dish(1), pg_temp.dish(2), pg_temp.dish(6)) and (n = 1 or r.recipe_version = 1);
-- dish 4's v2 uses the never-priced ingredient (unpriced while it is in effect)
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base)
select :SYN, r.id, pg_temp.ing(25), 10 from public.recipe r where r.menu_item_id = pg_temp.dish(4) and r.recipe_version = 2;
-- dish 7 only uses ingredient 1 (fresh CFDIs make it confirmed now and then)
delete from public.recipe_line where recipe_id in (select id from public.recipe where menu_item_id = pg_temp.dish(7));
insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base)
select :SYN, r.id, pg_temp.ing(1), 100 from public.recipe r where r.menu_item_id = pg_temp.dish(7);

-- menu prices: from 2025 at every location, then dated changes; dish 9 is near-free; dish 5 is
-- missing at the third location; some rows have no tax rate (16 %) or 8 %
insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from, effective_to)
select :SYN, l.id, m.id,
       case when m.id = pg_temp.dish(9) then 10 + k else 4000 + (random() * 9000)::int end,
       case when random() < 0.2 then null when random() < 0.2 then 0.08 else 0.16 end,
       f.d, case when k > 0 and random() < 0.2 then f.d + (random() * 120)::int end
from public.menu_item m, syn_loc l, generate_series(0, 3) k,
     lateral (select case when k = 0 then date '2025-01-01' else date '2025-10-01' + (random() * 420)::int + 0 * k end as d) f
where m.tenant_id = :SYN and not (m.id = pg_temp.dish(5) and l.id = 'cccccccc-0000-7000-8000-000000000103');

-- 400 days that cover all of it
select pg_temp.reference(:SYN, '2025-11-10', '2026-12-14');
select is(app.compute_dish_costs(:SYN, '2025-11-10', '2026-12-14'), (select n from ref_n where tenant = :SYN),
          'synthetic: the same number of snapshots');
select bag_eq(format('select * from pg_temp.rows(%L, ''2025-11-10'', ''2026-12-14'')', :SYN),
              format('select r from ref where tenant = %L', :SYN), 'synthetic: the same rows, value for value');
-- the dataset really moves what it means to move
select ok((select count(distinct confidence) = 2 from public.dish_cost_snapshot where tenant_id = :SYN),
          'synthetic: both confidence grades occur');
select ok(exists (select 1 from public.dish_cost_snapshot where tenant_id = :SYN and food_cost_pct is null),
          'synthetic: a near-free dish has no food cost %');
select ok((select count(distinct cost) > 20 from public.dish_cost_snapshot where tenant_id = :SYN and menu_item_id = pg_temp.dish(1)),
          'synthetic: a dish''s cost moves over the range');
select ok((select count(distinct date) between 1 and 399 from public.dish_cost_snapshot
           where tenant_id = :SYN and menu_item_id = pg_temp.dish(4)), 'synthetic: a dish is unpriced on some days');
select is((select count(*) from public.dish_cost_snapshot where tenant_id = :SYN and menu_item_id in (pg_temp.dish(11), pg_temp.dish(12))),
          0::bigint, 'synthetic: no snapshot for an inactive dish or one without a recipe');
-- a shorter range starting between boundaries gives the same rows as the full one
select app.compute_dish_costs(:SYN, '2026-02-17', '2026-03-03');
select bag_eq(format('select * from pg_temp.rows(%L, ''2026-02-17'', ''2026-03-03'')', :SYN),
              format('select r from ref where tenant = %L and split_part(r, '','', 3) between ''2026-02-17'' and ''2026-03-03''', :SYN),
              'synthetic: a range that starts mid-way gives the same rows');

-- change days ------------------------------------------------------------------------------------
select is((app.dish_cost_change_days(pg_temp.dish(7), '2026-01-01', '2026-03-31'))[1], '2026-01-01'::date, 'change days start on the first day');
select ok((select bool_and(d between '2026-01-01' and '2026-03-31') and count(*) = count(distinct d)
           from unnest(app.dish_cost_change_days(pg_temp.dish(7), '2026-01-01', '2026-03-31')) d),
          'change days are distinct and inside the range');
select ok(app.dish_cost_change_days(pg_temp.dish(7), '2026-01-01', '2026-12-31')
            @> array['2026-01-28'::date, '2026-02-27'::date, '2026-03-14'::date, '2026-04-13'::date],
          'a CFDI starts a change day, and so does the day it turns 30 days old');
select ok(app.dish_cost_change_days(pg_temp.dish(1), '2025-11-10', '2026-12-14')
            @> array['2026-01-20'::date, '2026-07-01'::date, '2026-04-10'::date, '2026-08-15'::date, '2026-09-11'::date],
          'every sub-recipe version boundary, nested ones too, is a change day');

-- affected dishes ----------------------------------------------------------------------------------
select is(app.dish_cost_items_using(:SYN, pg_temp.ing(4)),
          array(select unnest(array[pg_temp.dish(1), pg_temp.dish(2), pg_temp.dish(6)]) union
                select r.menu_item_id from public.recipe_line rl join public.recipe r on r.id = rl.recipe_id
                where rl.ingredient_id = pg_temp.ing(4) and r.menu_item_id is not null order by 1),
          'an ingredient used two sub-recipes down reaches the dishes that use the salsa');
select is(app.dish_cost_items_using(:SYN, pg_temp.ing(25)) @> array[pg_temp.dish(4)], true, 'a direct line counts');
select is(app.dish_cost_items_using(:SYN, 'cccccccc-0000-7000-8000-0000000002ff'), '{}'::uuid[], 'an unused ingredient moves nothing');
select is(app.dish_cost_items_using(:TENANT, pg_temp.ing(4)), '{}'::uuid[], 'nor across tenants');

-- chosen dishes only: the rest keep their rows ------------------------------------------------------
create temp table syn_before as select id, menu_item_id, date from public.dish_cost_snapshot where tenant_id = :SYN;
select cmp_ok(app.compute_dish_costs_for(:SYN, array[pg_temp.dish(7)], '2025-11-10', '2026-12-14'), '>', 0,
              'compute_dish_costs_for rewrites the listed dish');
select is((select count(*) from syn_before b join public.dish_cost_snapshot s on s.id = b.id where b.menu_item_id <> pg_temp.dish(7)),
          (select count(*) from syn_before where menu_item_id <> pg_temp.dish(7)), 'every other dish keeps its rows (same ids)');
select is((select count(*) from syn_before b join public.dish_cost_snapshot s on s.id = b.id where b.menu_item_id = pg_temp.dish(7)),
          0::bigint, 'the listed dish''s rows are new');
select bag_eq(format('select * from pg_temp.rows(%L, ''2025-11-10'', ''2026-12-14'')', :SYN),
              format('select r from ref where tenant = %L', :SYN), 'and the table still matches the reference');
select is(app.compute_dish_costs_for(:SYN, '{}', '2025-11-10', '2026-12-14'), 0, 'an empty list writes nothing');
select is((select count(*) from public.dish_cost_snapshot where tenant_id = :SYN), (select count(*) from syn_before),
          'and deletes nothing');
select throws_ok(format('select app.compute_dish_costs_for(%L, null, ''2025-11-10'', ''2026-12-15'')', :SYN), '22023', null,
                 'at most 400 days, as compute_dish_costs');

-- a tap and its backfill rewrite only the dishes the price can move (seed) ----------------------
set local app.today = '2026-10-12';
select app.compute_dish_costs(:TENANT, '2026-10-01', '2026-10-12');
create temp table seed_before as select id, menu_item_id, date from public.dish_cost_snapshot
where tenant_id = :TENANT and date between '2026-10-01' and '2026-10-12';
create temp table carne_items as select unnest(app.dish_cost_items_using(:TENANT, :CARNE)) as item;
select ok((select count(*) from carne_items) between 1 and (select count(distinct menu_item_id) - 1 from seed_before),
          'the meat is used by some dishes, not all');
select ok(exists (select 1 from carne_items where item = :PASTOR), 'pastor among them');

create function pg_temp.propose(kind text, target_type text, target uuid, payload jsonb) returns uuid language sql as $$
  insert into public.pending_change (tenant_id, kind, target_type, target_id, base_version, payload, proposed_by_user,
                                     proposed_via, expires_at)
  values ('03299e41-28bd-5779-bcc6-0e5e76580fad', kind, target_type, target, app.pending_base_version(kind, target, payload),
          payload, 'eb52f6ad-4d75-5b06-9881-9f68f4fb05a0', 'agent', now() + interval '1 day')
  returning id
$$;
select pg_temp.propose('ingredient_price.set', 'ingredient', :CARNE,
                       '{"unit_price": "0.50", "effective_from": "2026-10-05", "source": "manual"}') as backdated \gset
select is(app.dish_cost_items(p), (select array_agg(item order by item) from carne_items), 'the change names the dishes it moves')
from public.pending_change p where p.id = :'backdated';
select is(app.apply_pending_change(:'backdated', :OWNER) ->> 'code', 'applied', 'a backdated meat price applies');
select is((select count(*) from seed_before b join public.dish_cost_snapshot s on s.id = b.id
           where b.date = '2026-10-12' and b.menu_item_id not in (select item from carne_items)),
          (select count(*) from seed_before where date = '2026-10-12' and menu_item_id not in (select item from carne_items)),
          'the tap leaves today''s snapshots of the other dishes alone');
select is((select count(*) from seed_before b join public.dish_cost_snapshot s on s.id = b.id
           where b.date = '2026-10-12' and b.menu_item_id in (select item from carne_items)), 0::bigint,
          'and rewrites the meat dishes');
select is((select (after ->> 'snapshots')::int from public.audit_log where pending_change_id = :'backdated' and action = 'pending_change.apply'),
          (select count(*)::int from public.dish_cost_snapshot where tenant_id = :TENANT and date = '2026-10-12'
             and menu_item_id in (select item from carne_items)), 'the audit row counts the snapshots of those dishes');
select is(app.backfill_dish_costs(:'backdated', 31) - 'snapshots',
          '{"from": "2026-10-05", "to": "2026-10-11", "next_before": null}'::jsonb, 'the backfill runs as before');
select is((select count(*) from seed_before b join public.dish_cost_snapshot s on s.id = b.id
           where b.menu_item_id not in (select item from carne_items)),
          (select count(*) from seed_before where menu_item_id not in (select item from carne_items)),
          'and leaves the other dishes'' older days alone too');
select is((select count(*) from seed_before b join public.dish_cost_snapshot s on s.id = b.id
           where b.date between '2026-10-05' and '2026-10-11' and b.menu_item_id in (select item from carne_items)), 0::bigint,
          'while the meat dishes are rewritten from the price''s date');
-- what a full recompute would write
create temp table seed_after as select x from pg_temp.rows(:TENANT, '2026-10-01', '2026-10-12') x;
select app.compute_dish_costs_reference(:TENANT, '2026-10-01', '2026-10-12');
select bag_eq(format('select * from pg_temp.rows(%L, ''2026-10-01'', ''2026-10-12'')', :TENANT), 'select x from seed_after',
              'the snapshots after tap and backfill are what a full recompute writes');

-- a menu price moves only its dish ----------------------------------------------------------------
select is(app.dish_cost_items(p), array[:PASTOR]::uuid[], 'a menu price change moves only its dish')
from (select null::uuid as id, :TENANT::uuid as tenant_id, 'menu_item_price.set'::text as kind, :PASTOR::uuid as target_id) x,
     lateral (select (jsonb_populate_record(null::public.pending_change, to_jsonb(x))).*) p;
select is(app.dish_cost_items(p), null::uuid[], 'a batch names no dish (every dish)')
from (select :TENANT::uuid as tenant_id, 'import_batch.approve'::text as kind) x,
     lateral (select (jsonb_populate_record(null::public.pending_change, to_jsonb(x))).*) p;

-- P6: a tenant in two time zones recomputes each location's own today ----------------------------
reset app.today;
update public.location set timezone = case when id = 'cccccccc-0000-7000-8000-000000000102' then 'Pacific/Pago_Pago'
                                           else 'Pacific/Kiritimati' end
where tenant_id = :SYN;  -- UTC-11 and UTC+14: always on different days
select (t).first_day as first_day, (t).last_day as last_day from (select app.tenant_days(:SYN) t) x \gset
select ok(:'last_day'::date - :'first_day'::date between 1 and 2, 'the two locations are on different days');
select is(:'first_day'::date, app.business_today('cccccccc-0000-7000-8000-000000000102'), 'the earliest is Pago Pago''s');
delete from public.dish_cost_snapshot where tenant_id = :SYN and menu_item_id = pg_temp.dish(7) and date >= :'first_day'::date - 3;
select is(app.recompute_after_change(:SYN, :'first_day'::date - 3, array[pg_temp.dish(7)]) -> 'backfill',
          jsonb_build_object('from', :'first_day'::date - 3, 'to', :'first_day'::date - 1, 'requested_from', :'first_day'::date - 3,
                             'capped', false),
          'the backfill ends the day before the earliest today');
select is((select count(*)::int from public.dish_cost_snapshot where tenant_id = :SYN and menu_item_id = pg_temp.dish(7)
           and date >= :'first_day'::date - 3),
          (:'last_day'::date - :'first_day'::date + 1) * 3, 'the tap writes every location''s today, the latest one included');
select is(app.recompute_after_change(:SYN, :'last_day'::date, array[pg_temp.dish(7)]) -> 'backfill', 'null'::jsonb,
          'a change from the latest today leaves nothing to backfill');
select is(app.recompute_after_change(:SYN, :'last_day'::date + 1, array[pg_temp.dish(7)]),
          '{"snapshots": null, "backfill": null}'::jsonb, 'a change after every location''s today is not costed yet');

select * from finish();
rollback;
