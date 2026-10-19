# MR-10 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Write each test first and watch it fail (superpowers:test-driven-development); verify before claiming completion (superpowers:verification-before-completion).

**Goal:** Deliver the 40-table Supabase schema with tenant and location isolation, the generated Pydantic models, and the `NormalizedBatch` contract, in one branch and one PR.

**Architecture:** SQL migrations in a root `supabase/` project (pgTAP tests beside them); a self-contained `packages/contracts` Python package that generates its DB models from the migrated database and hand-writes `NormalizedBatch`. Security is layered: SQL privileges, then RLS policies keyed on JWT claims, then immutability triggers; the claim issuer is out of scope and documented.

**Tech Stack:** Postgres 17 (Supabase CLI 2.121.0, local Docker stack), pgTAP, Python 3.12, Pydantic v2, pytest, psycopg 3, `uv`.

**Spec:** `docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md` (revision 3, approved). Section numbers below refer to it.

## Global Constraints

- One branch `MR-10-contracts-schema`, one PR, commits `MR-10: <what>`. No merge, no push without the owner's go-ahead, no remote or shared database.
- Migrations: append-only, created with `supabase migration new`, apply from an empty database. Money: ledger `bigint` centavos; unit prices `numeric(20,6)` pesos; percentages `numeric(7,4)` percent points (5.4).
- `public` holds only the 40 domain tables, no functions, no views (5.1, 7.2.5). Helpers and enums live in schema `app`.
- Enums only where docs list values (5.3); other `text` columns get the not-blank check (5.1).
- Claims: `tenant_id`, `app_role`, `location_ids`; absent or malformed `location_ids` means no location; explicit JSON `null` means all (7.3, 7.5.10).
- Do not touch: root `pyproject.toml`, CI, other tickets' code. Do not edit `packages/contracts/src/mermia_contracts/db/models.py` by hand.
- Report real results only; a check that cannot run is listed as not run (16.4).

## Review Focus

- A membership created without a stated scope must never yield `location_ids: null` (test: insert without scope gives empty list; `NULL` without the flag fails).
- A child row (`sale_line`, `payment`) carrying a different location than its ticket must be rejected (composite FK including `location_id`).
- A blank string in an unspecified `text` column must be rejected (not-blank check on every text column).
- A client must not read class X tables through embedding, GraphQL or OpenAPI (`test_rest_exposure.py`).
- `service_role` must not be able to alter `audit_log` rows (`UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` revoked).

---

### Task 1: Project scaffolds

**Files:**
- Create: `supabase/` (via `supabase init`), `packages/contracts/{pyproject.toml,README.md,.gitignore}`, `packages/contracts/src/mermia_contracts/{__init__,py.typed}`, `packages/contracts/tests/test_smoke.py`, `.gitattributes`
- Modify: `supabase/config.toml` (`project_id = "mermia"`)

**Interfaces:**
- Produces: a startable local stack from the repo root; `uv run pytest` runs in `packages/contracts`.

- [ ] **Step 1:** Write `test_smoke.py::test_package_imports` (imports `mermia_contracts`); run `uv run pytest` and see it fail (no package).
- [ ] **Step 2:** Create the package scaffold (src layout, `requires-python >=3.12`, dependency `pydantic>=2.8`, dev `pytest`, `psycopg[binary]`, markers `db` and `rest`); run the test and see it pass.
- [ ] **Step 3:** Run `supabase init` at the repo root, set `project_id`, then `supabase start -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor` and `supabase db reset` on the empty migration set.
- [ ] **Step 4:** Commit `MR-10: scaffold supabase project and contracts package` (include the spec and this plan).

### Task 2: Foundations migration (spec 5.2, 7.3, 7.4, 8)

**Files:**
- Create: `supabase/migrations/<ts>_foundations.sql`, `supabase/tests/00_catalog.test.sql` (helper/grant/function assertions first), `supabase/tests/20_location.test.sql` (helper semantics), `supabase/tests/40_integrity.test.sql` (uuid_v7 cases)

**Interfaces:**
- Produces (schema `app`): `uuid_v7(timestamptz default clock_timestamp()) returns uuid`; `touch_row()`; `block_mutation()`; `current_tenant_id() returns uuid`; `can_see_location(uuid) returns boolean`; `has_all_locations() returns boolean`; `add_text_checks(regclass)`; `finish_table(rel regclass, mode text, loc_col text default null, parent regclass default null, fk_col text default null)` with modes `tenant | tenant_root | location | full | backend | parent`; `tag(rel regclass, tag text, cols text[])`. Table comment `rls_class=<T|L|F|LP|X>[;loc_col=<col>]`.

