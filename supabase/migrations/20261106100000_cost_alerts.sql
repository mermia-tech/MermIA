-- MR-33 (part a): cost alert rules (03 "Alert thresholds"; user decisions U1 and U3 in
-- docs/superpowers/plans/2026-11-06-mr-33-cost-alerts.md). Rules in code, never the LLM: the
-- backend runs app.evaluate_cost_alerts daily and it writes public.alert rows only. It never
-- writes a pending_change, a menu price or a suggestion; price suggestions are part b.
--
-- - Price jump: the price of record of an ingredient a live dish uses changes on a day, and the
--   new price is at least 15 % away from the last price, or at least 8 % away from the 30-day
--   time-weighted average (the price of record on each of the 30 days before). Either direction;
--   a zero price is never a jump. The quoted change is the rule that fired: vs the last price
--   when the 15 % rule does, else vs the average. One definition (app.price_jumps) for the
--   evaluator and api.get_cost_alerts.
-- - Margin breach: a dish's snapshot food cost is above target + 3 pts (U1: 32 % + 3).
-- - Urgent (U3, for a same-day message sent by MR-37/38): a price rise of at least 15 % vs the last
--   price on a top-20 ingredient by spend, or a breach on a top-10 dish by net sales at its
--   location, both over the 30 days to the evaluation day, and only when the evidence is at most
--   7 days old (a catch-up run over old days marks nothing urgent). The top-20 filter applies to
--   urgency only: every jump gets an alert for the weekly report.
-- - Spend is theoretical usage (units sold x recipe of record, through sub-recipes, x price of
--   record): purchases are only partly captured in Phase 1.
-- - Dedupe: one price_jump alert per (tenant, ingredient, day the price started); one
--   margin_breach alert per episode, (tenant, location, dish, first day of the run of breaching
--   snapshots): a breach that persists does not alert again, one that ends and comes back does.
--   `as_of` is that day and `value` the change or food cost on it. Status stays `open` until the
--   owner acts.

-- Alert rows ---------------------------------------------------------------------------------
alter table public.alert
  add column menu_item_id uuid,
  add column ingredient_id uuid,
  add column as_of date,
  add column urgent boolean not null default false,
  add column old_unit_price numeric(20, 6),
  add column new_unit_price numeric(20, 6),
  add column avg_unit_price numeric(20, 6),
  add foreign key (tenant_id, menu_item_id) references public.menu_item (tenant_id, id) on delete restrict,
  add foreign key (tenant_id, ingredient_id) references public.ingredient (tenant_id, id) on delete restrict;

update public.alert set status = 'open' where status is null;
alter table public.alert
  alter column status set default 'open',
  alter column status set not null,
  add constraint alert_rule_known check (rule in ('price_jump', 'margin_breach')),
  add constraint alert_status_known check (status in ('open', 'acknowledged', 'dismissed')),
  -- coalesce: a null comparison must fail the check, not pass it
  add constraint alert_shape check (coalesce(
    as_of is not null and value is not null and threshold is not null and (
      (rule = 'price_jump' and ingredient_id is not null and menu_item_id is null and location_id is null
        and old_unit_price > 0 and new_unit_price > 0 and avg_unit_price > 0)
      or (rule = 'margin_breach' and menu_item_id is not null and location_id is not null and ingredient_id is null
        and old_unit_price is null and new_unit_price is null and avg_unit_price is null)), false));

create unique index alert_price_jump_key on public.alert (tenant_id, ingredient_id, as_of) where rule = 'price_jump';
create unique index alert_margin_breach_key on public.alert (tenant_id, location_id, menu_item_id, as_of)
  where rule = 'margin_breach';
create index alert_menu_item_idx on public.alert (tenant_id, menu_item_id);
create index alert_ingredient_idx on public.alert (tenant_id, ingredient_id);
select app.tag('public.alert', 'unit=pesos_per_base_unit', array['old_unit_price', 'new_unit_price', 'avg_unit_price']);
comment on column public.alert.rule is 'price_jump | margin_breach (alert_rule_known)';
comment on column public.alert.status is 'open | acknowledged | dismissed (alert_status_known)';
comment on column public.alert.value is
  'percent points: the price change that fired (price_jump) or the food cost (margin_breach) on as_of';
comment on column public.alert.threshold is 'percent points: the threshold that fired';

-- Settings -----------------------------------------------------------------------------------
-- 03 defaults and U3; one place to calibrate them in the pilot.
create function app.cost_alert_settings(
  out jump_vs_last_pct numeric, out jump_vs_avg_pct numeric, out avg_days int, out breach_pts numeric,
  out top_ingredients int, out top_dishes int, out ranking_days int, out fresh_days int)
