# MR-33 Cost alerts Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** deterministic rules flag ingredient price jumps and dish margin breaches (and, in part b, suggest menu prices). Nothing is ever auto-applied.

**Architecture:** one migration on top of PR #77 (`20261108090000_read_rpcs_cost.sql`: `app.food_cost_target`, `app.net_ex_iva`, `api.get_cost_alerts`) and MR-25 (`20261022090000_costing_engine.sql`). The rules live in SQL next to the costing engine: `app.price_jumps` is the one definition of a price jump, used by the evaluator and by `api.get_cost_alerts`; `app.evaluate_cost_alerts` (service_role only) writes `public.alert` rows idempotently; a thin Python caller in `apps/api/src/mermia_api/costing/alerts.py` runs it.

**Tech Stack:** Postgres 17 (Supabase), pgTAP, pytest + psycopg.

**Spec:** `docs/kickoff/03-data-ingestion-and-costing.md` ("Alert thresholds", "Price-suggestion formula"); `docs/kickoff/12-*` (sample messages); `fixtures/README.md` (the two seed price jumps).

## User decisions (final, 2026-11-06)

- **U1 Target and breach:** one fixed 32 % food-cost target per tenant (`app.food_cost_target()`); a breach is food cost above 35 % (target + 3 pts). Per-category targets later.
- **U2 Bottled drinks / resale items** (seed: Coca-Cola 54 %, Corona 46 %): alert as breaches, never a price suggestion (part b).
- **U3 Frequency:** compute daily, silently; everything goes into the weekly report; at most one same-day message per tenant, only for urgent alerts: an ingredient price jump of at least 15 % on a top-20-by-spend ingredient, or a breach on a top-10 dish. MR-33 marks urgency; sending is MR-37 / MR-38. Owner decision 2026-11-07: a breach is urgent only on a confirmed dish cost; one on an estimated cost is recorded (`alert.confidence`) and appears in the weekly report marked as estimated.
- **U4 Suggestions** (part b): round to $5 under $250 and $10 at or above; at most +10 % per step (cap rounded down to a price point); never a decrease; no suggestion if the cap lands on the current price; Stars not raised; Dogs and Puzzles get "revisa porción/costo" (a rationale code) instead of a price; copy always "Son sugerencias, no cambio nada sin tu OK" plus a confidence tag; "Cambiar precios" creates a `menu_item_price.set` pending change. Prices include IVA.

## Split

- **33a (this PR, no contract change):** alert columns and checks, `app.price_jumps`, `app.evaluate_cost_alerts`, `api.get_cost_alerts` on the shared jump rule, Python caller, tests.
- **33b (later, contract change, both devs approve):** `price_suggestion` columns, `app.suggest_menu_price`, U2 / U4 rules, `PriceSuggestion` contract fields (confidence, change, new_food_cost, target_price, rationale_code), example JSON, schemas.

## Technical calls (open to change, repeated in the PR)

- **Price jump** (03): the price of record changes on a day and either (a) the new price is at least 15 % away from the last price, or (b) the new price is at least 8 % away from the 30-day time-weighted average (the price of record on each of the 30 days before) on the side the price moved to, and either the last price was within 8 % of that average or the step itself is at least 8 % vs the last price (so a small move while the average still lags a jump is no jump, but a second step, e.g. pastor $170 -> $195 -> $215, is). Both directions; zero prices are never a jump. Only ingredients a live dish uses. The alert quotes the change that fired (vs the last price when (a) fires, else vs the average).
- **`get_cost_alerts` price moves:** ingredients with a jump that started in the window; `change` is from the price before the window to the price of record at its end (as #77), so a second step shows the whole move; a row under 8 % (a move since undone) is left out.
- **Top-20 filter:** applies to urgency only (U3); every jump of at least 8 % gets a normal alert for the weekly report.
- **Spend** for the top 20: theoretical usage over the 30 days to the evaluation day (units sold x recipe of record, through sub-recipes, x price of record), since purchases are only partly captured in Phase 1.
- **Top 10 dishes:** by net sales at the location over the same 30 days.
- **Dedupe:** a price jump is one alert per (tenant, ingredient, day the price started). A breach is one alert per episode: (tenant, location, dish, first day of the run of breaching snapshots); a breach that persists never re-alerts, one that ends and comes back does. `as_of` is that start day; `value` the change or food cost on it.
- **Urgent** only when the evidence is at most 7 days old, so a catch-up run over old days never triggers a same-day message.
- **Status** stays `open` until the owner acts (`acknowledged`, `dismissed`).
- Doc 03 formula divides by a fraction, but values are percent points: convert. Missing snapshot => no alert, never a guess. Stale-cost and mix-shift alerts later.

## Tasks

### Task 1: Tests first

- [x] `supabase/tests/97_cost_alerts.test.sql`: price_jump alerts for pastor 2026-09-21 and aguacate 2026-09-28; exactly the expected set on the seed for 2026-09-12..10-12; a rerun adds no duplicates; nothing for another tenant; urgent per U3; no change in pending_change and menu_item_price counts; the evaluator runs as service_role and not as authenticated; `api.get_cost_alerts` answers as before.
- [x] `apps/api/tests/costing/test_cost_alerts.py` (`-m db`): the Python caller over the seed window; `api.get_cost_alerts` still validates against `RpcEnvelope[CostAlertsData]`.
- [x] Run; expect FAIL (functions missing).

### Task 2: Migration and caller

- [x] `supabase/migrations/20261108090300_cost_alerts.sql` (after #77's `20261108090200`): alert columns (`menu_item_id`, `ingredient_id`, `as_of`, `urgent`, `confidence` (required for margin_breach), prices tagged `unit=pesos_per_base_unit`), rule / status / shape checks, dedupe indexes; `app.cost_alert_settings`, `app.price_jumps`, `app.ingredient_spend`, `app.evaluate_cost_alerts`; `api.get_cost_alerts` redefined on `app.price_jumps` with the same output.
- [x] `apps/api/src/mermia_api/costing/alerts.py`: `evaluate_cost_alerts(conn, tenant_id, as_of)` and a day-range catch-up.
- [x] `supabase db reset`, `supabase test db`, `uv run pytest -m db`; regenerate models (`--check`).

### Task 3: Checks and PR

- [x] `.claude/skills/check/check.sh` green.
- [x] Commit `MR-33: ...`, push, draft PR on `MR-24-read-rpcs` with decisions, technical calls and what part b adds.

## Done when (33a)

pgTAP `97_cost_alerts` and pytest `test_cost_alerts.py` pass; `/check` passes.
