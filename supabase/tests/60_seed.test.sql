-- Layer: data. The fixture restaurant in supabase/seed.sql (MR-12; 08 C7, 13 H3) loads and holds
-- the figures the eval and the RPC tests rely on. Regenerate with `uv run python -m mermia_fixtures`.
begin;
select * from no_plan();

create temp table t as select id from public.tenant where name = 'Taquería El Güero';
create temp table l as
select x.name, x.id from public.location x join t on t.id = x.tenant_id;

select is((select count(*) from t), 1::bigint, 'the fixture tenant is loaded');
select is((select count(*) from l), 2::bigint, 'it has two locations');
select is((select count(*) from public.daily_sales_agg d join t on t.id = d.tenant_id), 112::bigint,
          'one daily row per location and day for 8 weeks');
select is((select count(*) from public.item_sales_agg i join t on t.id = i.tenant_id), 4592::bigint,
          'one item row per location, day and menu item');

-- 13 H3 examples 1 and 2: Centro's last week and the week before
select is((select sum(net) from public.item_sales_agg i join l on l.id = i.location_id
           where l.name = 'Centro' and i.period_from between '2026-10-05' and '2026-10-11'),
          18432050::numeric, 'Centro sold $184,320.50 in 2026-10-05..11 (item grain)');
select is((select sum(net_sales) from public.daily_sales_agg d join l on l.id = d.location_id
           where l.name = 'Centro' and d.business_date between '2026-10-05' and '2026-10-11'),
          18432050::numeric, 'Centro sold $184,320.50 in 2026-10-05..11 (daily grain)');
select is((select sum(net_sales) from public.daily_sales_agg d join l on l.id = d.location_id
           where l.name = 'Centro' and d.business_date between '2026-09-28' and '2026-10-04'),
          17190500::numeric, 'Centro sold $171,905.00 in 2026-09-28..10-04');

select is((select count(*) from public.daily_sales_agg d
           join (select location_id, period_from, sum(net) as net from public.item_sales_agg
                 group by 1, 2) i on i.location_id = d.location_id and i.period_from = d.business_date
           join t on t.id = d.tenant_id
           where i.net <> d.net_sales), 0::bigint,
          'every day''s net_sales equals the sum of its item nets');
select is((select count(*) from public.daily_sales_agg d join t on t.id = d.tenant_id
           where d.payment_mix->>'cash' is null
              or ((d.payment_mix->>'cash')::bigint + (d.payment_mix->>'card')::bigint
                  + (d.payment_mix->>'transfer')::bigint) <> d.net_sales), 0::bigint,
          'every day''s payment mix adds up to its net_sales');

-- 13 H3 example 7: the cancellation-heavy Saturday is the worst day by far
select is((select d.business_date from public.daily_sales_agg d join l on l.id = d.location_id
           order by d.cancellations_count desc limit 1), '2026-10-10'::date,
          'Saturday 2026-10-10 has the most cancellations');

-- 13 H3 example 4: tacos al pastor cost $18.40 from recipe and prices in effect on 2026-10-12.
-- cost = sum(qty * price per base unit * 100 / yield), sub-recipes per unit of their yield;
-- rounded once, half away from zero. Prices are kept per day: today (10-12) for the dish
-- cost, yesterday (10-11) for yesterday's food cost.
create temp table price_on as
select d.day, p.ingredient_id, p.unit_price_net
from (values ('2026-10-11'::date), ('2026-10-12'::date)) d(day)
join public.ingredient_price p on p.effective_from <= d.day and (p.effective_to is null or p.effective_to >= d.day)
join t on t.id = p.tenant_id;
create temp table salsa_per_g as
select pr.day, r.id as recipe_id, sum(rl.qty_base * pr.unit_price_net * 100 / i.default_yield_pct) / r.yield_qty as cost
from public.recipe r
join public.recipe_line rl on rl.recipe_id = r.id
join public.ingredient i on i.id = rl.ingredient_id
join price_on pr on pr.ingredient_id = i.id
where r.produces_ingredient_id is not null
group by pr.day, r.id, r.yield_qty;
select is((
  select round(100 * sum(case
    when rl.sub_recipe_id is not null then rl.qty_base * s.cost
    else rl.qty_base * pr.unit_price_net * 100 / i.default_yield_pct end))
  from public.menu_item m
  join public.recipe r on r.menu_item_id = m.id
  join public.recipe_line rl on rl.recipe_id = r.id
  left join public.ingredient i on i.id = rl.ingredient_id
  left join price_on pr on pr.ingredient_id = rl.ingredient_id and pr.day = '2026-10-12'
  left join salsa_per_g s on s.recipe_id = rl.sub_recipe_id and s.day = '2026-10-12'
  join t on t.id = m.tenant_id
  where m.external_id = 'P001'), 1840::numeric, 'tacos al pastor cost $18.40 today');