language sql immutable set search_path = ''
as $$ select 15.0, 8.0, 30, 3.0, 20, 10, 30, 7 $$;

-- Price jumps --------------------------------------------------------------------------------
-- The days in [from_date, to_date] on which the price of record of a tenant's ingredient changed
-- and the change is a jump. A change can only happen where a price row starts or the day after
-- one ends, so only those days are checked; each costs 32 price-of-record lookups.
create function app.price_jumps(tenant uuid, from_date date, to_date date)
returns table (ingredient_id uuid, started date, old_unit_price numeric, new_unit_price numeric,
               avg_unit_price numeric, change_pct numeric, threshold_pct numeric)
language sql stable set search_path = ''
as $$
  with k as (
    select * from app.cost_alert_settings()
  ), candidate as (
    select distinct p.ingredient_id, d.day
    from public.ingredient_price p
    cross join lateral (values (p.effective_from), (p.effective_to + 1)) d(day)
    where p.tenant_id = tenant and d.day between from_date and to_date
      and p.ingredient_id in (select u.ingredient_id from app.live_ingredients(to_date) u)
  ), move as (
    select c.ingredient_id, c.day, o.unit_price_net as old_price, n.unit_price_net as new_price,
           (select avg(h.unit_price_net)
            from k, generate_series(c.day - k.avg_days, c.day - 1, interval '1 day') g
            cross join lateral app.price_of_record(c.ingredient_id, g::date) h
            where h.unit_price_net > 0) as avg_price
    from candidate c
    cross join lateral app.price_of_record(c.ingredient_id, c.day) n
    cross join lateral app.price_of_record(c.ingredient_id, c.day - 1) o
    where n.unit_price_net > 0 and o.unit_price_net > 0 and n.unit_price_net <> o.unit_price_net
  ), fired as (
    select m.*, 100 * abs(m.new_price - m.old_price) >= k.jump_vs_last_pct * m.old_price as vs_last,
           100 * abs(m.new_price - m.avg_price) >= k.jump_vs_avg_pct * m.avg_price as vs_avg,
           k.jump_vs_last_pct, k.jump_vs_avg_pct
    from move m, k
  )
  select f.ingredient_id, f.day, f.old_price, f.new_price, round(f.avg_price, 6),
         case when f.vs_last then 100 * (f.new_price - f.old_price) / f.old_price
              else 100 * (f.new_price - f.avg_price) / f.avg_price end,
         case when f.vs_last then f.jump_vs_last_pct else f.jump_vs_avg_pct end
  from fired f
  where f.vs_last or f.vs_avg
$$;

-- Theoretical spend per ingredient over [from_date, to_date], in centavos: units sold of each
-- dish x what its recipe of record on to_date uses (through sub-recipes, the engine's yields and
-- depth limit) x the price of record on to_date.
create function app.ingredient_spend(tenant uuid, from_date date, to_date date)
returns table (ingredient_id uuid, spend numeric)
language sql stable set search_path = ''
as $$
  with recursive sold as (
    select v.menu_item_id, sum(v.units) as units
    from app.v_item_sales_daily v
    where v.tenant_id = tenant and v.business_date between from_date and to_date
    group by v.menu_item_id
  ), walk(recipe_id, factor, depth) as (
    -- factor: how many times the recipe's lines are used (portions / yield, or base units / yield)
    select r.id, s.units / coalesce(nullif(r.yield_qty, 0), 1), 0
    from sold s
    join public.recipe r on r.id = app.recipe_of_record(s.menu_item_id, null, to_date)
    union all
    select sub.id, w.factor * rl.qty_base / sub.yield_qty, w.depth + 1
    from walk w
    join public.recipe_line rl on rl.recipe_id = w.recipe_id and rl.sub_recipe_id is not null
    join public.recipe sr on sr.id = rl.sub_recipe_id
    join public.recipe sub on sub.id = app.recipe_of_record(null, sr.produces_ingredient_id, to_date)
    where w.depth < 8 and sub.yield_qty > 0
  )
  select rl.ingredient_id,
         sum(w.factor * rl.qty_base * p.unit_price_net * 100 * 100
             / nullif(coalesce(rl.yield_override_pct, i.default_yield_pct), 0))
  from walk w
  join public.recipe_line rl on rl.recipe_id = w.recipe_id and rl.ingredient_id is not null
  join public.ingredient i on i.id = rl.ingredient_id
  cross join lateral app.price_of_record(rl.ingredient_id, to_date) p
  group by rl.ingredient_id
$$;

