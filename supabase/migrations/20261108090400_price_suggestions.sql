-- MR-33 (part b): menu price suggestions (03 "Price-suggestion formula"; user decisions U1, U2 and
-- U4 in docs/superpowers/plans/2026-11-06-mr-33-cost-alerts.md). Rules in code, never the LLM:
-- app.evaluate_cost_alerts writes them next to the alerts. Suggestions only: nothing here writes a
-- pending_change or a menu price ("Cambiar precios" makes a menu_item_price.set pending change,
-- confirmed by a person; MR-37 / MR-38).
--
-- - Prices are menu prices with IVA included (settles MR-11 spec 7.2). The price that reaches the
--   target is cost / target x (1 + IVA), the target in percent points (32 -> 0.32) and IVA at the
--   menu price's own rate (16 % when unknown).
-- - Formula (app.suggest_menu_price, pure, rounded once at the end): that price rounded UP to a
--   price point ($5 under $250, $10 at or above), capped at +10 % of the current price rounded
--   DOWN to a price point; never a decrease, and no price when the cap lands on the current price
--   ($30 + 10 % = $33 -> $30). Reproduces doc 12: Costra $89 -> $95 (36.4 %), Bistec $85 -> $90
--   (36.0 %, $101.14 to reach 32 %), Gringa $79 -> $85 (33.6 %).
-- - Eligibility (03 "2 observations"): the dish breaches (food cost above target + 3 pts, U1) on the
--   latest snapshot on or before the evaluated day and on the latest on or before a week earlier;
--   each must be at most a week old (a dish the engine stopped costing gets nothing, never a guess).
--   Both observations count only at the dish's current menu price: that price must be the menu
--   price every day since the earlier one (pacing: a week after any price change, e.g. an applied
--   suggestion, before the next one). The suggestion quotes the menu price on the evaluated day.
-- - Resale items (U2: bottled drinks; Coca-Cola, Corona) keep their breach alerts but never get a
--   suggestion. The schema has no resale flag, so the narrowest signal is used: the dish's recipe
--   of record is a single line, an ingredient bought by the piece (`pza`), no sub-recipe, quantity
--   exactly 1 and yield 100 % (the line's and the recipe's): one bought piece is one sold item.
--   "5 tortillas" or "2 huevos" are dishes. (menu_item.kind = 'drink' is wider: it holds micheladas
--   and coffee.) An owner-confirmed resale flag at onboarding is a follow-up (MR-95).
-- - Menu engineering (U4, 03 Kasavana-Smith over the location's last 30 days, the rule of
--   api.get_menu_engineering): plowhorses get a price (raise_to_target or raise_capped); stars are
--   not raised (no row); puzzles and dogs get review_portion_cost ("revisa porción/costo") and no
--   price. A dish not sold in those 30 days has no quadrant and gets nothing.
-- - Confidence: the snapshot's (the engine's rule: confirmed = every recipe confirmed and every
--   price from a CFDI, or a confirmed nota, under 30 days old; else estimated).
-- - One row per breach episode per (tenant, location, dish), not per day. The episode is the
--   margin_breach alert's: the run of breaching snapshots since the last one within the line
--   (`episode_start`). While the row is open the daily run refreshes it in place (`as_of` = the
--   last day evaluated); a rerun on unchanged data writes nothing, and an older day than the row's
--   is never written back. An acted-on row (pending, dismissed, applied) sticks for its episode: no
--   new open row until a new episode starts, the current price changes, or the suggested price
--   moves to a higher price point (a price where a review stood counts as higher). An open row the
--   day's run did not refresh (the dish became a star or resale, stopped breaching or being costed,
--   lost its earlier observation, changed price) is removed; an acted-on row never is.
-- - A price row with a tax rate outside [0, 1) or a target price not above zero is skipped, so one
--   bad row never rolls back the tenant's day.
-- - api.get_cost_alerts shows each dish's latest row in the window while it is open or pending, no
--   acted-on row of its episode holds it back, its current price is still the menu price and the
--   dish still breaches; an open row only while it is fresh (evaluated on or after the dish's
--   latest snapshot, and within the last week, as the writer's observations). The top 10 by food
--   cost, with the total (doc 13: tool results stay small); breaches are capped the same way.

-- Columns ------------------------------------------------------------------------------------
-- The free-text subject (MR-10) is replaced by the dish; nothing wrote it.
alter table public.price_suggestion drop column subject;
drop function app.subject_item(text, uuid[], date);

alter table public.price_suggestion
  add column menu_item_id uuid,
  add column as_of date,
  add column episode_start date,
  add column current_price bigint,
  add column target_price bigint,
  add column new_food_cost_pct numeric(7, 4),
  add column confidence app.cost_confidence,
  add foreign key (tenant_id, menu_item_id) references public.menu_item (tenant_id, id) on delete restrict;

update public.price_suggestion set status = 'open' where status is null;
alter table public.price_suggestion
  alter column status set default 'open',
  alter column status set not null,
  add constraint price_suggestion_status_known check (status in ('open', 'pending', 'applied', 'dismissed')),
  -- coalesce: a null comparison must fail the check, not pass it
  add constraint price_suggestion_shape check (coalesce(
    rule = 'margin_breach' and menu_item_id is not null and location_id is not null and as_of is not null
      and episode_start <= as_of
      and value is not null and threshold is not null and current_price > 0 and target_price > 0
      and confidence in ('confirmed', 'estimated') and (
        -- a raise is above the current price and at most +10 % (U4, max_step_pct), in exact integers
        (rationale_code in ('raise_to_target', 'raise_capped') and suggested_price > current_price
          and suggested_price * 10 <= current_price * 11 and new_food_cost_pct is not null
          and (rationale_code = 'raise_to_target') = (suggested_price >= target_price))
        or (rationale_code = 'review_portion_cost' and suggested_price is null and new_food_cost_pct is null)), false));

-- at most one open suggestion per dish and location: the writer refreshes it in place
create unique index price_suggestion_open_key on public.price_suggestion (tenant_id, location_id, menu_item_id)
  where status = 'open';
-- a dish's rows by day (the writer's latest row, get_cost_alerts' episode check)
create index price_suggestion_dish_idx on public.price_suggestion (tenant_id, location_id, menu_item_id, as_of);
create index price_suggestion_menu_item_idx on public.price_suggestion (tenant_id, menu_item_id);
select app.tag('public.price_suggestion', 'unit=centavos', array['current_price', 'target_price']);
select app.tag('public.price_suggestion', 'unit=percent_points', array['new_food_cost_pct']);
comment on column public.price_suggestion.rule is 'margin_breach (price_suggestion_shape)';
comment on column public.price_suggestion.status is 'open | pending | applied | dismissed (price_suggestion_status_known)';
comment on column public.price_suggestion.rationale_code is
  'raise_to_target | raise_capped | review_portion_cost (price_suggestion_shape)';
comment on column public.price_suggestion.value is 'percent points: the food cost on as_of';
comment on column public.price_suggestion.as_of is 'the last day evaluated (refreshed in place while open)';
comment on column public.price_suggestion.episode_start is
  'the first day of the breach run (the margin_breach alert''s as_of): one row per episode';
comment on column public.price_suggestion.threshold is 'percent points: the breach line (target + 3 pts)';

-- Settings -----------------------------------------------------------------------------------
-- U4 defaults; one place to calibrate them in the pilot. Prices in centavos.
create function app.price_suggestion_settings(
  out max_step_pct numeric, out small_point bigint, out large_point bigint, out large_from bigint,
  out observation_days int)
language sql immutable set search_path = ''
as $$ select 10.0, 500::bigint, 1000::bigint, 25000::bigint, 7 $$;

-- How many price moves and suggestions api.get_cost_alerts lists (the largest; it also returns the
-- totals). Doc 13: tool results stay around 400 tokens, top N only. CostAlertsData.TOP_N.
create function app.cost_alerts_top_n() returns int
language sql immutable set search_path = ''
as $$ select 10 $$;

-- A price rounded to a menu price point: the next one up, or down ($5 steps under $250, $10 at or
-- above). Centavos in and out.
create function app.price_point(cents numeric, up boolean) returns bigint
language sql immutable set search_path = ''
as $$
  select (case when up then ceil(cents / s.step) else floor(cents / s.step) end * s.step)::bigint
  from app.price_suggestion_settings() k
  cross join lateral (select case when cents < k.large_from then k.small_point else k.large_point end as step) s
$$;

-- The formula, pure. cost and current_price in centavos (the price with IVA), tax_rate a fraction
-- (null: 16 %), target_pct in percent points. target_price: the lowest price in centavos that
-- reaches the target; suggested_price: null when the cap leaves the current price (never a
-- decrease); new_food_cost_pct: on the suggested price's net (the engine's IVA rounding). No row
-- for a cost, price or target that is not above zero.
create function app.suggest_menu_price(cost bigint, current_price bigint, tax_rate numeric, target_pct numeric)
returns table (target_price bigint, suggested_price bigint, new_food_cost_pct numeric)
language sql immutable set search_path = ''
as $$
  with x as (
    select cost * 100 * (1 + coalesce(tax_rate, 0.16)) / target_pct as raw_target,
           coalesce(tax_rate, 0.16) as rate, k.max_step_pct
    from app.price_suggestion_settings() k
    where cost > 0 and current_price > 0 and target_pct > 0
  ), p as (
    select x.raw_target, x.rate,
           least(app.price_point(x.raw_target, true),
                 app.price_point(current_price * (100 + x.max_step_pct) / 100, false)) as point
    from x
  )
  select ceil(p.raw_target)::bigint,
         case when p.point > current_price then p.point end,
         case when p.point > current_price
              then round(100.0 * cost / (p.point - round(p.point * p.rate / (1 + p.rate))), 4) end
  from p
