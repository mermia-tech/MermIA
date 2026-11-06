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
-- - Resale items (U2: bottled drinks; Coca-Cola, Corona) keep their breach alerts but never get a
--   suggestion. The schema has no resale flag, so the narrowest signal is used: the dish's recipe
--   of record is a single line, an ingredient bought by the piece (`pza`) with no sub-recipe; it
--   is bought and sold as is. (menu_item.kind = 'drink' is wider: it holds micheladas and coffee.)
-- - Menu engineering (U4, 03 Kasavana-Smith over the location's last 30 days, the rule of
--   api.get_menu_engineering): plowhorses get a price (raise_to_target or raise_capped); stars are
--   not raised (no row); puzzles and dogs get review_portion_cost ("revisa porción/costo") and no
--   price. A dish not sold in those 30 days has no quadrant and gets nothing.
-- - Confidence: the snapshot's (the engine's rule: confirmed = every recipe confirmed and every
--   price from a CFDI, or a confirmed nota, under 30 days old; else estimated).
-- - One row per (tenant, location, dish, day evaluated); a rerun refreshes an open row only when
--   its figures changed. api.get_cost_alerts shows each dish's latest row in the window while it
--   is open or pending, its current price is still the menu price and the dish still breaches.

-- Columns ------------------------------------------------------------------------------------
-- The free-text subject (MR-10) is replaced by the dish; nothing wrote it.
alter table public.price_suggestion drop column subject;
drop function app.subject_item(text, uuid[], date);

alter table public.price_suggestion
  add column menu_item_id uuid,
  add column as_of date,
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
      and value is not null and threshold is not null and current_price > 0 and target_price > 0
      and confidence in ('confirmed', 'estimated') and (
        (rationale_code = 'raise_to_target' and suggested_price > current_price and suggested_price >= target_price
          and new_food_cost_pct is not null)
        or (rationale_code = 'raise_capped' and suggested_price > current_price and suggested_price < target_price
          and new_food_cost_pct is not null)
        or (rationale_code = 'review_portion_cost' and suggested_price is null and new_food_cost_pct is null)), false));

create unique index price_suggestion_key on public.price_suggestion (tenant_id, location_id, menu_item_id, as_of);
create index price_suggestion_menu_item_idx on public.price_suggestion (tenant_id, menu_item_id);
select app.tag('public.price_suggestion', 'unit=centavos', array['current_price', 'target_price']);
select app.tag('public.price_suggestion', 'unit=percent_points', array['new_food_cost_pct']);
comment on column public.price_suggestion.rule is 'margin_breach (price_suggestion_shape)';
comment on column public.price_suggestion.status is 'open | pending | applied | dismissed (price_suggestion_status_known)';
comment on column public.price_suggestion.rationale_code is
  'raise_to_target | raise_capped | review_portion_cost (price_suggestion_shape)';
comment on column public.price_suggestion.value is 'percent points: the food cost on as_of';
comment on column public.price_suggestion.threshold is 'percent points: the breach line (target + 3 pts)';

-- Settings -----------------------------------------------------------------------------------
-- U4 defaults; one place to calibrate them in the pilot. Prices in centavos.
create function app.price_suggestion_settings(
  out max_step_pct numeric, out small_point bigint, out large_point bigint, out large_from bigint,
  out observation_days int)
language sql immutable set search_path = ''
as $$ select 10.0, 500::bigint, 1000::bigint, 25000::bigint, 7 $$;

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

-- U2: a dish bought and sold as is (its recipe of record on the day is one line, an ingredient
-- counted by the piece).
create function app.is_resale(item uuid, on_date date) returns boolean
language sql stable set search_path = ''
as $$
  select count(*) = 1 and coalesce(bool_and(l.sub_recipe_id is null and i.base_unit = 'pza'), false)
  from public.recipe_line l
  left join public.ingredient i on i.id = l.ingredient_id
  where l.recipe_id = app.recipe_of_record(item, null, on_date)
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

-- As in 20261104090000_read_rpcs_cost.sql, on app.menu_quadrants. Same output.
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
-- Writes the tenant's suggestions for one business day; returns how many rows it added or
-- refreshed. Idempotent: a rerun on unchanged data writes nothing. An acted-on row (not open) is
-- never touched.
create function app.write_price_suggestions(tenant uuid, on_date date) returns int
language plpgsql set search_path = ''
as $$
declare
  k record;
  a record;
  breach_above numeric;
  written int;