-- Evaluator ----------------------------------------------------------------------------------
-- Writes the tenant's alerts for one business day; returns how many rows it added. Idempotent: a
-- rerun adds nothing. Price jumps are looked for over the 7 days to on_date, so a price entered a
-- few days late is still caught by the next run.
create function app.evaluate_cost_alerts(tenant uuid, on_date date) returns int
language plpgsql set search_path = ''
as $$
declare
  k record;
  breach_above numeric;
  jumps int;
  breaches int;
begin
  if tenant is null or on_date is null then
    raise exception 'tenant and on_date are required' using errcode = '22023';
  end if;
  select * into k from app.cost_alert_settings();
  breach_above := app.food_cost_target() + k.breach_pts;
  -- one evaluation per tenant at a time
  perform pg_advisory_xact_lock(hashtextextended('cost_alerts:' || tenant::text, 0));

  with top_spend as (
    select s.ingredient_id from app.ingredient_spend(tenant, on_date - (k.ranking_days - 1), on_date) s
    where s.spend > 0
    order by s.spend desc, s.ingredient_id
    limit k.top_ingredients
  )
  insert into public.alert (tenant_id, rule, ingredient_id, as_of, value, threshold,
                            old_unit_price, new_unit_price, avg_unit_price, urgent)
  select tenant, 'price_jump', j.ingredient_id, j.started, round(j.change_pct, 4), j.threshold_pct,
         j.old_unit_price, j.new_unit_price, j.avg_unit_price,
         100 * (j.new_unit_price - j.old_unit_price) >= k.jump_vs_last_pct * j.old_unit_price
           and j.ingredient_id in (select t.ingredient_id from top_spend t)
  from app.price_jumps(tenant, on_date - (k.fresh_days - 1), on_date) j
  on conflict (tenant_id, ingredient_id, as_of) where rule = 'price_jump' do nothing;
  get diagnostics jumps = row_count;

  with breach as (
    select s.location_id, s.menu_item_id
    from public.dish_cost_snapshot s
    where s.tenant_id = tenant and s.date = on_date and s.price_net > 0 and 100.0 * s.cost / s.price_net > breach_above
  ), episode as (
    -- first breaching day after the last snapshot within target (days without a snapshot or a
    -- price say nothing, so they neither end nor start an episode)
    select b.location_id, b.menu_item_id, (
             select min(s.date) from public.dish_cost_snapshot s
             where s.tenant_id = tenant and s.location_id = b.location_id and s.menu_item_id = b.menu_item_id
               and s.date <= on_date and s.price_net > 0 and s.date > coalesce((
                 select max(o.date) from public.dish_cost_snapshot o
                 where o.tenant_id = tenant and o.location_id = b.location_id and o.menu_item_id = b.menu_item_id
                   and o.date < on_date and o.price_net > 0 and 100.0 * o.cost / o.price_net <= breach_above),
                 '-infinity'::date)) as started
    from breach b
  ), top_dish as (
    select x.location_id, x.menu_item_id from (
      select v.location_id, v.menu_item_id,
             row_number() over (partition by v.location_id order by sum(v.net) desc, v.menu_item_id) as n
      from app.v_item_sales_daily v
      where v.tenant_id = tenant and v.business_date between on_date - (k.ranking_days - 1) and on_date
      group by v.location_id, v.menu_item_id
    ) x where x.n <= k.top_dishes
  )
  insert into public.alert (tenant_id, location_id, rule, menu_item_id, as_of, value, threshold, urgent)
  select tenant, e.location_id, 'margin_breach', e.menu_item_id, e.started,
         round(100.0 * s.cost / s.price_net, 4), breach_above,
         e.started > on_date - k.fresh_days
           and exists (select 1 from top_dish t where t.location_id = e.location_id and t.menu_item_id = e.menu_item_id)
  from episode e
  join public.dish_cost_snapshot s
    on s.tenant_id = tenant and s.location_id = e.location_id and s.menu_item_id = e.menu_item_id and s.date = e.started
  -- a breach already alerted in this episode (even under an earlier start, before a recompute
  -- moved it) is not alerted again
  where not exists (select 1 from public.alert a
                    where a.tenant_id = tenant and a.rule = 'margin_breach' and a.location_id = e.location_id
                      and a.menu_item_id = e.menu_item_id and a.as_of between e.started and on_date)
  on conflict (tenant_id, location_id, menu_item_id, as_of) where rule = 'margin_breach' do nothing;
  get diagnostics breaches = row_count;

  return jumps + breaches;
end
$$;