$$;

-- U2: a dish bought and sold as is. Its recipe of record on the day is one line: one piece (`pza`,
-- quantity 1) of a bought ingredient, at 100 % yield, for one portion. "5 tortillas" is a dish.
create function app.is_resale(item uuid, on_date date) returns boolean
language sql stable set search_path = ''
as $$
  select count(*) = 1 and coalesce(bool_and(
           l.sub_recipe_id is null and i.base_unit = 'pza' and l.qty_base = 1
           and coalesce(l.yield_override_pct, i.default_yield_pct) = 100 and coalesce(r.yield_qty, 1) = 1), false)
  from public.recipe r
  join public.recipe_line l on l.recipe_id = r.id
  left join public.ingredient i on i.id = l.ingredient_id
  where r.id = app.recipe_of_record(item, null, on_date)
$$;

-- The first day of the breach run that the snapshot of `on_date` closes: the first snapshot after
-- the last one within the line (food cost at or under `breach_above`) before on_date. Days without
-- a snapshot or a price say nothing, so they neither end nor start a run. The margin_breach
-- alert's episode and the price suggestion's.
create function app.breach_episode_start(tenant uuid, loc uuid, item uuid, on_date date, breach_above numeric)
returns date
language sql stable set search_path = ''
as $$
  select min(s.date) from public.dish_cost_snapshot s
  where s.tenant_id = tenant and s.location_id = loc and s.menu_item_id = item
    and s.date <= on_date and s.price_net > 0 and s.date > coalesce((
      select max(o.date) from public.dish_cost_snapshot o
      where o.tenant_id = tenant and o.location_id = loc and o.menu_item_id = item
        and o.date < on_date and o.price_net > 0 and 100.0 * o.cost / o.price_net <= breach_above),
      '-infinity'::date)