-- 13 H3 example 6 (food cost yesterday), recomputed from the rows: for Centro on 2026-10-11,
-- numerator = units x dish cost (dish cost rounded once per dish) over items with a recipe,
-- denominator = those items' net (gross - discount) less the IVA inside it.
-- dish cost with the prices in effect on 2026-10-11, the day being measured
create temp table dish_cost_on as
select m.id as menu_item_id, round(100 * sum(case
    when rl.sub_recipe_id is not null then rl.qty_base * s.cost
    else rl.qty_base * pr.unit_price_net * 100 / i.default_yield_pct end)) as cost
from public.menu_item m
join public.recipe r on r.menu_item_id = m.id
join public.recipe_line rl on rl.recipe_id = r.id
left join public.ingredient i on i.id = rl.ingredient_id
left join price_on pr on pr.ingredient_id = rl.ingredient_id and pr.day = '2026-10-11'
left join salsa_per_g s on s.recipe_id = rl.sub_recipe_id and s.day = '2026-10-11'
join t on t.id = m.tenant_id
group by m.id;
create temp table yesterday as
select sum(a.units * c.cost) as cost, sum(a.net) as net
from public.item_sales_agg a
join dish_cost_on c on c.menu_item_id = a.menu_item_id
join l on l.id = a.location_id
where l.name = 'Centro' and a.period_from = '2026-10-11';
select is((select cost from yesterday), 718946::numeric, 'food cost numerator: $7,189.46 of recipe cost');
select is((select net - round(net * 16 / 116) from yesterday), 1919397::numeric,
          'denominator: $19,193.97 of covered net sales without IVA');
select is((select round(cost * 100 / (net - round(net * 16 / 116)), 1) from yesterday), 37.5,
          'Centro food cost on 2026-10-11 is 37.5 %');

select is((select p.price_gross from public.menu_item_price p join public.menu_item m on m.id = p.menu_item_id
           join l on l.id = p.location_id where l.name = 'Centro' and m.external_id = 'P001'),
          6500::bigint, 'and sell for $65.00 at Centro');

-- the two price jumps (08 C7): pastor meat and avocado each have a before and an after price
select is((select count(*) from public.ingredient_price p join public.ingredient i on i.id = p.ingredient_id
           join t on t.id = i.tenant_id where i.name in ('Carne al pastor (adobada)', 'Aguacate Hass')),
          4::bigint, 'two ingredients have a price jump');

-- 13 H3 example 7: the cancellations have waiters. Ticket grain, cancelled, every line voided
-- by a waiter of the same location, and they add up to the day's daily row.
create temp table cancelled as
select st.* from public.sale_ticket st join l on l.id = st.location_id
where l.name = 'Centro' and st.business_date = '2026-10-10' and st.status = 'cancelled';
select is((select count(*) from cancelled), 17::bigint, 'Centro has 17 cancelled tickets on 2026-10-10');
select is((select sum(total) from cancelled),
          (select d.cancellations_amount::numeric from public.daily_sales_agg d join l on l.id = d.location_id
           where l.name = 'Centro' and d.business_date = '2026-10-10'),
          'they add up to the day''s cancellations_amount');
select is((select count(*) from cancelled c
           where c.total <> (select sum(sl.net) from public.sale_line sl where sl.ticket_id = c.id)
              or c.tax <> (select sum(sl.tax) from public.sale_line sl where sl.ticket_id = c.id)
              or c.subtotal <> c.total - c.tax), 0::bigint,
          'ticket total = sum of line net, tax = sum of line tax, subtotal = total - tax (fixtures/README.md)');
select is((select count(*) from public.sale_line sl join cancelled c on c.id = sl.ticket_id
           left join public.staff s on s.id = sl.voided_by and s.location_id = sl.location_id
           where not sl.is_void or s.id is null or sl.void_reason is null), 0::bigint,
          'every line is voided, with a reason, by a waiter of that location');
select is((select s.display_name from cancelled c join public.staff s on s.id = c.staff_id
           group by s.display_name order by count(*) desc limit 1), 'Pepe',
          'Pepe cancelled the most');
select is((select count(*) from public.sale_ticket st join t on t.id = st.tenant_id where st.status = 'paid'),
          0::bigint, 'no paid tickets: sales stay at item and daily grain, so nothing counts twice');

-- the seed's own memberships work with RLS: claims built from the Centro manager's membership
-- see Centro's rows and none of Polanco's
select set_config('request.jwt.claims', (
  select json_build_object('role', 'authenticated', 'tenant_id', m.tenant_id, 'app_role', m.role,
                           'location_ids', to_json(m.location_ids))::text
  from public.membership m join public.app_user u on u.id = m.user_id join t on t.id = m.tenant_id
  where u.name = 'Lupita'), true);
create temp table centro_id as select id from l where name = 'Centro';
grant select on centro_id to authenticated;
set local role authenticated;
select is((select count(*) from public.item_sales_agg where location_id <> (select id from centro_id)),
          0::bigint, 'the Centro manager sees no other location');
select is((select count(*) from public.item_sales_agg where location_id = (select id from centro_id)),
          2296::bigint, 'and all of Centro''s item rows');
reset role;

select * from finish();
rollback;