-- get_cost_alerts on the shared jump rule ----------------------------------------------------
-- As in 20261104090000_read_rpcs_cost.sql, except price moves: per ingredient, the latest jump
-- (app.price_jumps) that started in the window, while the ingredient still has a price of record
-- above zero at the window's end. `change` is the change that fired. Same output (C3).
create or replace function api.get_cost_alerts(since jsonb default '"last_7d"', location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  r date[];
  w_to date;
  moves jsonb;
  breaches jsonb;
  suggestions jsonb;
  levels app.cost_confidence[];
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  today := app.business_today(location_id);
  r := app.resolve_period(coalesce(since, '"last_7d"'), today);
  if r[1] > today then
    raise exception 'since must start on or before today' using errcode = '22023';
  end if;
  w_to := today;

  select coalesce(jsonb_agg(jsonb_build_object(
           'ingredient', m.name,
           'change', app.pct(m.change_pct, true),
           'new_unit_price', jsonb_build_object('raw', trim_scale(m.new_price), 'base_unit', m.base_unit,
                                                'text', app.price_text(m.new_price, m.base_unit)))
         order by m.started, m.name), '[]')
  into moves
  from (
    select distinct on (j.ingredient_id) i.name, i.base_unit, j.new_unit_price as new_price, j.change_pct, j.started
    from app.price_jumps((select app.current_tenant_id()), r[1], w_to) j
    join public.ingredient i on i.id = j.ingredient_id
    where exists (select 1 from app.price_of_record(j.ingredient_id, w_to) cur where cur.unit_price_net > 0)
    order by j.ingredient_id, j.started desc
  ) m;

  with latest as (
    select distinct on (s.menu_item_id, s.location_id) s.menu_item_id, s.cost, s.price_net, s.confidence
    from public.dish_cost_snapshot s
    where s.location_id = any (locs) and s.date between r[1] and w_to and s.price_net > 0
    order by s.menu_item_id, s.location_id, s.date desc
  ), worst as (
    select distinct on (l.menu_item_id) l.menu_item_id, 100.0 * l.cost / l.price_net as fc, l.confidence
    from latest l order by l.menu_item_id, 100.0 * l.cost / l.price_net desc
  )
  select coalesce((select jsonb_agg(jsonb_build_object('menu_item_id', b.menu_item_id, 'name', m.name,
                                                       'food_cost', app.pct(b.fc), 'target', app.pct(app.food_cost_target()))
                                    order by round(b.fc, 4) desc, m.name)
                   from worst b join public.menu_item m on m.id = b.menu_item_id
                   where b.fc > app.food_cost_target() + 3), '[]'),
         (select array_agg(distinct b.confidence) from worst b where b.fc > app.food_cost_target() + 3)
  into breaches, levels;

  select coalesce(jsonb_agg(jsonb_build_object(
           'menu_item_id', x.item_id,
           'name', coalesce(x.item_name, nullif(btrim(x.subject), ''), x.rule),
           'current_price', case when x.price is not null then app.money(x.price) end,
           'suggested_price', app.money(x.suggested_price))
         order by x.created_at, x.id), '[]')
  into suggestions
  from (
    select ps.id, ps.subject, ps.rule, ps.suggested_price, ps.created_at, m.id as item_id, m.name as item_name,
           case when m.id is not null and ps.loc is not null then app.menu_price_on(m.id, ps.loc, today) end as price
    from (select p.*, coalesce(p.location_id, get_cost_alerts.location_id) as loc from public.price_suggestion p) ps
    left join public.menu_item m
      on m.id = app.subject_item(ps.subject, case when ps.loc is not null then array[ps.loc] else locs end, today)
    where (ps.location_id = any (locs) or ps.location_id is null)
      and (ps.status is null or ps.status in ('open', 'pending'))
      and ps.suggested_price is not null
  ) x;

  if breaches <> '[]' then
    flags := flags || app.confidence_flag(levels);
  end if;
  return app.rpc_ok(
    jsonb_build_object('price_moves', moves, 'breaches', breaches, 'suggestions', suggestions),
    locs, flags, null, array[r[1], w_to]);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- Privileges ---------------------------------------------------------------------------------
-- The RPC runs as the caller and needs the jump rule. The evaluator and its spend ranking are the
-- backend's (service_role), with the helpers and the sales view they read.
revoke all on function app.cost_alert_settings(), app.price_jumps(uuid, date, date),
  app.ingredient_spend(uuid, date, date), app.evaluate_cost_alerts(uuid, date) from public, anon, authenticated;
grant execute on function app.cost_alert_settings(), app.price_jumps(uuid, date, date) to authenticated, service_role;
grant execute on function app.ingredient_spend(uuid, date, date), app.evaluate_cost_alerts(uuid, date),
  app.food_cost_target(), app.live_ingredients(date) to service_role;
grant select on app.v_item_sales_daily to service_role;