- [ ] **Step 1:** Write the pgTAP cases: `uuid_v7` over 10,000 values (version 7, variant `8-b`, unique, zero inversions, timestamp round-trip, license text in the function comment); helper semantics (`null`, array, `[]`, wrong type, absent key, malformed tenant); every `app` function has no `PUBLIC`/`anon` execute; only the three helpers executable by `authenticated`; default privileges on `public` revoked (create a scratch table, check no `anon`/`authenticated` privilege).
- [ ] **Step 2:** `supabase test db`; expect failures (objects missing).
- [ ] **Step 3:** Write the migration (PostgreSQL License header for `uuid_v7`; reference helper bodies from 7.3; `touch_row` refuses `tenant_id` change through `to_jsonb(old)`; `alter default privileges for role postgres in schema public` revokes for `anon`/`authenticated`; grants of 7.4).
- [ ] **Step 4:** `supabase db reset && supabase test db`; expect pass. Commit `MR-10: foundations migration and helper tests`.

### Task 3: Enums migration (5.3)

**Files:** `supabase/migrations/<ts>_enums.sql`; extend `00_catalog.test.sql` with an enum-label table.

- [ ] **Step 1:** Add the test comparing every enum's ordered labels to 5.3 (24 enums); see it fail.
- [ ] **Step 2:** Create the 24 enums in schema `app`; see it pass. Commit `MR-10: enums`.

### Task 4: Identity and sources (5.7 §2.1)

**Files:** `<ts>_identity_and_sources.sql`; tests in `40_integrity` (membership), `00_catalog` expected-table list (grows).

**Interfaces:** Consumes `finish_table`, `tag`. Produces tables `tenant, location, app_user, membership, channel_identity, consent_log, source, external_ref`; `membership` columns include `all_locations boolean not null default false`, `location_ids uuid[] default '{}'`, check `all_locations = (location_ids is null)`; trigger rejecting foreign-tenant `location_ids`; `source` column grants exclude `config`, `api_key_hash`.

- [ ] **Step 1:** Write tests: insert without scope gives `'{}'` and `all_locations = false`; `location_ids = null` with `all_locations = false` fails; `all_locations = true` with an array fails; foreign-tenant location id in `location_ids` fails; `tenant_id` update fails; blank `name` fails.
- [ ] **Step 2:** Run, see failures. Step 3: write the migration. Step 4: `supabase db reset && supabase test db`. Commit `MR-10: identity and sources tables`.

### Task 5: Ingestion (§2.2)

**Files:** `<ts>_ingestion.sql`; tests: partial unique index (one `applied` per slice, others free), `unique (tenant_id, sha256)`, `import_issue` class LP.

- [ ] Steps as Task 4 (test, fail, migrate, pass, commit `MR-10: ingestion tables`).

### Task 6: Catalog and sales (§2.3)

**Files:** `<ts>_catalog_and_sales.sql`; tests: `sale_line`/`payment` with a location different from the ticket's fail (composite FK on `(tenant_id, ticket_id, location_id)` referencing `sale_ticket (tenant_id, id, location_id)`), currency check, period check.

- [ ] Steps as Task 4. Commit `MR-10: catalog and sales tables`.

### Task 7: Control (§2.5 control tables)

**Files:** `<ts>_control.sql`; tests: `audit_log` privileges exactly `SELECT` (`authenticated`, `service_role`) and `INSERT` (`service_role`); `UPDATE`/`DELETE`/`TRUNCATE` as `postgres` raise `42501`; `pending_change.kind` not null and not blank.

- [ ] Steps as Task 4. Commit `MR-10: control tables`.

### Task 8: Costing (§2.4) and Task 9: Metrics (`dish_cost_snapshot`, `daily_location_metrics`)

**Files:** `<ts>_costing.sql`, `<ts>_metrics.sql`; tests: `num_nonnulls` checks on `recipe`, `recipe_line`, `ingredient_price`; `unique nulls not distinct` on `unit_conversion`; unit tags present.

- [ ] Steps as Task 4, one commit each: `MR-10: costing tables`, `MR-10: metrics tables`.

### Task 10: Complete the pgTAP suite (10.4)

**Files:** finalize `00_catalog`, `10_isolation`, `20_location`, `30_write_denial`, `40_integrity`, create `50_exposure`.

- [ ] **Step 1:** `00_catalog`: the 40-table list, no functions/views in `public`, RLS on and not forced, class comments, policy counts per class, privilege matrix, unit tags, not-blank checks on all `text` columns, no `set_config`-on-`request.jwt` function.
- [ ] **Step 2:** `10_isolation`: data-driven fixtures (`session_replication_role = replica`, per-table overrides for CHECK columns) and the A/B/no-claim/malformed/anon matrix per class, locations A1/A2/B1.
- [ ] **Step 3:** `20_location`: LP inheritance for `import_issue`, class F rule, `source` column grants.
- [ ] **Step 4:** `30_write_denial`: each client role × `INSERT/UPDATE/DELETE/TRUNCATE` on every table (privilege layer message), a scratch table for the RLS-layer message, `service_role` writes, `authenticated` cannot `set role service_role`, definer-function pattern.
- [ ] **Step 5:** `50_exposure`: FKs from client-readable tables to class X tables listed, `source` columns, membership scope behaviour, `audit_log` privileges.
- [ ] **Step 6:** `supabase db reset && supabase test db`; expect all pass. If `session_replication_role` is refused under `pg_prove`, switch `10_isolation` to dependency-ordered fixtures and record it. Commit `MR-10: pgTAP isolation and exposure suite`.

