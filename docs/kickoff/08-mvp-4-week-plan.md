# 08 - MVP 4-week plan (to a live pilot)

Date: 2026-10-15. This plan builds the architecture in `09-architecture.md`. Facts carry labels and come from 01, 03, 04 and 13. Scope cuts and estimates are **opinion**.

## Summary

- **Go-live target: day 16 (Monday of week 4)**, with one pilot restaurant (one location, or two if it is a small chain). Week 4 runs live with daily fixes. The pilot is judged after 4 more weeks (criteria at the end).
- **Two tracks.** Dev A owns *data* (schema, ingestion, costing, metrics RPCs, apply functions). Dev B owns *conversation* (WhatsApp, agent, eval and LLM selection, confirmations, reports delivery, metering).
- **Contracts are frozen at the end of day 2.** Both devs then build against fixtures and mocks, and integrate on day 10.
- **The eval gate:** the 40-question LLM eval (13 H3) runs against mock tools on days 4-5. Agent work starts only after it passes.

## Week 0 / day 1: long-lead items (start immediately)

| # | Task | Owner | Why now | Label |
|---|---|---|---|---|
| 1 | Create the Meta Business portfolio and **start Business Verification** (RFC constancia + proof of address matching the legal name exactly) | founders | Takes days to weeks; maximum 3 attempts | **likely** timing (04) |
| 2 | Get a dedicated +52 number, register it on the Cloud API, set the 2FA PIN, add a payment method, choose the billing currency deliberately (cannot change later) | Dev B | Without a payment method, service messages stop after 1,000 | **verified** (04) |
| 3 | Pilot restaurant, collect: SR version and edition; whether Analytics / Corte Z email / WhatsApp is active; **sample exports** (Productos vendidos, Ventas por día, Cuentas desglose, Corte Z, Recetas) for 2-4 recent weeks; menu with prices; top suppliers (CFDI vs notas); current food-cost target | founders | Parsers cannot be built blind; report columns for SR 10-12 are **unverified** (01) | - |
| 4 | Pilot: send those exports **from the manager's phone to a test WhatsApp number** (xlsx, xls, pdf, and a CFDI .xml) on iOS and Android | Dev B | CSV/XML delivery is **unverified** (04) | - |
| 5 | Ask the pilot's SR distributor for the **ERP/PMS module price** and lead time; send the "Quiero integrar mi sistema" form | founders | Long-term ingestion route (09 section 10) | module price **unverified** (01) |
| 6 | Get the SR licence/EULA text from the pilot; book a lawyer for the aviso de privacidad, data-processing (encargado) clause and pilot agreement | founders | Needed before real data is processed (notes 2) | - |
| 7 | Create the Anthropic account (Start tier), Supabase org (Pro), Render or Fly account, Sentry, Langfuse, GitHub repo + CI | Dev A / Dev B | - | - |
| 8 | Submit the WhatsApp templates (es_MX, utility, neutral wording): `reporte_semanal`, `reporte_diario`, `recordatorio_reporte`, `cambio_pendiente` (3 buttons), `reporte_recibido`, `cambio_resuelto`; 2-3 variants each | Dev B | Up to 24 h review; check the category Meta assigns | **verified** (04) |

If pilot samples are late, Dev A builds the fixtures from the SR 8 manual's report descriptions and swaps in the real files when they arrive. This is a risk: parser rework in week 2.

## Days 1-2: contracts (both devs, pairing)

Everything lives in `packages/contracts`. A change after day 2 needs a PR approved by both devs (CODEOWNERS).

| Contract | Content | Primary author |
|---|---|---|
| C1 Normalized schema v1 | SQL migrations for 09 sections 2.1-2.5 (tables, enums, RLS policies), as DDL plus generated Pydantic models | Dev A |
| C2 `NormalizedBatch` v1 | Pydantic model (09 section 3); the parser output format | Dev A |
| C3 Metric RPC interfaces | The 11 read RPCs in 09 section 4.1: name, args, response JSON with formatted and raw values, flags, envelope; 1-2 example responses each | Dev A writes, Dev B reviews |
| C4 Agent tool definitions | 12 tools as JSON Schema generated from C3 Pydantic models; one-line descriptions; ≤125 tokens each, measured with `count_tokens` | Dev B writes, Dev A reviews |
| C5 `PendingChange` kinds | `ingredient_price.set`, `recipe.upsert`, `menu_item_price.set`, `import_batch.approve`, `import_batch.rollback`; payload schemas; `apply_pending_change(id, user_id)` signature and result codes | Dev A + B |
| C6 `AgentRequest` / `AgentResponse` | 09 section 4.3 | Dev B |
| C7 Fixtures | "Taquería El Güero" (13 H3): 2 locations, 8 weeks of item-daily sales, about 40 menu items, about 60 ingredients, recipes for the top 15, 3 suppliers, 2 price jumps, 1 cancellation-heavy Saturday. Delivered as SQL seed, JSON files and **mock RPC responses generated from the seed** | Dev A (seed), Dev B (mock server) |
| C8 Sample SR exports | Pilot files in `fixtures/sr/<version>/`, each paired with an expected `NormalizedBatch` golden JSON (start with 2 report types) | Dev A |

