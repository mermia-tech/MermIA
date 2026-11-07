# MR-34 build_weekly_report RPC Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** one read-only RPC returns everything the weekly report needs; MR-38 (p0sin) renders and sends it.

**Architecture:** one SQL function `api.build_weekly_report` on top of PR #94 (`20261106110000_price_suggestions.sql`) that composes the existing read RPCs (`get_sales_summary`, `get_top_dishes`, `get_food_cost_pct`, `get_cost_alerts`, `get_data_status`) for one Monday–Sunday week. Its contract lives in a new `REPORT_RPCS` registry, not in `RPCS`, so the 12 agent tools and the cached prompt prefix do not change.

**Tech Stack:** Postgres 17 (Supabase), pgTAP, Pydantic v2, pytest + psycopg, FastAPI mock.

**Spec:** `docs/kickoff/12-*` section 1 (the `reporte_semanal` template and `Ver márgenes`); `docs/kickoff/09-architecture.md` section 4.1 (read RPCs); `docs/kickoff/13-*` (compact tool results).

## User decisions (final, 2026-11-06)

- **W1 Recipients:** owner only, one whole-business report (doc 12); `[Por sucursal]` calls `compare_locations`. Location managers get no weekly report in the pilot. The RPC still honours `location_id` and RLS, so a manager call returns only their location.
- **W2 Week:** Monday–Sunday; sent Monday 9:00 local; if Sunday's upload is missing, retry 12:00, then send anyway noting the missing day. Scheduling is MR-38; the RPC exposes `missing_business_days` for the week.
- **W3 Comparison:** previous week only.
- **W4 Sections:** main template = sales, % vs last week, tickets, average ticket, top dish, number of dishes over target (no suggestions). `[Ver márgenes]` = top 3 breaches with suggestions + "Son sugerencias, no cambio nada sin tu OK". `[Ver detalle]` = price moves, food cost vs 32 % with coverage, missing days. No "pesos encontrados" for now.

## Design

- **Contract** (`packages/contracts/src/mermia_contracts/rpc.py`): `BuildWeeklyReportArgs(period="last_week", location_id=None)`; `period` is `last_week`, `prev_week` or an explicit `{from, to}` that is Monday–Sunday. `WeeklyReportData` reuses the existing shapes: `week`, `previous_week`, `sales: SalesSummaryData` (with `change_vs_previous` vs the previous week), `top_dishes: TopDishesData` (top 3 by units), `food_cost: FoodCostData | None`, `cost_alerts: CostAlertsData` (top 10 with `*_total`), `missing_business_days` (in the week), `stale_costs`. Dishes over target = `cost_alerts.breaches_total`.
- **Registry:** `REPORT_RPCS = {"build_weekly_report": ...}` and `ALL_RPCS = RPCS | REPORT_RPCS`. `RPCS` still generates the 12 agent tools; `MetricCardMsg` still accepts agent RPCs only.
- **Generated:** `export_schemas` loops over `ALL_RPCS` (`schemas/rpc.build_weekly_report.{args,response}.json`); the mock serves `ALL_RPCS`; the example `tests/examples/rpc/build_weekly_report.json` is copied from the live SQL on the seed (after the backend's cost job and the alert evaluation of 2026-10-12).
- **Migration** `20261106120000_weekly_report.sql`: `api.build_weekly_report(period jsonb default '"last_week"', location_id uuid default null) returns jsonb`, security invoker, read-only. It calls the section RPCs with the explicit week, `get_cost_alerts(since => week)`, lists the week's missing business days (up to yesterday), merges the section flags without duplicates and takes `coverage_pct` from sales.
- **Errors:** an invalid week or an unknown location is one error envelope; a section error is one error envelope naming the section, except two `no_data` cases that must not block the Monday message: no dish sales gives `top_dishes.rows = []`, no costed sales gives `food_cost = null`. No sales at all is `no_data`.
- **SQL, not Python:** same RLS path as the other RPCs, one round trip, reusable by the dashboard, pgTAP-testable.

## Tasks

- [ ] **1. Contract and mock (commit 1, unblocks MR-38).** Tests first: `test_weekly_report_contract.py` (args accept `last_week` / `prev_week` / a Monday–Sunday range, reject other names and ranges; data rejects a week that is not Monday–Sunday, a previous week that is not the week before, top dishes not by units or over 3, missing days outside the week); `test_rpc_contract.py` (REPORT_RPCS apart from RPCS, examples of ALL_RPCS parse); `test_metric_card.py` (agent RPC examples only, a weekly report is not a card); mock tests (served, valid, fixed answer). Then the models, `ALL_RPCS`, `export_schemas`, mock `rpcs.py` / `app.py`, the example JSON and the schemas.
- [ ] **2. SQL (commit 2).** Tests first: pgTAP `supabase/tests/99_weekly_report.test.sql` (other tenant nothing; manager only their location; each section equals its own RPC's data; invalid weeks; no rows written; runs as authenticated) and `packages/contracts/tests/test_rpc_db_weekly.py` (`-m db`). Update `50_exposure` (11 -> 12 api RPCs). Then the migration.
- [ ] **3. Checks.** `.claude/skills/check/check.sh`, `supabase test db`, `MERMIA_DB_URL=... uv run pytest -q --tb=short -m db`, `uv run python -m mermia_contracts.tools.export_schemas --check`, `test_agent_tools` still 12 tools.

## Done when

- pytest `packages/contracts/tests/test_rpc_db_weekly.py` (-m db) validates against `RpcEnvelope[WeeklyReportData]` for the owner, the Polanco manager and another tenant; `last_week` with today = 2026-10-12: net sales 34,524,130 (Centro 18,432,050 + Polanco 16,092,080), about +3.5 % vs the previous week (33,352,460); the week of 2026-09-28 shows the aguacate jump; the mock example equals the live output.
- pgTAP `supabase/tests/99_weekly_report.test.sql`: other tenant nothing; manager only their location; each section equals its own RPC's data; no rows written; runs as authenticated. `50_exposure` lists 12 api RPCs; mock tests cover the new RPC.
- `export_schemas --check` passes; `test_agent_tools` still 12 tools; `/check` green.

## Risks / notes for MR-38

- `get_cost_alerts` looks from the period start to today, and suggestions show only while under a week old, so re-running an old week does not reproduce what was sent: MR-38 should store the sent payload in `report_run`.
- Doc 12 sample numbers are made up; tests pin the seed's figures.
- The MR-38 issue says suggestions go behind `Ver detalle`; decision W4 puts them behind `Ver márgenes`.
- Doc 13's ~400-token cap is for agent tool results; the report goes to code, but stays compact via top-N + `*_total`.