### Task 11: Generator and models (10.2)

**Files:**
- Create: `src/mermia_contracts/tools/gen_db_models.py`, `db/overrides.py`, generated `db/models.py`, `tests/test_generator_hash.py`, `tests/test_generator_fresh.py`, `tests/test_models_match_db.py`

**Interfaces:**
- Produces: CLI `python -m mermia_contracts.tools.gen_db_models --db-url URL [--check]`; `compute_migrations_hash(migrations_dir: Path) -> str`; `generate(conn) -> str` (deterministic, ruff-format-stable); one `<Table>Row` model per `public` table and a `StrEnum` per `app` enum.

- [ ] **Step 1:** Write `test_generator_hash` (hash equals header of `models.py`; changes when a migration byte changes), `test_models_match_db` (every column, nullability, enum labels) and `test_generator_fresh` (regenerated text equals the file); marker `db` on the last two.
- [ ] **Step 2:** Run (fail), implement the generator following 10.2, run it against the reset database, run `uvx ruff format --check` and `uvx ruff check` on the package, adjust until stable. Commit `MR-10: db model generator and generated models`.

### Task 12: `NormalizedBatch` (10.1, 10.3)

**Files:** `src/mermia_contracts/batch.py`, `tests/{test_batch_types,test_batch_enums_json,test_batch_examples,test_batch_provisional}.py`, `tests/examples/*.json`

**Interfaces:** Consumes the generated enums. Produces `NormalizedBatch`, `Period`, `Totals`, `Grain`, and the `*In` types of 10.1 (`MenuItemIn`, `ItemSalesIn`, `DailySalesIn`, `TicketIn`, `StaffIn`, `TicketLineIn`, `PaymentIn`, `PurchaseIn`, `SupplierIn`, `PurchaseLineIn`, `RecipeIn`, `RecipeLineIn`, `IssueIn`); provisional classes' docstrings begin `PROVISIONAL:`.

- [ ] **Step 1:** Write the tests of 10.3 first (types, nullability, enums, JSON round trip and schema snapshot, contract rules, provisional markers); run, see them fail.
- [ ] **Step 2:** Implement `batch.py`; add `test_models_match_db` coverage that each `*In` field maps to a column; run; commit `MR-10: NormalizedBatch contract`.

### Task 13: REST exposure test (7.2.5)

**Files:** `tests/test_rest_exposure.py` (marker `rest`, reads `MERMIA_API_URL`, `MERMIA_JWT_SECRET`, `MERMIA_API_KEY`; HS256 minting with stdlib only)

- [ ] **Step 1:** Write the cases: class X table returns 403; `source?select=*` 403 and `select=id,kind` 200; embedding class X from a readable table yields no X data; `import_batch?select=*,import_issue(*)` and `import_issue?select=*,import_batch(*)` show only allowed locations; GraphQL queries of X tables fail (or reported not run); OpenAPI lists no X table for `authenticated`; forged signature 401.
- [ ] **Step 2:** Run against the local stack; record any case the local stack cannot serve. Commit `MR-10: REST exposure tests`.

### Task 14: Docs (section 11)

**Files:** `README.md`, `docs/kickoff/09-architecture.md`, `docs/kickoff/08-mvp-4-week-plan.md`, spec status line

- [ ] **Step 1:** README: layout, prerequisites, commands (10.5), percentages in percent points, units and rounding.
- [ ] **Step 2:** Edit `09` and `08` as listed in section 11 (module table, money rule, `tenant_id` exceptions, claims, trust-boundary pointer, `cancellations`, `table_label`, `alert`/`price_suggestion`, `all_locations`, snake_case).
- [ ] **Step 3:** Commit `MR-10: documentation updates`.

### Task 15: Full verification and PR preparation

- [ ] **Step 1:** `supabase stop --no-backup`, `supabase start -x ...`, `supabase db reset`, `supabase test db`.
- [ ] **Step 2:** `cd packages/contracts && uv run pytest`, then with `MERMIA_DB_URL` `-m db`, with REST variables `-m rest`, then `gen_db_models --check`; `uvx ruff check` and `uvx ruff format --check` on the package.
- [ ] **Step 3:** Update spec 16.4 with what ran and what could not; write the PR description with real outputs, deviations, and the owner-review items. Do not push or open the PR without the owner's go-ahead.

## Self-review (against the spec)

Coverage: 5.1-5.7 (Tasks 2-9), 6 (Tasks 2-9), 7.1-7.5 (Tasks 2, 4, 7, 10, 13), 8 (Tasks 2, 4-9), 10 (Tasks 11-13), 11 (Task 14), 13 and 14 (Task 15). Types: `finish_table` and `tag` are defined in Task 2 and used in Tasks 4-9; `Row` and enum names come from the generator in Task 11 and are consumed by Task 12.