$$;

-- The menu price on `on_date` was the menu price every day since `since`: the same price then, and
-- no other price started in between. Null without a price on on_date.
create function app.menu_price_steady(item uuid, loc uuid, since date, on_date date) returns boolean
language sql stable set search_path = ''
as $$
  select (select r.price_gross from app.menu_price_row(item, loc, since) r) is not distinct from cur.price_gross
     and not exists (
       select 1 from public.menu_item_price p
       where p.menu_item_id = item and p.location_id = loc and p.effective_from > since
         and p.effective_from <= on_date and p.price_gross <> cur.price_gross)
  from app.menu_price_row(item, loc, on_date) cur
$$;

-- A suggestion an owner acted on (pending, dismissed, applied) gives way to a new one in its
-- episode only when the current price changed or the suggested price is a higher price point (a
-- price where a review, no price, stood counts as higher).
create function app.suggestion_reopens(acted_current bigint, acted_suggested bigint, new_current bigint,
                                       new_suggested bigint) returns boolean
language sql immutable set search_path = ''
as $$
  select new_current is distinct from acted_current or coalesce(new_suggested, 0) > coalesce(acted_suggested, 0)
$$;

-- Menu engineering ---------------------------------------------------------------------------
-- Kasavana-Smith over the costed sales of [f, t] at locs, one quadrant per dish (modifiers left
-- out): popular when its share of units is at least 70 % of the equal share, profitable when its
-- contribution margin per unit (net without IVA - cost) is at least the units-weighted average.
-- The one rule for api.get_menu_engineering and the suggestions.
create function app.menu_quadrants(locs uuid[], f date, t date)
returns table (menu_item_id uuid, units numeric, quadrant text)
language sql stable set search_path = ''
as $$
  with d as (
    select c.menu_item_id, sum(c.units) as units, round(sum(c.net_ex_iva)) - sum(c.units * c.cost) as cm
    from app.item_cost_rows(locs, f, t) c
    join public.menu_item m on m.id = c.menu_item_id
    where m.kind <> 'modifier' and c.cost is not null
    group by c.menu_item_id having sum(c.units) > 0
  ), tot as (
    select count(*) as n, sum(d.units) as units, sum(d.cm) as cm from d
  )
  select d.menu_item_id, d.units,
         case when d.units / tot.units >= 0.7 / tot.n then
                case when d.cm / d.units >= tot.cm / tot.units then 'star' else 'plowhorse' end
              else case when d.cm / d.units >= tot.cm / tot.units then 'puzzle' else 'dog' end
         end
  from d cross join tot
$$;