Exit of day 2: contracts merged on `main`. The mock RPC server (`apps/mock-rpc`, serving C7 data in the C3 shapes) runs locally. A contract test is in CI: real RPC output must parse with the C3 Pydantic models.

## Ownership

| Area | Dev A (data) | Dev B (conversation) |
|---|---|---|
| Database | migrations, RLS, pgTAP tests, seed | - |
| Ingestion | parser registry, SR parsers, batch loader, `apply_batch` / `rollback_batch`, dedup, validation, issue messages (es-MX text supplied to B) | WhatsApp media download → `raw_file`; email inbox transport (week 3) |
| Costing | ingredients, units, recipes, prices, `dish_cost_snapshot`, alert rules, price-suggestion formula (03) | recipe capture conversation (chat → `propose_change`) |
| Metrics | the 11 RPCs, `daily_location_metrics` | templates that render RPC results |
| Agent | - | router, templates, LLM gateway (routing, caps, `llm_usage`), broker loop, number validator, memory |
| LLM selection | reviews eval expectations against fixture numbers | eval harness, 40 questions, runs, decision memo |
| Confirmations | `apply_pending_change`, version and role checks, audit triggers | confirmation service, buttons, expiry job, replies |
| Reports | `build_weekly_report(location_id, period)` RPC returning the data | scheduling (Procrastinate), template send, follow-up detail |
| Onboarding, ops | tenant/user admin script | opt-in flow, aviso link, `message_log`, Sentry, deploy |

## Week by week

| Week | Dev A | Dev B | Sync point (end of week) |
|---|---|---|---|
| **1** (days 1-5) | D1-2 contracts. D3-5: migrations + RLS + pgTAP on 2 tenants; parser for "Productos vendidos" against the pilot sample (golden test); `apply_batch` / `rollback_batch`; first 4 RPCs (`get_sales_summary`, `compare_periods`, `get_top_dishes`, `get_data_status`) | D1-2 contracts. D3: mock RPC server, eval harness (provider adapter for Anthropic, OpenAI, Google; scorer). D3-4: write 40 questions with expected tools, args and numbers from fixtures. D4-5: **run the eval** on Haiku 5.5, Sonnet 5.5, GPT-6 Luna, Gemini 3.5 Flash-Lite (+ gpt-oss-120b) × 3 runs. WhatsApp webhook skeleton: 200 + enqueue, idempotent, media download | **Day 5 gate:** eval results → routing table fixed (13 H4) and decision recorded in `docs/decisions/llm.md`. Real pilot file parses to a batch. Test number receives a file end to end into `raw_file` |
| **2** (days 6-10) | Parsers 2-3 ("Ventas por día" or Corte Z, "Recetas" if the pilot has recipes). Remaining RPCs (`get_dish_margin`, `get_food_cost_pct`, `get_sales_breakdown`, `get_cancellations`, `compare_locations`, `get_menu_engineering`, `get_cost_alerts`). Costing engine + recipe spreadsheet template importer | Router + templates for the top ~8 questions; broker loop with cached prefix; number validator; memory; caps; `llm_usage`. Upload flow messages: received / summary / issues / Deshacer button. Identity mapping, roles, opt-in with aviso link | **Day 10 integration:** Dev B switches from the mock server to real RPCs on staging (same fixtures); contract tests green; eval re-run against real RPCs (no regressions) |
| **3** (days 11-15) | `apply_pending_change` for the 5 kinds; recompute jobs; alert rules + price suggestions; `build_weekly_report`; load pilot history (2-4 weeks of exports), recipes for the top 10 dishes, ingredient prices. Stretch: CFDI XML parser | Confirmation service + sequence (09 section 5.2), expiry, conflict handling; weekly report job + "Ver detalle" follow-up with suggestions; missed-upload reminder; email inbox transport (if Corte Z email or CFDI is in use). Production deploy, Sentry, alerts | **Day 15 dress rehearsal:** both devs plus a founder role-play owner and manager on production with pilot data. Run the manual test script (below). Go/no-go |
| **4** (days 16-20) | Live. Fix parser edge cases from real uploads within 24 h; cross-check our totals against the pilot's SR report every day | Live. Daily review of `llm_usage`, `message_log`, validator rejects, unanswered questions → new templates or tools | **Day 20 review:** first-week metrics vs success criteria; backlog for Phase 1b |

