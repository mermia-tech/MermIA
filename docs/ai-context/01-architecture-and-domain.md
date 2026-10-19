# 01 - Architecture and domain

Tags: **[CODE]** verified in repo, **[DOC]** documented decision, **[HYP]** needs confirmation, **[UNK]** unknown. See `00-overview-and-prompting.md`.

Rule for domain: a rule is "implemented" only if a constraint, policy, trigger or validator exists in code. Everything else is "pending".

---

# Architecture

## Stack

| Layer | Choice | Tag / evidence |
|---|---|---|
| Backend | Python 3.12, FastAPI, one always-on service on Render, `uv` | [DOC] `CLAUDE.md`, `docs/kickoff/09-architecture.md` §7. Code: only `/health` exists, on `origin/main` (`apps/api/src/mermia_api/main.py`) [CODE] |
| Contracts | Pydantic v2 (`pydantic>=2.11`) | [CODE] `packages/contracts/pyproject.toml` |
| Database | Supabase Postgres 17 (local CLI 2.121.0 used), RLS, pgTAP | [CODE] `supabase/config.toml` (`major_version = 17`); versions from [DOC] spec §17 |
| Jobs | Procrastinate on the same Postgres | [DOC] `09` §7. No code. Spec reserves a separate schema for it; `public` must hold only domain tables |
| LLM | Haiku 5.5 primary, Sonnet 5.5 escalation, GPT-6 Luna fallback, behind a provider adapter | [DOC] `13`, `09` §7. No code. Haiku quality is **unverified** until the eval [HYP] |
| WhatsApp | Cloud API direct | [DOC] `04`. No code; Meta verification and number registration are open tickets (#2, #3) |
| Frontend (Phase 2) | React + Vite, TS types generated from Pydantic JSON Schema | [DOC] `CLAUDE.md`. Pipeline "untested, allow half a day" per `09` D9 |

## Repository structure

On the working branch `MR-10-contracts-schema`:

```
supabase/                  config.toml, migrations/ (8 files, append-only), tests/ (6 pgTAP files)
packages/contracts/        src/mermia_contracts/{batch.py, db/models.py (GENERATED), db/overrides.py,
                           db/types.py, tools/gen_db_models.py}; tests/ (+ examples/*.json)
docs/kickoff/              research and plan (00..14, research/)
docs/superpowers/          MR-10 design spec (1019 lines) and implementation plan
docs/process/ticket-guide.md, .github/ISSUE_TEMPLATE/ticket.md
.claude/                   skills (check, review, start-ticket), agents/skeptic-reviewer.md, hooks, settings.json
CLAUDE.md, README.md, .gitattributes
```

Additionally on `origin/main` but **not** on this branch [CODE via `git show origin/main:<path>`]: root `pyproject.toml` (uv workspace `apps/*`, `packages/*`; ruff, mypy strict, pytest config), `apps/api/`, `.python-version` (3.12), `uv.lock`, `.github/workflows/ci.yml`.

**Integration risk [CODE]:** `git merge-tree HEAD origin/main` reports content conflicts in `.gitignore` and `README.md`. Also: `packages/contracts` has its own `pyproject.toml`, `uv.lock` and `.python-version`; main's root mypy config lists `files = ["apps"]` with a comment to add `packages` when MR-10 lands, and `mypy_path` lists only `apps/api/src`. Whether the contracts package passes under the root `ruff`/`mypy --strict` config is [UNK] (the spec records ruff/mypy run on the package alone, §17).

## Intended modules (target, mostly not built)

From `09` §1 [DOC]: `packages/contracts` (all Pydantic contracts), `supabase/` (migrations, RLS, metric RPCs, `apply_batch`, `rollback_batch`, `apply_pending_change`, pgTAP), `apps/api/{ingestion,agent,channels,confirm}`, `apps/evals`, `apps/mock-rpc` (08). None of the `apps/*` modules beyond the `/health` skeleton exist.

## Main data flows (designed; only step "schema" is built)

1. **Ingestion** [DOC `09` D2, §2.6, §3]: transport (WhatsApp / email / HTTP push) -> `raw_file` (sha256 dedup) -> parser registry -> one `NormalizedBatch` -> batch loader -> `apply_batch` -> facts tagged with `batch_id`. Lifecycle `received -> parsed -> needs_review -> applied -> superseded / rolled_back`. Facts are insert-only; metrics read only the current applied batch per slice. Clean uploads auto-apply with a "Deshacer" button.
   - Built: tables `raw_file`, `import_batch`, `import_issue`; `NormalizedBatch` types. [CODE]
   - Not built: transports, parsers, `apply_batch`/`rollback_batch`. [open issues #15, #16, #21, #23, #39]
2. **Question answering** [DOC `09` §4]: WhatsApp message -> router (templates, zero tokens) -> otherwise Haiku with 12 tools -> tool executor calls metric RPCs **as the user** (short-lived JWT, RLS applies) -> number validator rejects any number not in tool output -> reply. Not built (#17, #24, #26, #27).
3. **Writes** [DOC `09` D7, §5]: the agent's only write tool is `propose_change`; creates `pending_change`; a human with an allowed role confirms (WhatsApp buttons); `apply_pending_change()` applies in one transaction with `base_version` check; `audit_log` is append-only. Tables exist [CODE]; functions/service do not (#32, #37).
4. **Reports** [DOC `08`]: scheduled weekly job (Procrastinate) builds data via `build_weekly_report` RPC and sends a WhatsApp utility template. Not built (#34, #38).

## Entry points

- HTTP: `GET /health` only (on `origin/main`). [CODE]
- Database: no RPCs/functions in `public` by design; helper functions live in schema `app` (not exposed by the Data API). [CODE `supabase/tests/00_catalog.test.sql`; spec §5.1]
- CLI tooling: `python -m mermia_contracts.tools.gen_db_models [--check]` regenerates/validates `db/models.py`. [CODE]

## Security architecture as built

- Every table has RLS enabled and explicit grants, set by `app.finish_table(rel, mode, loc_col, parent, fk_col)` called in the same migration as the table. [CODE `supabase/migrations/20261018184052_foundations.sql:157`]
- Access classes (table comment `rls_class=`): T tenant, L location, F full-tenant members only, LP location inherited from a parent row, X backend-only (no client grant). 10 tables are X. [CODE foundations; DOC spec §7.2]
- Claims read by policies: `tenant_id`, `app_role`, `location_ids` (never JWT `role`). Absent/empty/malformed `location_ids` = no location; explicit JSON `null` = all, only with `membership.all_locations = true`. [CODE foundations `app.can_see_location`, `app.has_all_locations`]
- Composite foreign keys `(tenant_id, x_id)` block cross-tenant references even for `postgres` and `service_role`. [DOC spec D18, V12; tests `40_integrity.test.sql`]
- **Trust of claims depends on who may sign JWTs.** RLS reads claims but does not make them trustworthy; the issuer, key custody, `custom_access_token` hook and `sub` mapping are NOT built and are conditions before any real tenant data. [DOC spec §7.5, §7.6]

## Dependencies between contracts and DB

`mermia_contracts/db/models.py` is generated from the migrated database by introspection and carries a hash of the migrations; `NormalizedBatch` imports the generated enums, so a schema change that is not regenerated fails tests. Guards: `tests/test_generator_hash.py` (no DB), `test_generator_fresh.py`, `test_models_match_db.py` (need `MERMIA_DB_URL`). `tests/test_batch_matches_db.py` pins which input field feeds which column (MAP / LOADER_ONLY tables). [CODE]

---

# Domain and business rules

## Entities (40 tables in `public`) [CODE `supabase/migrations/*`, count of `create table public.*` = 40]

| Group | Tables | Access class |
|---|---|---|
| Tenancy / identity / sources | `tenant` (T root), `location` (L), `source` (L; `config` and `api_key_hash` hidden by column grant), `app_user`, `membership`, `channel_identity`, `consent_log`, `external_ref` (the last four X = backend-only) | see below |
| Ingestion | `raw_file` (X), `import_batch` (L), `import_issue` (LP) | |
| Catalog and sales facts | `menu_category`, `menu_item`, `menu_item_price`, `modifier_link`, `staff`, `sale_ticket`, `sale_line`, `payment`, `item_sales_agg`, `daily_sales_agg` (all L) | |
| Costing | `supplier`, `ingredient`, `ingredient_alias`, `unit_conversion`, `purchase_doc`, `purchase_line`, `ingredient_price`, `recipe`, `recipe_line` (all T) | |
| Control / metrics / ops | `pending_change`, `audit_log` (F), `dish_cost_snapshot`, `daily_location_metrics`, `alert`, `price_suggestion` (L), `report_run`, `conversation`, `llm_usage`, `message_log` (X) | |

Access classes [CODE `app.finish_table`, `20261018184052_foundations.sql:157`]: **T** tenant only; **L** tenant + `app.can_see_location(col)`; **F** tenant + `app.has_all_locations()`; **LP** visible if the parent row is visible; **X** no client grant at all. Four tables have no `tenant_id`: `tenant`, `app_user`, `channel_identity`, `consent_log`. [DOC spec §5.7]

Key relationships [CODE]: every tenant-scoped FK is composite `(tenant_id, x_id)`; `sale_line`/`payment` carry a location that must equal their ticket's (`foreign key (tenant_id, ticket_id, location_id)`, `20261018185056_catalog_and_sales.sql:211,248` [CODE]); `import_batch.supersedes_batch_id` self-reference; `recipe` has either `menu_item_id` or `produces_ingredient_id` (`num_nonnulls = 1`); `recipe_line` has either `ingredient_id` or `sub_recipe_id`.

## Implemented rules (in the database)

| Rule | Enforcement | Evidence |
|---|---|---|
| Tenant isolation on every client-readable table | RLS policy `tenant_id = (select app.current_tenant_id())` | foundations; `supabase/tests/10_isolation.test.sql` (data-driven over all tables) |
| Location isolation, fail-closed | `app.can_see_location`: absent/empty/malformed `location_ids` = nothing (tenant-level rows hidden too); explicit `null` = all | `20_location.test.sql` |
| `null` = all locations needs an explicit flag | `membership.all_locations boolean default false`, `check (all_locations = (location_ids is null))`; default `location_ids = '{}'` | identity migration:55-62; `40_integrity` |
| Membership locations must belong to the membership's tenant | constraint trigger `app.check_membership_locations()` | identity migration:67 |
| No client writes at all | no INSERT/UPDATE/DELETE grants or policies for `authenticated`/`anon` | `30_write_denial.test.sql` |
| `audit_log` immutable | UPDATE/DELETE row trigger + TRUNCATE trigger raise `42501`; UPDATE/DELETE/TRUNCATE revoked from every role incl. `service_role` | foundations `app.block_mutation`; `30_write_denial`. Owner role can still bypass via replica mode/trigger disable; mitigated only by a test forbidding functions that do so |
| Optimistic concurrency | `version` + `updated_at` bumped by `app.touch_row()`; changing `tenant_id` is refused | foundations; `40_integrity` |
| Cross-tenant references impossible | composite FKs, even for `postgres`/`service_role` | `40_integrity` |
| One applied batch per slice | partial unique index `(tenant_id, slice_key) where status='applied'` | ingestion migration; constraint tested, **behaviour under real apply ordering untested** |
| Same file twice ignored | `unique (tenant_id, sha256)` on `raw_file`; CFDI dedup `unique (tenant_id, cfdi_uuid)` | migrations |
| No blank strings in `text` columns | `app.add_text_checks(rel)` adds `btrim(col) <> ''` checks | foundations; `00_catalog` |
| Money units | ledger = `bigint` centavos; unit prices/costs = `numeric(20,6)` pesos per base unit; quantities `numeric(18,6)`; `*_pct` = percent points (34.1 = 34.1%) `numeric(7,4)`; tax rate = fraction `numeric(5,4)`; LLM/message cost USD `numeric(12,6)`. Convert pesos->centavos once, `round(pesos*100)`, never round intermediates, never float | README "Units" [DOC]; column `COMMENT` unit tags [CODE]; checked by `00_catalog` |
| UUIDv7 keys | vendored sub-ms `app.uuid_v7()` (PostgreSQL License notice kept in the migration; a test greps it) | foundations; `test_migration_notices.py` |
| Roles, channel, status vocabularies | Postgres enums in schema `app` (24), only values the docs list; other `text` columns have no value list on purpose | enums migration; spec §5.3 |
| Parser output is strictly typed | `NormalizedBatch`: no extra fields, money = strict int centavos within bigint range, quantities `Decimal`, instants timezone-aware, required text not blank, `period.from <= period.to`, `contract_version = 1` | `packages/contracts/src/mermia_contracts/batch.py`; `tests/test_batch_*.py` |
| Client cannot read class X tables via embedding / OpenAPI / hidden columns | privileges + PostgREST exposure tests | `tests/test_rest_exposure.py` (needs local stack) |

## Pending / documented-only rules (NOT implemented)

| Rule | Source | Missing piece |
|---|---|---|
| **Human approval for every DB change by the agent**, audit-logged | `CLAUDE.md`, `09` D7, §5 | `propose_change`, `apply_pending_change`, confirmation service (#32, #37). Tables only |
| Approval matrix by change kind and role (e.g. `menu_item_price.set` approvable by owner/admin only) | `09` §5.1 | No function reads `membership.can_approve` or `pending_change.required_role`; `pending_change.kind` is plain `text` and kinds disagree between `08` (5 kinds) and `09` §5.1 (7 kinds) |
| Per-batch approval; clean uploads auto-apply with "Deshacer" | `09` §10, `08` | `apply_batch`/`rollback_batch` (#16), upload messages (#28) |
| Ticket-grain idempotency | spec §8.2 | Facts have **no** unique key on `(tenant_id, source_id, external_id)`; `apply_batch` must dedupe, and validate `grain` vs rows, dates vs `period`, `totals` vs rows (the Pydantic model does not) |
| Number validator: code produces every number; LLM numbers must appear in tool output; 100% numeric fidelity release gate | `09` D6, `05` #7, `13` | Not built (#27) |
| LLM never sees phone numbers, RFCs or full staff names; staff stored first-name only | `09` §4.2, spec | Schema stores `staff.display_name`; no agent code |
| Caps per tenant (60 LLM questions/day, 400 max tokens, 4 tool calls) | `09` §4.2 | `llm_usage` table only |
| Unknown WhatsApp senders ignored; opt-in recorded | `09` §2.1, `04` | tables only (#29) |
| Margin math: net of IVA, `price/1.16`; alert thresholds (8% price jump, +3 pts food cost); food-cost target 30-35% | `11` A7-A9 | marked **likely/opinion**; costing engine and alert rules not built (#25, #33). Tip/IVA treatment awaits an accountant (`11` T6) |
| Every cost figure carries a confidence tag (`confirmed/estimated/missing`) | `09` §2.5, `05` | enum exists on `dish_cost_snapshot.confidence`; nothing computes it |
| JWT claim issuance (who may mint `tenant_id`/`app_role`/`location_ids`, `null` only for `all_locations` memberships) | spec §7.5, §7.6 | Not built (#27, #29, #40). Without it, RLS has no trustworthy input in production |
| Retention of raw files (`raw_file.retention_until`) and privacy-notice versioning | `04`, `05` #10 | column only; policy [UNK] (lawyer ticket #8) |

## Provisional contract areas (formats unverified)

`MenuItemIn`, `ItemSalesIn`, `DailySalesIn`, `RecipeIn`, `RecipeLineIn` carry a `PROVISIONAL:` docstring and a test checks the marker (`tests/test_batch_provisional.py`). They depend on real SR exports (Productos vendidos, Corte Z / Ventas por día, Recetas) that are not in the repo. `TicketIn` follows the "verified" ERP/PMS payload but has no adapter (Phase 1b); `PurchaseIn` follows CFDI 4.0 fields not yet validated against the SAT XSD. [CODE `batch.py`, `packages/contracts/README.md`]

Notable modelling calls the owner approved on 2026-10-18 and that an AI should not "fix": `daily_sales_agg` has `cancellations_amount` + `cancellations_count` (both nullable = "not reported", not zero); `item_sales_agg` uses `period_from/period_to`; `alert` and `price_suggestion` are separate tables; `sale_ticket.table_label` instead of `table`; `recipe.recipe_version` instead of `recipe.version`; `public` holds no functions. [DOC spec §2, §5.6, §12.1]