-- As in 20261108090000_read_rpcs_cost.sql, on app.menu_quadrants. Same output.
create or replace function api.get_menu_engineering(period jsonb, location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  r date[];
  s record;
  quadrants jsonb;
  levels app.cost_confidence[];
  uncosted bigint;
  flags jsonb := '[]';
begin
  if locs is null then
    return app.rpc_error('not_found', 'location not found');
  end if;
  r := app.resolve_period(period, app.business_today(location_id));

  with x as (
    select c.* from app.item_cost_rows(locs, r[1], r[2]) c
    join public.menu_item m on m.id = c.menu_item_id
    where m.kind <> 'modifier'
  ), q as (
    select m.name, q.units, q.quadrant
    from app.menu_quadrants(locs, r[1], r[2]) q join public.menu_item m on m.id = q.menu_item_id
  )
  select case when exists (select 1 from q) then (
           select jsonb_agg(jsonb_build_object(
                    'name', k.name,
                    'count', (select count(*) from q where q.quadrant = k.name),
                    'top_items', coalesce((select jsonb_agg(t.name order by t.units desc, t.name)
                                           from (select q.name, q.units from q where q.quadrant = k.name
                                                 order by q.units desc, q.name limit 3) t), '[]'))
                  order by k.ord)
           from unnest(array['star', 'plowhorse', 'puzzle', 'dog']) with ordinality k(name, ord)) end,
         (select array_agg(distinct x.confidence) from x where x.confidence is not null),
         (select count(*) from x where x.cost is null)
  into quadrants, levels, uncosted;

  if quadrants is null then
    return app.rpc_error('no_data', 'No costed dish sales for the period', locs);
  end if;
  flags := flags || app.confidence_flag(levels);
  if uncosted > 0 then
    flags := flags || app.flag('uncosted_sales', 'Algunos platillos vendidos no tienen costo y no entran en el análisis.');
  end if;
  select * into s from app.sales_totals(locs, r[1], r[2]);
  if s.expected_covered < s.expected_days then
    flags := flags || app.flag('missing_days',
      format('Faltan datos de %s de %s días del periodo.', s.expected_days - s.expected_covered, s.expected_days));
  end if;

  return app.rpc_ok(jsonb_build_object('quadrants', quadrants), locs, flags,
                    100.0 * s.expected_covered / nullif(s.expected_days, 0), r);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- Writer -------------------------------------------------------------------------------------
-- Writes the tenant's suggestions for one business day; returns how many rows it added, refreshed
-- or removed. One row per breach episode: the dish's open row is refreshed in place; a new row is
-- added when the dish has none, its latest is from an earlier episode, or its latest was acted on
-- and app.suggestion_reopens. An open row from an earlier day that this run did not refresh no
-- longer holds (no longer eligible) and is removed. Idempotent: a rerun on unchanged data writes
-- nothing. An acted-on row (not open) is never touched, and a day older than the dish's latest row
-- writes nothing and removes nothing newer.
create function app.write_price_suggestions(tenant uuid, on_date date) returns int
language plpgsql set search_path = ''
as $$
declare
  k record;
  a record;
  breach_above numeric;
  target numeric := app.food_cost_target();
  written int;
  removed int;
begin
  if tenant is null or on_date is null then
    raise exception 'tenant and on_date are required' using errcode = '22023';
  end if;
  select * into k from app.price_suggestion_settings();
  select * into a from app.cost_alert_settings();
  breach_above := target + a.breach_pts;
  -- one writer per tenant at a time (the evaluator's lock; it nests)
  perform pg_advisory_xact_lock(hashtextextended('cost_alerts:' || tenant::text, 0));

  with obs as (
    -- n = 0: the latest snapshot on or before on_date; n = 1: on or before a week earlier; each at
    -- most a week old
    select distinct on (s.location_id, s.menu_item_id, o.n)
           o.n, s.location_id, s.menu_item_id, s.date, s.cost, s.price_net, s.confidence
    from (values (0), (1)) o(n)
    join public.dish_cost_snapshot s
      on s.tenant_id = tenant and s.price_net > 0
     and s.date <= on_date - o.n * k.observation_days and s.date > on_date - (o.n + 1) * k.observation_days
    order by s.location_id, s.menu_item_id, o.n, s.date desc
  ), breaching as (
    select cur.location_id, cur.menu_item_id, cur.date, prev.date as prev_date, cur.cost, cur.confidence,
           round(100.0 * cur.cost / cur.price_net, 4) as food_cost
    from obs cur
    join obs prev on prev.location_id = cur.location_id and prev.menu_item_id = cur.menu_item_id and prev.n = 1
    where cur.n = 0
      and 100.0 * cur.cost / cur.price_net > breach_above and 100.0 * prev.cost / prev.price_net > breach_above
      and cur.confidence in ('confirmed', 'estimated')
  ), quadrant as materialized (
    -- once per location (inlined, the planner can rerun it per breaching dish)
    select l.location_id, q.menu_item_id, q.quadrant
    from (select distinct b.location_id from breaching b) l
    cross join lateral app.menu_quadrants(array[l.location_id], on_date - (a.ranking_days - 1), on_date) q
  ), candidate as materialized (
    -- stars are not raised; the per-dish checks below run only on what is left
    select b.*, q.quadrant
    from breaching b
    join quadrant q on q.location_id = b.location_id and q.menu_item_id = b.menu_item_id
    where q.quadrant in ('plowhorse', 'puzzle', 'dog')
  ), proposal as materialized (
    select c.*, mp.price_gross, f.target_price, f.suggested_price, f.new_food_cost_pct,
           case when c.quadrant in ('puzzle', 'dog') then 'review_portion_cost'
                when f.suggested_price >= f.target_price then 'raise_to_target'
                when f.suggested_price is not null then 'raise_capped'
           end as rationale_code
    from candidate c
    cross join lateral app.menu_price_row(c.menu_item_id, c.location_id, on_date) mp
    cross join lateral app.suggest_menu_price(c.cost, mp.price_gross, mp.tax_rate, target) f
    -- a usable price row (one bad rate must not fail the shape check and roll back the tenant's
    -- day), both observations at the current menu price (pacing), and not a resale item (U2)
    where mp.tax_rate >= 0 and mp.tax_rate < 1 and f.target_price > 0
      and app.menu_price_steady(c.menu_item_id, c.location_id, c.prev_date, on_date)
      and not app.is_resale(c.menu_item_id, c.date)
  ), episode as (
    select x.location_id, x.menu_item_id, x.food_cost, x.confidence, x.price_gross, x.target_price,
           x.rationale_code,
           case when x.rationale_code <> 'review_portion_cost' then x.suggested_price end as suggested_price,
           case when x.rationale_code <> 'review_portion_cost' then x.new_food_cost_pct end as new_food_cost_pct,
           app.breach_episode_start(tenant, x.location_id, x.menu_item_id, x.date, breach_above) as episode_start
    from proposal x
    where x.rationale_code is not null
  ), decision as (
    select e.*, l.id as latest_id,
           case when l.id is null then 'insert'
                when on_date < l.as_of then 'skip'
                when l.status = 'open' then 'update'
                when l.episode_start >= e.episode_start
                     and not app.suggestion_reopens(l.current_price, l.suggested_price, e.price_gross, e.suggested_price)
                  then 'skip'
                else 'insert'
           end as action
    from episode e
    left join lateral (
      select p.id, p.status, p.as_of, p.episode_start, p.current_price, p.suggested_price
      from public.price_suggestion p
      where p.tenant_id = tenant and p.location_id = e.location_id and p.menu_item_id = e.menu_item_id
      order by p.as_of desc, p.id desc
      limit 1
    ) l on true
  ), refreshed as (
    update public.price_suggestion p
    set as_of = on_date, episode_start = d.episode_start, value = d.food_cost, threshold = breach_above,
        current_price = d.price_gross, target_price = d.target_price, suggested_price = d.suggested_price,
        new_food_cost_pct = d.new_food_cost_pct, confidence = d.confidence, rationale_code = d.rationale_code
    from decision d
    where d.action = 'update' and p.id = d.latest_id and p.status = 'open'
      and (p.as_of, p.episode_start, p.value, p.threshold, p.current_price, p.target_price, p.suggested_price,
           p.new_food_cost_pct, p.confidence, p.rationale_code)
          is distinct from (on_date, d.episode_start, d.food_cost, breach_above, d.price_gross, d.target_price,
                            d.suggested_price, d.new_food_cost_pct, d.confidence, d.rationale_code)
    returning 1
  ), added as (
    insert into public.price_suggestion
      (tenant_id, location_id, menu_item_id, as_of, episode_start, rule, value, threshold, current_price,
       target_price, suggested_price, new_food_cost_pct, confidence, rationale_code)
    select tenant, d.location_id, d.menu_item_id, on_date, d.episode_start, 'margin_breach', d.food_cost,
           breach_above, d.price_gross, d.target_price, d.suggested_price, d.new_food_cost_pct, d.confidence,
           d.rationale_code
    from decision d
    where d.action = 'insert'
    on conflict (tenant_id, location_id, menu_item_id) where status = 'open' do nothing
    returning 1
  )
  select (select count(*) from refreshed) + (select count(*) from added) into written;

  -- a separate statement, so it sees this run's refreshes (as_of = on_date): what is left from an
  -- earlier day was not eligible today; no owner acted on it
  delete from public.price_suggestion p
  where p.tenant_id = tenant and p.status = 'open' and p.as_of < on_date;
  get diagnostics removed = row_count;
  return written + removed;
end
$$;

-- Evaluator ----------------------------------------------------------------------------------
-- As in 20261108090300_cost_alerts.sql, with the episode start from app.breach_episode_start (the
-- same rule, now shared with the suggestions), plus the day's price suggestions (written after the
-- alerts, in the same transaction). Still returns how many alerts it added.
create or replace function app.evaluate_cost_alerts(tenant uuid, on_date date, today date default null) returns int
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
  today := coalesce(today, app.tenant_today(tenant));
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
           and j.started > today - k.fresh_days
           and j.ingredient_id in (select t.ingredient_id from top_spend t)
  from app.price_jumps(tenant, on_date - (k.fresh_days - 1), on_date) j
  on conflict (tenant_id, ingredient_id, as_of) where rule = 'price_jump' do nothing;
  get diagnostics jumps = row_count;

  with breach as (
    select s.location_id, s.menu_item_id
    from public.dish_cost_snapshot s
    where s.tenant_id = tenant and s.date = on_date and s.price_net > 0 and 100.0 * s.cost / s.price_net > breach_above
  ), episode as (
    select b.location_id, b.menu_item_id,
           app.breach_episode_start(tenant, b.location_id, b.menu_item_id, on_date, breach_above) as started
    from breach b
  ), top_dish as (
    select x.location_id, x.menu_item_id from (
      select v.location_id, v.menu_item_id,
             row_number() over (partition by v.location_id order by sum(v.net) desc, v.menu_item_id) as n
      from app.v_item_sales_daily v
      where v.tenant_id = tenant and v.business_date between on_date - (k.ranking_days - 1) and on_date
      group by v.location_id, v.menu_item_id
    ) x where x.n <= k.top_dishes
  ), head as (
    -- the breach is the episode, across all its alert rows of any status. A late recompute can
    -- merge two episodes into one; only the earliest row is the episode's (F2), and an owner's
    -- acknowledge or dismiss on it leaves the whole episode as it is
    select distinct on (a.location_id, a.menu_item_id) a.id, a.status, a.location_id, a.menu_item_id, a.as_of,
           a.urgent, a.awaits_confirmation, a.evaluated_on, e.started
    from episode e
    join public.alert a
      on a.tenant_id = tenant and a.rule = 'margin_breach'
     and a.location_id = e.location_id and a.menu_item_id = e.menu_item_id
     and a.as_of between e.started and on_date
    order by a.location_id, a.menu_item_id, a.as_of
  ), next_state as (
    -- the open head of a breach still on (the episode only holds snapshots over the limit, so a
    -- breach that ended is left as it is) takes the confidence and the food cost of the on_date
    -- snapshot together (a late CFDI can move them either way). Its urgency moves by R1-R4:
    -- - another row of the episode already used its chance (it is urgent, or it no longer waits:
    --   a later row stops waiting only once the head does, below): the head stops waiting and is
    --   never urgent (F1, one urgency per breach, R4).
    -- - unconfirmed snapshot: not urgent (R1); a waiting row keeps waiting, a row that is not
    --   waiting is never set waiting again (R4).
    -- - confirmed snapshot on a fresh day of a waiting row: its one chance (R2, R4). It stops
    --   waiting, top 10 or not, and is urgent only if in the top 10 that day.
    -- - otherwise urgent stays as it is: a row that lost urgency, never had it or already used its
    --   chance cannot gain it; a catch-up over old days confirms the tag but leaves a waiting row
    --   waiting for a fresh day.
    -- A rerun of a day older than the last one applied to the row (a range rerun) leaves it as it
    -- is: an older day never undoes the state a later day set.
    select a.id, s.confidence, round(100.0 * s.cost / s.price_net, 4) as value,
           case when s.confidence <> 'confirmed' or u.spent then false
                when a.awaits_confirmation and on_date > today - k.fresh_days
                  then exists (select 1 from top_dish t where t.location_id = a.location_id and t.menu_item_id = a.menu_item_id)
                else a.urgent end as urgent,
           a.awaits_confirmation and not u.spent
             and not (s.confidence = 'confirmed' and on_date > today - k.fresh_days) as awaits_confirmation
    from head a
    join public.dish_cost_snapshot s
      on s.tenant_id = tenant and s.location_id = a.location_id and s.menu_item_id = a.menu_item_id and s.date = on_date
    cross join lateral (
      select a.awaits_confirmation and exists (
               select 1 from public.alert o
               where o.tenant_id = tenant and o.rule = 'margin_breach' and o.location_id = a.location_id
                 and o.menu_item_id = a.menu_item_id and o.as_of between a.started and on_date and o.id <> a.id
                 and (o.urgent or not o.awaits_confirmation)) as spent
    ) u
    where a.status = 'open' and (a.evaluated_on is null or a.evaluated_on <= on_date)
  ), refreshed as (
    -- only rows that change: an identical rerun of the same day writes nothing and bumps no version
    update public.alert a
    set confidence = n.confidence, value = n.value, urgent = n.urgent, awaits_confirmation = n.awaits_confirmation,
        evaluated_on = on_date
    from next_state n
    where a.id = n.id
      and (a.confidence, a.value, a.urgent, a.awaits_confirmation, a.evaluated_on)
          is distinct from (n.confidence, n.value, n.urgent, n.awaits_confirmation, on_date)
    returning 1
  ), merged as (
    -- F3: the episode's later open rows are never refreshed or granted. They keep waiting while
    -- the head waits (so the head can tell a row that used its chance from one that only follows
    -- it), and stop waiting for good once the head no longer waits or is no longer open. Their
    -- value and confidence stay as they were last refreshed, and their status is left alone: the
    -- weekly report (MR-37) and the same-day sender must dedupe margin_breach alerts by episode,
    -- or take the episode's earliest row.
    update public.alert o
    set awaits_confirmation = false
    from head h
    left join next_state n on n.id = h.id
    where o.tenant_id = tenant and o.rule = 'margin_breach' and o.status = 'open' and o.awaits_confirmation
      and o.location_id = h.location_id and o.menu_item_id = h.menu_item_id
      and o.as_of > h.as_of and o.as_of <= on_date
      and (h.status <> 'open' or not coalesce(n.awaits_confirmation, h.awaits_confirmation))
    returning 1
  )
  insert into public.alert (tenant_id, location_id, rule, menu_item_id, as_of, value, threshold, confidence, urgent, awaits_confirmation,
                            evaluated_on)
  -- as_of is the start of the episode; value and confidence come from the on_date snapshot
  select tenant, e.location_id, 'margin_breach', e.menu_item_id, e.started,
         round(100.0 * s.cost / s.price_net, 4), breach_above, s.confidence,
         -- urgent at insert needs all four: a new breach, started within fresh_days of on_date (R3:
         -- an existing problem goes to the weekly report), a confirmed on_date cost (R1), a fresh
         -- on_date and a top-10 dish
         e.started > on_date - k.fresh_days
           and s.confidence = 'confirmed'
           and on_date > today - k.fresh_days
           and exists (select 1 from top_dish t where t.location_id = e.location_id and t.menu_item_id = e.menu_item_id),
         -- a new breach recorded on an unconfirmed cost on a fresh day waits for its one chance (R2);
         -- an existing one or one first recorded on a stale day (a catch-up) never waits (R3), nor
         -- does one recorded confirmed (its chance is this insert, R4)
         e.started > on_date - k.fresh_days and s.confidence <> 'confirmed' and on_date > today - k.fresh_days,
         on_date
  from episode e
  join public.dish_cost_snapshot s
    on s.tenant_id = tenant and s.location_id = e.location_id and s.menu_item_id = e.menu_item_id and s.date = on_date
  -- a breach already alerted in this episode (even under an earlier start, before a recompute
  -- moved it) is not alerted again
  where not exists (select 1 from public.alert a
                    where a.tenant_id = tenant and a.rule = 'margin_breach' and a.location_id = e.location_id
                      and a.menu_item_id = e.menu_item_id and a.as_of between e.started and on_date)
  on conflict (tenant_id, location_id, menu_item_id, as_of) where rule = 'margin_breach' do nothing;
  get diagnostics breaches = row_count;

  perform app.write_price_suggestions(tenant, on_date);
  return jumps + breaches;
end
$$;
-- get_cost_alerts with the suggestions -------------------------------------------------------
-- As in 20261108090300_cost_alerts.sql, except:
-- - price_moves: the app.cost_alerts_top_n() largest moves (by size, either way), still listed by
--   start day, with price_moves_total counting them all;
-- - breaches: the app.cost_alerts_top_n() highest food costs, with breaches_total; the confidence
--   flag still covers them all;
-- - suggestions: per dish and location in scope, the latest row evaluated in the window, while it
--   is open or pending, an open one only if no acted-on row of its episode holds it back
--   (app.suggestion_reopens) and only while fresh (as_of on or after the dish's latest snapshot and
--   under a week old), its current price is still the menu price today and the dish's
--   latest snapshot in the window still breaches (a price changed or a cost that came back makes
--   it moot). The app.cost_alerts_top_n() highest food costs, highest first, with
--   suggestions_total. Prices with IVA; `change` is the suggested price vs the current one.
create or replace function api.get_cost_alerts(since jsonb default '"last_7d"', location_id uuid default null) returns jsonb
language plpgsql stable security invoker set search_path = ''
as $$
declare
  locs uuid[] := app.scope_locations(location_id);
  today date;
  r date[];
  w_to date;
  top_n int := app.cost_alerts_top_n();
  moves jsonb;
  moves_total int;
  breaches jsonb;
  breaches_total int;
  suggestions jsonb;
  suggestions_total int;
  levels app.cost_confidence[];
  flags jsonb := '[]';
  breach_above numeric := app.food_cost_target() + (select s.breach_pts from app.cost_alert_settings() s);
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

  with moved as (
    select i.name, i.base_unit, cur.unit_price_net as new_price, j.started,
           100 * (cur.unit_price_net - coalesce(nullif(pre.unit_price_net, 0), j.first_old))
             / coalesce(nullif(pre.unit_price_net, 0), j.first_old) as change_pct
    from (select x.ingredient_id, max(x.started) as started,
                 (array_agg(x.old_unit_price order by x.started))[1] as first_old
          from app.price_jumps((select app.current_tenant_id()), r[1], w_to) x
          group by x.ingredient_id) j
    join public.ingredient i on i.id = j.ingredient_id
    cross join lateral app.price_of_record(j.ingredient_id, w_to) cur
    left join lateral app.price_of_record(j.ingredient_id, r[1] - 1) pre on true
    where cur.unit_price_net > 0
  ), ranked as (
    select m.*, row_number() over (order by abs(m.change_pct) desc, m.name) as n
    from moved m
    where abs(m.change_pct) >= (select s.jump_vs_avg_pct from app.cost_alert_settings() s)
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'ingredient', m.name,
           'change', app.pct(m.change_pct, true),
           'new_unit_price', jsonb_build_object('raw', trim_scale(m.new_price), 'base_unit', m.base_unit,
                                                'text', app.price_text(m.new_price, m.base_unit)))
         order by m.started, m.name) filter (where m.n <= top_n), '[]'),
         count(*)
  into moves, moves_total
  from ranked m;

  with latest as (
    select distinct on (s.menu_item_id, s.location_id) s.menu_item_id, s.cost, s.price_net, s.confidence
    from public.dish_cost_snapshot s
    where s.location_id = any (locs) and s.date between r[1] and w_to and s.price_net > 0
    order by s.menu_item_id, s.location_id, s.date desc
  ), worst as (
    select distinct on (l.menu_item_id) l.menu_item_id, 100.0 * l.cost / l.price_net as fc, l.confidence
    from latest l order by l.menu_item_id, 100.0 * l.cost / l.price_net desc
  ), ranked as (
    select b.*, m.name, row_number() over (order by round(b.fc, 4) desc, m.name, b.menu_item_id) as n
    from worst b join public.menu_item m on m.id = b.menu_item_id
    where b.fc > breach_above
  )
  -- the top N by food cost; the confidence covers every breach, listed or not
  select coalesce(jsonb_agg(jsonb_build_object('menu_item_id', b.menu_item_id, 'name', b.name,
                                               'food_cost', app.pct(b.fc), 'target', app.pct(app.food_cost_target()))
                            order by b.n) filter (where b.n <= top_n), '[]'),
         count(*),
         array_agg(distinct b.confidence)
  into breaches, breaches_total, levels
  from ranked b;

  with shown as (
    select x.*, m.name
    from (
      select distinct on (p.location_id, p.menu_item_id) p.*
      from public.price_suggestion p
      where p.location_id = any (locs) and p.as_of between r[1] and w_to
      order by p.location_id, p.menu_item_id, p.as_of desc, p.id desc
    ) x
    join public.menu_item m on m.id = x.menu_item_id
    where x.status in ('open', 'pending')
      and (x.status = 'pending' or not exists (
             select 1 from public.price_suggestion d
             where d.tenant_id = x.tenant_id and d.location_id = x.location_id and d.menu_item_id = x.menu_item_id
               and d.status <> 'open' and d.episode_start >= x.episode_start
               and not app.suggestion_reopens(d.current_price, d.suggested_price, x.current_price, x.suggested_price)))
      -- an open row only while fresh: evaluated on or after the dish's latest snapshot (the evaluator
      -- ran since) and within the writer's observation week (a dish no longer costed shows nothing)
      and (x.status = 'pending' or (
             x.as_of > w_to - (select k.observation_days from app.price_suggestion_settings() k)
             and x.as_of >= (select max(s.date) from public.dish_cost_snapshot s
                             where s.location_id = x.location_id and s.menu_item_id = x.menu_item_id
                               and s.date <= w_to)))
      and x.current_price = app.menu_price_on(x.menu_item_id, x.location_id, w_to)
      and (select 100.0 * s.cost / s.price_net > breach_above
           from public.dish_cost_snapshot s
           where s.location_id = x.location_id and s.menu_item_id = x.menu_item_id
             and s.date between r[1] and w_to and s.price_net > 0
           order by s.date desc limit 1)
  ), ranked as (
    select x.*, row_number() over (order by x.value desc, x.name, x.location_id) as n from shown x
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'menu_item_id', x.menu_item_id,
           'location_id', x.location_id,
           'name', x.name,
           'current_price', app.money(x.current_price),
           'target_price', app.money(x.target_price),
           'suggested_price', case when x.suggested_price is not null then app.money(x.suggested_price) end,
           'change', case when x.suggested_price is not null
                          then app.pct(100.0 * (x.suggested_price - x.current_price) / x.current_price, true) end,
           'new_food_cost', case when x.new_food_cost_pct is not null then app.pct(x.new_food_cost_pct) end,
           'confidence', x.confidence,
           'rationale_code', x.rationale_code)
         order by x.n) filter (where x.n <= top_n), '[]'),
         count(*)
  into suggestions, suggestions_total
  from ranked x;

  if breaches <> '[]' then
    flags := flags || app.confidence_flag(levels);
  end if;
  return app.rpc_ok(
    jsonb_build_object('price_moves', moves, 'price_moves_total', moves_total, 'breaches', breaches,
                       'breaches_total', breaches_total, 'suggestions', suggestions,
                       'suggestions_total', suggestions_total),
    locs, flags, null, array[r[1], w_to]);