Dependencies:
- B's agent needs C3/C4 (day 2) and the mock server (day 3), not A's real RPCs.
- A's issue messages need B's send function (week 2); until then they are logged.
- B's confirmation flow needs A's `apply_pending_change` by day 13. Until then B uses a stub that writes `audit_log` only.
- The real pilot exports block A's parsers, not B.

## Avoiding blocking

| Practice | Detail |
|---|---|
| Fixtures first | One fixture restaurant is the shared truth for evals, mocks, pgTAP and parser tests |
| Mock RPC server | Generated from the seed through the real SQL when available; hand-written JSON before that; validated by the same Pydantic models |
| Contract tests in CI | Real RPC responses must parse with the C3 schemas; tool schemas must stay under the token budget |
| Golden files | Each SR sample export has an expected `NormalizedBatch`; a parser change that alters golden output needs review |
| Branching | Trunk-based: short branches (≤1 day), PR to `main`, the other dev reviews the same day; PRs under about 400 lines; migrations numbered and only appended; `packages/contracts` changes need both approvals; squash merge |
| Environments | Local Supabase (CLI) per dev; one shared staging project; production from week 3 |
| Daily sync | 15 min each morning: blockers, contract changes, what lands today |
| Eval in CI | A subset of 10 questions runs on every prompt, tool-schema or model change (about US$0.30); the full 40 runs nightly in week 2-4 (13 I4) |

## MVP scope

**In:**

| Feature | Notes |
|---|---|
| Upload SR xlsx/xls by WhatsApp (2-3 report types), dedup, validation, summary reply, Deshacer | Photos get "por favor mándame el archivo" (no OCR) |
| Email inbox for Corte Z or CFDI (only if the pilot uses it) | Same parsers |
| Recipes and costs for the **top 10 dishes** | From the SR "Recetas" export (Case 1) or a spreadsheet template filled with our help (Case 2); prices via chat `propose_change` or CFDI (stretch) |
| Owner Q&A in WhatsApp | Templates for the top questions + Haiku/Sonnet with the 12 tools; number validator; confidence tag on every cost figure |
| Weekly report (utility template, Monday morning) | 04 recommends weekly as the default; the daily summary is an opt-in from Phase 1b (07), its template is submitted in week 0 |
| Margin alerts and price suggestions in the weekly follow-up | Rules in code (03); never auto-applied |
| Confirmation flow for the 5 change kinds | Buttons, 24 h expiry, audit log |
| Roles: owner, manager, support | Set up by our admin script (concierge onboarding) |
| Cost metering (`llm_usage`, `message_log`) and per-tenant caps | From day 1 |

**Out (explicitly):** dashboard; local connector; ERP/PMS push (unless the pilot already owns the module; even then it waits for Phase 1b); photo/nota OCR; SAT descarga masiva; SNIIM benchmarks; inventory and actual cost; self-serve sign-up and billing; voice notes; multi-language; changing prices inside SR; more than 2 locations; any custom report building.

## Manual test script (day 15, run by the devs)

1. Manager sends the real "Productos vendidos" xlsx → summary within 60 s, and the totals match SR's own screen.
2. The same file again → "ya lo recibí". A file from the wrong day → `needs_review` prompt. A photo → asks for the file.
3. Deshacer → the metrics revert; restore works.
4. Owner asks the 10 eval examples (13 H3) in their own words → correct numbers, ≤8 s each.
5. Owner says the meat price changed → pending change with a diff → Confirmar → food cost recomputed → audit row present. Rechazar and expiry paths also work.
6. Weekly report job sent manually → template delivered → "Ver detalle" → suggestions.
7. As a second tenant, try to read the pilot's data via the RPCs → nothing (RLS).
8. `llm_usage` and `message_log` rows exist for every step; cost per question ≤ US$0.003 on the Haiku route.

## Pilot success criteria (measured over 4 weeks after go-live)

| Area | Criterion |
|---|---|
| Data flow | Data received for ≥85% of business days; ≥95% of received files parsed without a dev touching them; median upload-to-confirmation ≤2 min |
| Accuracy | Our daily net sales match SR within ±0.5% on 100% of checked days; **zero** wrong numbers reported by the owner and confirmed by us; zero validator escapes |
| Engagement | Owner interacts on ≥3 days a week (question or button) in weeks 2-4; ≥80% of weekly reports opened (read receipts) |
| Value | Owner confirms at least one cost or price change through the flow; the owner can name one decision the product changed (interview) |
| Cost | LLM ≤ US$1.00 per month for the pilot tenant; WhatsApp billed cost reconciles with `message_log` within 5%; cache hit ≥80% |
| Commercial | Owner agrees to pay the proposed price after the pilot (verbal plus signed letter of intent) or gives a clear reason why not |

If data flow fails (manager discipline), move the ERP/PMS push or Corte Z email earlier in Phase 1b, before adding features.