begin
  if tenant is null or on_date is null then
    raise exception 'tenant and on_date are required' using errcode = '22023';
  end if;
  select * into k from app.price_suggestion_settings();
  select * into a from app.cost_alert_settings();
  breach_above := app.food_cost_target() + a.breach_pts;

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
    select cur.location_id, cur.menu_item_id, cur.date, cur.cost, cur.confidence,
           round(100.0 * cur.cost / cur.price_net, 4) as food_cost
    from obs cur
    join obs prev on prev.location_id = cur.location_id and prev.menu_item_id = cur.menu_item_id and prev.n = 1
    where cur.n = 0
      and 100.0 * cur.cost / cur.price_net > breach_above and 100.0 * prev.cost / prev.price_net > breach_above
      and cur.confidence in ('confirmed', 'estimated')
      and not app.is_resale(cur.menu_item_id, cur.date)
  ), quadrant as (
    select l.location_id, q.menu_item_id, q.quadrant
    from (select distinct b.location_id from breaching b) l
    cross join lateral app.menu_quadrants(array[l.location_id], on_date - (a.ranking_days - 1), on_date) q
  ), proposal as (
    select b.*, mp.price_gross, f.target_price, f.suggested_price, f.new_food_cost_pct,
           case when q.quadrant in ('puzzle', 'dog') then 'review_portion_cost'
                when q.quadrant = 'plowhorse' and f.suggested_price >= f.target_price then 'raise_to_target'
                when q.quadrant = 'plowhorse' and f.suggested_price is not null then 'raise_capped'
           end as rationale_code
    from breaching b
    join quadrant q on q.location_id = b.location_id and q.menu_item_id = b.menu_item_id
    cross join lateral app.menu_price_row(b.menu_item_id, b.location_id, b.date) mp
    cross join lateral app.suggest_menu_price(b.cost, mp.price_gross, mp.tax_rate, app.food_cost_target()) f
  )
  insert into public.price_suggestion as p
    (tenant_id, location_id, menu_item_id, as_of, rule, value, threshold, current_price, target_price,
     suggested_price, new_food_cost_pct, confidence, rationale_code)
  select tenant, x.location_id, x.menu_item_id, on_date, 'margin_breach', x.food_cost, breach_above,
         x.price_gross, x.target_price,
         case when x.rationale_code <> 'review_portion_cost' then x.suggested_price end,
         case when x.rationale_code <> 'review_portion_cost' then x.new_food_cost_pct end,
         x.confidence, x.rationale_code
  from proposal x
  where x.rationale_code is not null
  on conflict (tenant_id, location_id, menu_item_id, as_of) do update
    set value = excluded.value, threshold = excluded.threshold, current_price = excluded.current_price,
        target_price = excluded.target_price, suggested_price = excluded.suggested_price,
        new_food_cost_pct = excluded.new_food_cost_pct, confidence = excluded.confidence,
        rationale_code = excluded.rationale_code
    where p.status = 'open'
      and (p.value, p.threshold, p.current_price, p.target_price, p.suggested_price, p.new_food_cost_pct,
           p.confidence, p.rationale_code)
          is distinct from (excluded.value, excluded.threshold, excluded.current_price, excluded.target_price,
                            excluded.suggested_price, excluded.new_food_cost_pct, excluded.confidence,
                            excluded.rationale_code);
  get diagnostics written = row_count;
  return written;
end
$$;

-- Evaluator ----------------------------------------------------------------------------------
-- As in 20261106100000_cost_alerts.sql, plus the day's price suggestions (written after the
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
         e.started > today - k.fresh_days
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

  perform app.write_price_suggestions(tenant, on_date);
  return jumps + breaches;
end
$$;

-- get_cost_alerts with the suggestions -------------------------------------------------------
-- As in 20261106100000_cost_alerts.sql, except suggestions: per dish and location in scope, the
-- latest row evaluated in the window, while it is open or pending, its current price is still the
-- menu price today and the dish's latest snapshot in the window still breaches (a price changed or
-- a cost that came back makes it moot). Highest food cost first. Prices with IVA; `change` is the
-- suggested price vs the current one.
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

  select coalesce(jsonb_agg(jsonb_build_object(
           'ingredient', m.name,
           'change', app.pct(m.change_pct, true),
           'new_unit_price', jsonb_build_object('raw', trim_scale(m.new_price), 'base_unit', m.base_unit,
                                                'text', app.price_text(m.new_price, m.base_unit)))
         order by m.started, m.name), '[]')
  into moves
  from (
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
  ) m
  where abs(m.change_pct) >= (select s.jump_vs_avg_pct from app.cost_alert_settings() s);

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
                   where b.fc > breach_above), '[]'),
         (select array_agg(distinct b.confidence) from worst b where b.fc > breach_above)
  into breaches, levels;

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
         order by x.value desc, x.name, x.location_id), '[]')
  into suggestions
  from (
    select distinct on (p.location_id, p.menu_item_id) p.*, m.name
    from public.price_suggestion p
    join public.menu_item m on m.id = p.menu_item_id
    where p.location_id = any (locs) and p.as_of between r[1] and w_to
    order by p.location_id, p.menu_item_id, p.as_of desc
  ) x
  where x.status in ('open', 'pending')
    and x.current_price = app.menu_price_on(x.menu_item_id, x.location_id, w_to)
    and (select 100.0 * s.cost / s.price_net > breach_above
         from public.dish_cost_snapshot s
         where s.location_id = x.location_id and s.menu_item_id = x.menu_item_id
           and s.date between r[1] and w_to and s.price_net > 0
         order by s.date desc limit 1);

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
-- get_menu_engineering runs as the caller and needs the quadrant rule. The writer, the formula
-- and their helpers are the backend's (service_role), called from the evaluator.
revoke all on function app.price_suggestion_settings(), app.price_point(numeric, boolean),
  app.suggest_menu_price(bigint, bigint, numeric, numeric), app.is_resale(uuid, date),
  app.menu_quadrants(uuid[], date, date), app.write_price_suggestions(uuid, date)
  from public, anon, authenticated;
grant execute on function app.menu_quadrants(uuid[], date, date) to authenticated, service_role;
grant execute on function app.price_suggestion_settings(), app.price_point(numeric, boolean),
  app.suggest_menu_price(bigint, bigint, numeric, numeric), app.is_resale(uuid, date),
  app.write_price_suggestions(uuid, date), app.item_cost_rows(uuid[], date, date),
  app.net_ex_iva(numeric, numeric), app.menu_price_row(uuid, uuid, date)
  to service_role;