exception when sqlstate '22023' then
  return app.rpc_error('invalid_args', sqlerrm, coalesce(locs, '{}'));
end
$$;

-- Privileges ---------------------------------------------------------------------------------
-- get_menu_engineering runs as the caller and needs the quadrant rule; get_cost_alerts the list size,
-- the sticky rule and the observation week (settings). The writer, the formula and their helpers are the backend's (service_role),
-- called from the evaluator.
revoke all on function app.price_suggestion_settings(), app.price_point(numeric, boolean),
  app.suggest_menu_price(bigint, bigint, numeric, numeric), app.is_resale(uuid, date),
  app.menu_quadrants(uuid[], date, date), app.write_price_suggestions(uuid, date), app.cost_alerts_top_n(),
  app.breach_episode_start(uuid, uuid, uuid, date, numeric), app.menu_price_steady(uuid, uuid, date, date),
  app.suggestion_reopens(bigint, bigint, bigint, bigint)
  from public, anon, authenticated;
grant execute on function app.menu_quadrants(uuid[], date, date), app.cost_alerts_top_n(),
  app.suggestion_reopens(bigint, bigint, bigint, bigint), app.price_suggestion_settings() to authenticated, service_role;
grant execute on function app.price_point(numeric, boolean),
  app.suggest_menu_price(bigint, bigint, numeric, numeric), app.is_resale(uuid, date),
  app.write_price_suggestions(uuid, date), app.item_cost_rows(uuid[], date, date),
  app.breach_episode_start(uuid, uuid, uuid, date, numeric), app.menu_price_steady(uuid, uuid, date, date),
  app.net_ex_iva(numeric, numeric), app.menu_price_row(uuid, uuid, date)
  to service_role;
