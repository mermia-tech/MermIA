# MR-10 Design: database schema and `NormalizedBatch` contract

Date: 2026-10-18. Ticket: [#10](https://github.com/mermia-tech/MermIA/issues/10). Branch (not yet created): `MR-10-contracts-schema`. Status: **revision 3. Approved by the owner on 2026-10-18 with the adjustments listed in 2.3. Implemented on branch `MR-10-contracts-schema`; the verification record is in section 17.**

This document is written so a builder can plan MR-10 from it without going back to the owner, except for the items in section 12.

Revision 3 adds the owner's approval conditions (2.3): indirect exposure paths (7.2.5), separation of visibility, approval, execution and audit reading (7.2.6), issuance of the `null` claim (7.5.10), an explicit all-locations flag on `membership` (5.7), text-integrity rules (5.1), and the exposure tests (10.4).

Revision 2 changes (from the owner's review of revision 1): location isolation is resolved table by table (7.2); the trust boundary for JWT claims is explicit (7.5, 7.6); every schema call of revision 1 was re-checked against the docs, the PoCs and the scope (12.1); items that depend on unverified formats are marked provisional (10.1); the evidence is split into five buckets (section 16).

## 0. How to read this document

Every statement carries one of these tags when its origin matters.

| Tag | Meaning |
|---|---|
| **[APPROVED]** | Decided by the owner in chat (2026-10-18). |
| **[DOC]** | Written in the repo (`docs/kickoff/*`, tickets). The file is cited. |
| **[VERIFIED]** | Checked locally on 2026-10-18 with Supabase CLI 2.121.0 and Postgres 17.11 (section 3, ids `V1`-`V26`). |
| **[EXT]** | Read in external documentation. Not run here. |
| **[AUTHOR]** | A call made while writing this spec because the docs are silent. Reviewable. Listed in 12.1 when it touches schema, security, integrity or compatibility. |
| **[OPEN]** | A hypothesis not yet proven, or a question for the owner. |

## 1. Intent, scope and non-goals

### Why

Dev A and Dev B both build on the database shape and on the parser output format. MR-10 fixes them (`09-architecture.md` §2.1-2.5 and §3). `docs/kickoff/08-mvp-4-week-plan.md` calls these contracts C1 and C2. Changing them later means rewriting code in several places, so correctness and security matter more than speed here.

### Goals

1. SQL migrations that create the 40 tables of `09` §2.1-2.5 with their enums, constraints, indexes, triggers and **tenant and location isolation by default**, and that run from an empty database. [DOC ticket #10] [APPROVED]
2. Pydantic models generated deterministically from that schema, plus a check that the generated file is not stale. [DOC ticket #10] [APPROVED]
3. A hand-written `NormalizedBatch` Pydantic model and its input types (parser output, `09` §3). [DOC]
4. Tests that prove tenant isolation, location isolation, write denial for client roles, integrity rules, and the contract types. [APPROVED]
5. An explicit trust boundary for the JWT claims the policies read (7.5). [APPROVED D3]
6. One PR, one branch, internal phases as separate commits. [APPROVED]

### Non-goals (explicitly out of MR-10)

- RPCs, `apply_batch`, `rollback_batch`, `apply_pending_change`, metric views (MR-16, MR-17, MR-24, MR-32). Views must use `security_invoker = true` when they arrive; see 8.1.
- The `custom_access_token` hook, minting or setting of agent claims, production key custody, and the `app_role` checks in apply functions (MR-14, MR-27, MR-29, MR-32, MR-40). MR-10 documents the conditions they must meet (7.5, 7.6) but does not build them.
- Storage buckets and their policies. `raw_file.storage_path` is only a text column here.
- Fixtures and seed data (MR-12).
- Root `pyproject.toml`, `uv` workspace and CI (MR-9). MR-10 only documents the commands MR-9 will run.
- Staff-level or hour-level aggregates ("reports by waiter and hour"). [APPROVED]
- Procrastinate tables. They go in a separate schema in the ticket that adds Procrastinate; `public` is reserved for domain tables. [APPROVED]
- CODEOWNERS (MR-11).
- Any remote or shared database. Everything runs against the local CLI stack.

### Anti-goals (would make MR-10 a failure even if it "works")

- A table with `tenant_id` readable across tenants, or with client write access that bypasses `pending_change` (`09` D7).
- A table readable beyond what the documented operations need (least privilege), without a recorded reason.
- Silent drift between the SQL and the Pydantic models.
- A contract field that is not backed by a document and not listed in 12.1.
- Claiming that RLS alone makes a claim trustworthy (7.5).

## 2. Decisions and their status

### 2.1 Approved by the owner (2026-10-18)

| Id | Decision |
|---|---|
| P1 | One PR. No 400-line limit. No calendar plan, no waiting for Dev B. |
| D2 | Migrations live in `supabase/` at the repo root. `09` and contradicting references are updated (section 11). |
| D3 | JWT claims `tenant_id`, `app_role`, `location_ids`, with an explicit statement of where their trust comes from (7.5). |
| D6 | Ledger amounts are `bigint` centavos. Unit prices and unit costs are `numeric(20,6)` **pesos** per base unit. Units, conversion and rounding rules are documented (5.4). |
| D7 | Cancellations are split into amount and count. Their match with the sources is validated and recorded (5.5). |
| D8 | JSON is `snake_case`. |
| D10 | `app_user`, `channel_identity` and `consent_log` have no `tenant_id`; only the backend can access them. |
| D12 | Issue severity is `info`, `warning`, `error`, after checking it does not contradict another contract (done: 9.2). |
| D18 | Composite foreign keys `(tenant_id, id)`, subject to compatibility tests (PoC results V12, V13). |
| D5 | UUIDv7 stays a requirement. License check and local PoC before adopting an external implementation (done: V8, V18, 5.2). |
| - | `public` is reserved for domain tables; Procrastinate gets its own schema. |
| - | Waiter and hour reports are out of MR-10. |
| - | `audit_log` has no `updated_at` or `version` and is immutable. |
| D1 | Installing the Supabase CLI and pulling images was authorized. Done. No remote database was touched. |

### 2.2 Documented requirements this spec relies on

| Requirement | Source |
|---|---|
| 40 tables, columns and enums as listed | `09` §2.1-2.5 |
| Batch lifecycle states | `09` §2.6 |
| `NormalizedBatch` shape | `09` §3 |
| Reads run as the user under RLS (`SECURITY INVOKER`); writes only through `pending_change` and `SECURITY DEFINER` functions with explicit tenant checks | `09` D5, D7, D8, §4.1, §6 |
| Policy uses a `tenant_id` claim, and there is an extra location filter from `membership.location_ids` | `09` §6 |
| "`location_id` null means every location the user can see" | `09` §4.1 |
| Manager access is scoped to a location ("Laura ya puede mandar reportes de *Centro*"); one uploader per branch, mapped by phone number | `12` §4a-4d, `05` risk 3 |
| Approval matrix by change kind and role (no location dimension) | `09` §5.1 |
| Dashboard (Phase 2): `pending_change` list and diff, filter by location, full audit view | `09` §5.3 |
| UUIDv7 keys that any client can generate | `09` §2, §9; `07` roadmap; research notes |
| `audit_log` is append-only: a trigger blocks UPDATE and DELETE and no grants exist for either | `09` §2.5 |
| Migrations are numbered and only appended | `08` Branching row |
| Local Supabase through the CLI per dev | `08` Environments row |
| Roles `owner, manager, admin, support` | `09` §2.1 |
| Unknown senders are ignored; opt-in is recorded with notice version and message types | `09` §2.1, `04` (opt-in row), `05` risk 10 |
| LLM usage fields | `13` §I4 |
| Meta pricing categories | `04` §4 |

### 2.3 Owner approval of revision 2 and its conditions (2026-10-18)

| Item | Owner decision | Where handled |
|---|---|---|
| A1 | Keep the ten backend-only tables and the restricted `source.config` / `source.api_key_hash`. Verify documented flows work with those permissions and that no indirect path (views, relationships, exposed functions) leaks sensitive data. | 7.2.4, 7.2.5, `00_catalog`, `50_exposure`, `test_rest_exposure.py` |
| A12 | Keep fail-closed: absent or malformed claim means no location; empty list none; valid list only those; `null` means all locations **only** when it comes from a trusted issuer **and** the membership expressly authorizes full scope. Document who may issue `null`, how that permission is validated and how a client or exposed function is prevented from obtaining it. Header restrictions are not accepted as proof of trust. | 5.7 (`membership.all_locations`), 7.3, 7.5.10 |
| A13 | Keep `pending_change` and `audit_log` for all-location members only. Document visibility, approval, execution and audit reading separately. `audit_log` stays immutable with explicit operation privileges. No extra RPC for single-location managers (later phase). | 7.2.6, 5.7, `30_write_denial` |
| A14 | Keep `import_issue` inheriting its batch's visibility. Prove it on direct queries, embedded relations and documented routes. | 7.2.5, `20_location`, `test_rest_exposure.py` |
| A2, A4, A5, A8 | Accepted, with conditions: percentages documented as percent points; no invented enums; no integrity validation skipped because a column is `text`; `alert` and `price_suggestion` stay separate. | 5.1 (text integrity), 5.4, 5.3 |
| A10 | Accepted: vendored UUIDv7, license notice kept, compatibility, ordering and uniqueness tests kept. | 5.2, `40_integrity`, `00_catalog` |
| Other recommended calls | Kept where consistent with canonical documents. | 12.1 |
| AMB-7, `sub`, production key custody | May stay as documented dependencies of later tickets, provided MR-10 still establishes a correct security boundary. | 7.5, 7.6, 12.2 |
| Pending verifications | Run the relevant ones against the real schema before finishing; record tool limits; never report an unrun check as passed. | 13 (step 9), 16.4 |
| Process | Create `MR-10-contracts-schema` from updated `main`; follow section 13; Superpowers plan execution, TDD and verification; one branch and one PR; no artificial 400-line limit; no merge and no ticket closing without the owner. Stop and report on a critical contradiction (security, integrity, compatibility). | 13 |

## 3. Local verification already done (PoC)

Environment: macOS, Docker 29.8.1, Supabase CLI 2.121.0 (installed with `brew install supabase`, authorized), Postgres 17.11 local stack. The PoC projects were created outside the repo and the stack was stopped afterwards. Nothing in the repo was changed by them. The scripts are in the session scratchpad, not in the repo. Everything below ran against the local stack only.

| # | Result | Tag |
|---|---|---|
| V1 | `supabase init` generates `major_version = 17`; the local database reports Postgres 17.11. | [VERIFIED] |
| V2 | `supabase db reset` and `supabase test db` find `supabase/` by searching **upward** from the current directory (run from a nested directory). `--workdir` means "the directory containing `supabase/`", used exactly as given. A root `supabase/` works from anywhere in the repo with no flags. | [VERIFIED] (run and `supabase start --help`) |
| V3 | `supabase test db` runs pgTAP through the `pg_prove` image; `has_extension('pgtap')` passes; a test using `set local role`, `set_config('request.jwt.claims', ...)`, `throws_ok` and `is` works. | [VERIFIED] |
| V4 | `auth.jwt()` is `coalesce(nullif(current_setting('request.jwt.claim', true), ''), nullif(current_setting('request.jwt.claims', true), ''))::jsonb`. | [VERIFIED] |
| V5 | Roles: `postgres` is **not** superuser and has `BYPASSRLS`; `service_role` has `BYPASSRLS`; `anon`, `authenticated`, `authenticator`, `supabase_auth_admin` do not. | [VERIFIED] |
| V6 | Default privileges: objects created by `postgres` in `public` grant all table privileges to `anon`, `authenticated`, `service_role`; functions grant `EXECUTE` to the same roles. `alter default privileges for role postgres in schema public revoke ...` removes it for later tables (a new table had grants only for `service_role`). | [VERIFIED] |
| V7 | API exposed schemas locally: `public`, `graphql_public`. An RPC call on schema `app` returns `PGRST106 Invalid schema`. | [VERIFIED] |
| V8 | UUIDv7 as a pure SQL function on Postgres 17, 100k values per variant. Millisecond variant: version and variant bits correct, unique, **50,029 ordering inversions** in one statement. Sub-millisecond variant: version and variant correct, unique, **0 inversions**, timestamp round-trips. | [VERIFIED] |
| V9 | A column `DEFAULT app.uuid_v7()` is evaluated with the **invoker's** privileges. With `EXECUTE` revoked from `PUBLIC`, `service_role` inserts failed with `permission denied for function`. The fix is an explicit grant of `EXECUTE` and schema `USAGE` to the roles that insert. | [VERIFIED] |
| V10 | Tenant isolation on a minimal model via `set local role` and claims: tenant A sees only A, tenant B only B; no tenant claim, malformed `tenant_id` and no claims return zero rows; `anon` gets `permission denied`; a table with RLS on, a `SELECT` grant and no policy returns zero rows; `service_role` and `postgres` see all rows. | [VERIFIED] |
| V11 | The three layers fail with different errors: SQL privilege (`42501 permission denied for table X`), RLS (`42501 new row violates row-level security policy for table "X"`), trigger (custom `42501`). `service_role` is blocked on `UPDATE/DELETE/TRUNCATE` of the audit table by `REVOKE`; `postgres` is blocked by the trigger. | [VERIFIED] |
| V12 | Composite FK `(tenant_id, x_id)`: a child of tenant B pointing at tenant A's parent fails with `23503` even for `postgres` and `service_role` (both bypass RLS). | [VERIFIED] |
| V13 | PostgREST (local) with HS256 JWTs minted against the local secret: valid token returns tenant data; **resource embedding through a composite FK works**; wrong signing secret returns `401 PGRST301`; expired token `401 PGRST303`; token without `tenant_id` returns `[]`; a table without client grants returns `403`. | [VERIFIED] |
| V14 | The local secret is a published demo value. A token signed with it and `role=service_role` returned all tenants' rows. The trust anchor of every claim is therefore **custody of the signing key** (7.5). | [VERIFIED] |
| V15 | `set local session_replication_role = replica` succeeded for `postgres` (not superuser) and let a data-driven fixture generator insert rows into tables with composite FKs, enums, `numeric(20,6)`, `jsonb`, arrays, `bytea` and a CHECK. The same loop then showed 1/1/0/permission-denied for tenant A / tenant B / no claim / `anon` on every table. | [VERIFIED] (in `psql`, not yet under `pg_prove`) |
| V16 | Catalog introspection (`pg_attribute`, `pg_type`, `pg_enum`, `format_type`) returns enum labels in order, `numeric(20,6)`, arrays, nullability and defaults. | [VERIFIED] |
| V17 | A minted JWT placed in the `apikey` header was accepted locally, although the external docs say it cannot be. | [VERIFIED] vs [EXT] contradiction; irrelevant to MR-10, noted for MR-14/27 |
| V18 | The upstream UUIDv7 SQL library (`dverite/postgres-uuidv7-sql`) is under the **PostgreSQL License**: copyright and the two disclaimer paragraphs must appear in all copies. Not archived (pushed 2025-11-05). Its sub-millisecond function is RFC 9562 method 3. | [VERIFIED] via GitHub API |
| V19 | **Location inherited from a parent row.** A child table (`import_issue` shape) whose policy is `tenant_id = current and exists (select 1 from <parent> p where p.tenant_id = child.tenant_id and p.id = child.parent_id)` returned only the rows whose parent location the claim allows (Centro only: 1 row; empty array or absent claim: none; explicit JSON null: all; other tenant: only its own). The parent's own RLS applied inside the subquery. | [VERIFIED] |
| V20 | **Fail-closed location claim.** With `can_see_location` returning true only for an explicit JSON `null` or a matching array element: absent `location_ids` returns no rows, empty array none, wrong type none. | [VERIFIED] |
| V21 | **Full-tenant policy.** `app.has_all_locations()` (true only for explicit JSON `null`) as an extra policy term: a member with `location_ids: null` read `pending_change`/`audit_log`-shaped tables; a Centro-only member and a token without the claim read none. | [VERIFIED] |
| V22 | **Column-level grants.** `grant select (tenant_id, id, location_id, kind) on source-shaped table to authenticated`: `select *`, `select config` and `select api_key_hash` fail with `42501`; selecting the granted columns works; over PostgREST `select=*` returns `403` and `select=id,kind` returns `200`. A location-limited member saw both its location's row and the tenant-level (null location) row. | [VERIFIED] |
| V23 | **Privileged function pattern.** A `SECURITY DEFINER` function in schema `app` with `search_path = ''` and `EXECUTE` revoked from `PUBLIC`, `anon`, `authenticated` and granted to `service_role`: `authenticated` is denied (`permission denied for function`), `anon` is denied (`permission denied for schema app`), `service_role` succeeds. | [VERIFIED] |
| V24 | **The Data API cannot change claims.** `POST /rest/v1/rpc/set_config` returns `404 PGRST202`; an RPC on schema `app` returns `406`; `public` held zero functions in the PoC database; direct writes through the Data API to a read-only table return `403`. | [VERIFIED] |
| V25 | **Headers do not choose claims.** A request carrying `request.jwt.claims` and `X-Tenant-Id` headers for tenant B, with a token for tenant A, returned tenant A's rows. | [VERIFIED] |
| V26 | `authenticated` **can** call `set_config('request.jwt.claims', ...)` in raw SQL. The trust model therefore assumes clients have no raw-SQL path (7.5.3). | [VERIFIED] |

| V27 | **PUBLIC execute default.** Postgres grants `EXECUTE` on new functions to `PUBLIC`, and a per-schema `alter default privileges ... in schema app revoke execute ... from public` did not remove it (9 of 9 functions stayed executable by `anon`). A global `alter default privileges for role postgres revoke execute on functions from public` did. The foundations migration uses the global form. | [VERIFIED] (found by `00_catalog`) |
| V28 | **`SET ROLE` follows the session user.** `authenticated` and `anon` are not members of `service_role` or `postgres`, but the PostgREST login role `authenticator` is a member of `service_role` (not of `postgres`). A test that tried `set role service_role` from inside a `set local role authenticated` block succeeded because the session user was `postgres`; it was invalid and was replaced by membership checks (`30_write_denial`). An escalation by SQL is therefore prevented only by the absence of any raw-SQL path (7.5.3). | [VERIFIED] |
| V29 | **Tenant-level rows and fail-closed claims.** With the first `can_see_location` (`loc is null` returns true before looking at the claim), a member with an absent or empty `location_ids` still saw tenant-level rows (null location). The helper was tightened: tenant-level rows are visible only with an explicit `null` or a non-empty well-formed list; an absent key, an empty list or any malformed list sees no row of a location-scoped table. | [VERIFIED] (found by `20_location`) |
| V30 | **`session_replication_role = replica` works under `pg_prove`** for `postgres`, so the data-driven isolation matrix (`10_isolation`) runs on the real 40-table schema. Mutation checks (dropping the `sale_ticket` policy, widening `import_issue` to tenant-only, widening `pending_change` to tenant-only) were detected by the matrix. | [VERIFIED] |
| V31 | **pg_graphql is not enabled on the local stack** (`pg_graphql extension is not enabled`). GraphQL exposure could not be tested; the test reports itself as skipped. | [VERIFIED] limitation |
| V32 | **PostgREST embedding.** `import_batch?select=*,raw_file(*)` and the other relationships into class X tables return no data. An ambiguous relationship (`app_user?select=*,import_batch(*)`) returns `300` before any permission check; a hinted one returns `403`. The OpenAPI document lists 30 tables plus `/` (the 10 class X tables are absent). | [VERIFIED] |
| V33 | **Staleness guards work.** Appending a line to a migration fails `test_generator_hash`; adding a column in the database fails `test_generator_fresh`, `test_models_match_db` and `gen_db_models --check`. | [VERIFIED] |
| V34 | **Python version.** Without a pin, `uv` selected Python 3.14 for the package; `.python-version` pins 3.12 as in `CLAUDE.md`. | [VERIFIED] |

Not yet verified (carry these into the implementation's first phases; list in section 16): behaviour of the whole schema under `supabase db reset`; `pg_prove` permitting `session_replication_role` (V15 ran in `psql`); CHECK/trigger interactions in the data-driven fixture generator; PostgREST embedding for self-referencing composite FKs; the partial unique index under real apply ordering; the multi-mode `app.secure_table` function; the generator's output on the real schema; production JWT signing-key custody.

## 4. Architecture and layout

[APPROVED D2]

```
supabase/                              # CLI project, found by upward search from anywhere in the repo (V2)
  config.toml                          # generated by `supabase init`; project_id = "mermia"; major_version = 17
  .gitignore                           # generated by the CLI
  migrations/                          # append-only, CLI timestamp names (see 6.1)
  tests/                               # pgTAP (see 10.4)
packages/contracts/                    # self-contained; compatible with the future MR-9 uv workspace
  pyproject.toml                       # requires-python >=3.12; runtime dep: pydantic; dev: pytest, psycopg[binary]; registers the `db` and `rest` pytest markers
  uv.lock                              # replaced by MR-9's root lock when the workspace lands
  README.md
  .gitignore                           # .venv, __pycache__, .pytest_cache (the repo has no root .gitignore yet)
  src/mermia_contracts/
    __init__.py
    py.typed
    batch.py                           # NormalizedBatch and the *In types (hand-written)
    db/__init__.py
    db/models.py                       # GENERATED, never edited
    db/overrides.py                    # typed shapes for documented jsonb columns (hand-written)
    tools/__init__.py
    tools/gen_db_models.py             # generator and --check (hand-written)
  tests/
    test_batch_types.py
    test_batch_enums_json.py
    test_batch_examples.py
    test_batch_provisional.py          # provisional types carry their marker (10.1)
    test_rest_exposure.py              # `rest` marker: embedding, hidden columns, GraphQL, OpenAPI (local stack only)
    test_generator_hash.py             # no database needed
    test_generator_fresh.py            # needs the local database
    test_models_match_db.py            # needs the local database
    examples/*.json                    # small valid and invalid batches
.gitattributes                         # packages/contracts/src/mermia_contracts/db/models.py linguist-generated=true
README.md                              # developer commands (10.5)
```

Why not `packages/db`: `09`'s module table lists it, but the CLI expects `<workdir>/supabase/migrations`, offers no setting to move it, and a root `supabase/` needs no flag in any command, CI step or editor tool (V2). The module row in `09` is rewritten (section 11). [AUTHOR, approved as D2]

Why `packages/contracts` imports nothing from `supabase/`: the Python package must install without the database. Database-dependent tests are marked `db` and run only when `MERMIA_DB_URL` is set.

## 5. Database design

### 5.1 Conventions

| Topic | Rule |
|---|---|
| Names | `snake_case`, singular table names exactly as in `09` §2, except the renames in 5.6. |
| Primary key | `id uuid primary key default app.uuid_v7()`. |
| Shared columns | Tenant-scoped tables carry `tenant_id uuid not null references tenant(id)`, `created_at timestamptz not null default now()`, `updated_at timestamptz not null default now()`, `version int not null default 1`. [DOC `09` §2] `audit_log` omits `updated_at` and `version`. [APPROVED] |
| Composite FKs | Every tenant-scoped table also has `unique (tenant_id, id)`. Every FK to another tenant-scoped table is `foreign key (tenant_id, x_id) references x (tenant_id, id)`, `on delete restrict`. [APPROVED D18, V12, V13] FKs to the tenant-less `app_user` are plain (`user_id references app_user(id)`). |
| Deletes | `restrict` everywhere. Rows are never deleted by design (`09` §2.6). |
| Optimistic concurrency | Trigger `app.touch_row()` on every table that has `updated_at`: sets `updated_at = now()`, `version = old.version + 1`, and refuses a change of `tenant_id`. Apply functions compare `base_version` to `version` (`09` §5.2). |
| Enums | Postgres enums only where `09`/`03`/`04` list the values (5.3). Anything else is `text` with a `COMMENT` reading `values not yet specified`, and no CHECK. [AUTHOR, 12.1 A8] |
| Text integrity | A `text` column never loses integrity checks because its values are unspecified: required columns are `NOT NULL`, and `app.add_text_checks(rel)` adds `check (col is null or btrim(col) <> '')` to every `text`/`varchar` column of the table (no value lists, no invented enums). Format checks stay where a document gives a format (`phone_e164`, `sha256`, `currency`, `parser`, `code`). The catalog test fails if a `text` column of `public` lacks the check or an explicit exemption. [AUTHOR, 12.1 A20] |
| Money units | Each money, price, quantity and percent column carries a tag in its `COMMENT` (5.4); the generator reads it. |
| Access class | Each table carries `COMMENT ON TABLE ... IS 'rls_class=<class>[;loc_col=<col>]'` (7.2), written by `app.secure_table`. The catalog test reads it and checks policies and grants against it. |
| Indexes | One index per FK, with `tenant_id` first. Plus the uniqueness rules in 5.7. Query-driven indexes belong to MR-17. |
| Schema `app` | Holds helper functions and enums. Not exposed to the Data API (V7). Never holds tables. |
| `public` | Domain tables only, and **no functions** (V24, 7.5.3). [APPROVED] The catalog test fails if any other table or any function appears there. |
| Extensions | None. `gen_random_uuid()` is built in; pgTAP is provided by the CLI test image (V3). |

### 5.2 UUIDv7

Postgres 17 has no `uuidv7()` [EXT]; Postgres 18 does [EXT]. Decision: vendor the **sub-millisecond** variant as `app.uuid_v7(ts timestamptz default clock_timestamp()) returns uuid` (`language sql volatile parallel safe`).

- Source: `dverite/postgres-uuidv7-sql`, function `uuidv7_sub_ms` in `sql/uuidv7-sql--1.0.sql`. License: PostgreSQL License, permissive. [V18]
- Obligation: the migration header reproduces the copyright line and the two disclaimer paragraphs from the upstream `LICENSE.md`, and names the function as adapted (renamed, moved to schema `app`). A test greps for the notice.
- Why sub-ms: 0 ordering inversions against 50,029 for the millisecond variant over 100k rows (V8). Ordered keys matter for index locality (`07`, `09` §9) and match native `uuidv7()` behaviour.
- Grants: `USAGE` on schema `app` and `EXECUTE` on `app.uuid_v7(timestamptz)` to `service_role` (V9). Client roles never insert, so they do not get it. `PUBLIC` and `anon` have no `EXECUTE`.
- Upgrade path: when the platform default becomes Postgres 18, a new migration can redefine `app.uuid_v7` as a wrapper around native `uuidv7()`. No column changes.
- Clients and the future POS may supply their own v7 ids; columns accept any `uuid`. [DOC `09` §9]
- Acceptance: a pgTAP test over at least 10,000 generated values checks version nibble 7, variant `8-b`, uniqueness, zero inversions in one statement, and timestamp round-trip. [VERIFIED as PoC (V8); to be re-run in pgTAP]

### 5.3 Enums (all in schema `app`)

Only values written in the docs. Postgres cannot drop enum values, so additions are `ALTER TYPE ... ADD VALUE` in later migrations.

| Enum | Values | Source |
|---|---|---|
| `member_role` | `owner, manager, admin, support` | `09` §2.1 (Phase 3 adds `cashier`, `waiter` per `09` §5.1/§9, `07`; added later) |
| `channel` | `whatsapp, web, pos` | `09` §2.1 `channel_identity` (reused by `consent_log`, `audit_log`, `conversation`) |
| `source_kind` | `sr_report, sr_corte_email, sr_erp_push, sr_connector, cfdi, photo_ocr, manual, mermia_pos` | `09` §2.1 |
| `batch_quality` | `file, push, ocr` | `09` §2.2 |
| `batch_status` | `received, rejected, parsed, needs_review, applied, rolled_back, superseded` | `09` §2.6 |
| `issue_severity` | `info, warning, error` | [APPROVED D12] |
| `menu_item_kind` | `dish, drink, modifier, combo` | `09` §2.3 |
| `sale_channel` | `dine_in, takeout, delivery_app, delivery` | `09` §2.3 |
| `ticket_status` | `paid, cancelled` | `09` §2.3 |
| `fiscal_status` | `none, requested, in_global, stamped` | `09` §2.3 |
| `payment_method` | `cash, card, transfer, voucher, other` | `09` §2.3 |
| `supplier_kind` | `cfdi, market, other` | `09` §2.4 |
| `base_unit` | `g, ml, pza` | `09` §2.4, `03` C.6 |
| `yield_source` | `default, measured` | `09` §2.4 |
| `purchase_doc_kind` | `cfdi, nota_photo, manual` | `09` §2.4 |
| `ingredient_price_source` | `cfdi, nota, sr_import, manual, benchmark` | `09` §2.4 (`03` says `ocr_note`; `09` is canonical) |
| `recipe_status` | `draft, confirmed` | `09` §2.4 |
| `cost_confidence` | `confirmed, estimated, missing` | `09` §2.5, `03` C.5 |
| `pending_change_status` | `pending, approved, rejected, expired, conflict, applied, failed` | `09` §2.5 |
| `proposed_via` | `agent, dashboard, import, pos` | `09` §2.5 |
| `actor_kind` | `user, system, agent` | `09` §2.5 |
| `report_kind` | `weekly, daily` | `09` §2.5 |
| `llm_route` | `template, haiku, sonnet, fallback` | `13` §I4 |
| `meta_pricing_category` | `marketing, utility, authentication, service` | `04` §4 |

Left as `text` (values not specified): `tenant.plan`, `tenant.status`, `source.status`, `location.sr_version`, `location.sr_edition`, `staff.role`, `raw_file.received_via`, `ingredient_price.confidence`, `pending_change.kind`, `pending_change.target_type`, `pending_change.resolved_via`, `alert.rule/status`, `price_suggestion.rule/status`, `report_run.status`, `message_log.direction`, `llm_usage.validator_result`. `pending_change.kind` stays text because `08` C5 lists five kinds while `09` §5.1 lists seven; MR-11 settles it (9.1 C7).

### 5.4 Units, conversion and rounding [APPROVED D6]

| Column kind | SQL type | Unit | Tag in `COMMENT` |
|---|---|---|---|
| Ledger amounts (sales, taxes, tips, discounts, totals, price, margin, dish cost) | `bigint` | **centavos** of `currency` (default `MXN`) | `unit=centavos` |
| Unit prices and unit costs (`ingredient_price.unit_price_net`) | `numeric(20,6)` | **pesos per base unit** (g, ml, pza) | `unit=pesos_per_base_unit` |
| Purchase line unit price (`purchase_line.unit_price_net`) | `numeric(20,6)` | **pesos per purchase unit** (the `unit` on the same row) | `unit=pesos_per_purchase_unit` |
| Quantities (units sold, `qty`, `qty_base`, `yield_qty`, `pack_qty`) and `factor` | `numeric(18,6)`; `factor numeric(20,10)` | the row's unit | `unit=quantity` |
| Percentages (`*_pct`) | `numeric(7,4)` | **percent points** (34.1 means 34.1 %, never the fraction 0.341) [APPROVED A5]; documented in `README.md`, in `09`, in the column `COMMENT` and in the generated field description | `unit=percent_points` |
| Tax rate | `numeric(5,4)` | fraction (0.1600 = 16 %) | `unit=fraction` |
| LLM and message cost | `numeric(12,6)` | USD | `unit=usd` |

Rules:

1. Peso to centavo: `round(pesos * 100)`, which in Postgres `numeric` rounds half away from zero. Done **once**, at the point a result is stored in a `bigint` column. Never round an intermediate.
2. Dish cost: `sum(recipe_line.qty_base / yield * unit_cost_pesos)` computed in `numeric`, then converted once to centavos for `dish_cost_snapshot.cost`. `food_cost_pct` is computed from unrounded values.
3. A price tied to a pack (CFDI `ValorUnitario` per `Unidad`) is converted to pesos per base unit with `unit_conversion` and `ingredient.default_yield_pct` / `yield_override_pct` (`03` C.6). Conversion lives in the costing engine (MR-25), not in MR-10.
4. Floating point is never used for money.
5. Currency: `currency char(3)` next to every ledger amount group, default `'MXN'` [AUTHOR, 12.1 A9], with `check (currency ~ '^[A-Z]{3}$')`.

Why unit prices are not centavos: `09` §2 says "money is `bigint` centavos", but `ingredient_price` stores a price per base unit. $18/kg is 1.8 centavos/g and CFDI lines can carry decimals. Recorded in 9.1 C2 and resolved by D6.

### 5.5 Cancellations [APPROVED D7]

`daily_sales_agg` gets `cancellations_amount bigint` and `cancellations_count int`, replacing the single `cancellations` column of `09` §2.3.

Match with sources (checked 2026-10-18):

| Source | What it says | Fit |
|---|---|---|
| `09` §4.1 RPC 6 | `get_cancellations` returns "count, amount, top items" | Both values are consumed. |
| `12` sample message | "cancelaciones: 14 vs 5, por $3,245.00" | The owner sees count and amount. |
| `01` Corte Z | contains "discounts, cancellations" | Format **unverified** (`01` says to get a sample). |
| `01` SR 8 reports | "Cancelaciones de cuentas / de productos" exist | Granularity (checks or items) unknown. |

Both columns are nullable, because a given report may give only one of them. The parser sets what the file gives and leaves the other null; metrics treat null as "not reported", not zero. [AUTHOR] This depends on the real Corte Z format (section 16, bucket 5); if the sample contradicts it, revise before MR-23.

### 5.6 Deviations from the column names in `09`

| `09` | MR-10 | Reason |
|---|---|---|
| `sale_ticket."table"` | `table_label` | `table` is a reserved word; quoting it everywhere is error-prone. [AUTHOR, 12.1 A4] |
| `daily_sales_agg.cancellations` | `cancellations_amount`, `cancellations_count` | D7. |
| `alert / price_suggestion` (one row in `09` §2.5) | two tables, `alert` and `price_suggestion` | `09` writes them as one row with a slash; `03` lists them as separate entities. `price_suggestion` adds `suggested_price bigint` and `rationale_code`. The split is a design reading, not a documented requirement. [AUTHOR, 12.1 A4] |
| `item_sales_agg.business_date (or period)` | `period_from date`, `period_to date` | Check `period_from <= period_to`; a single-day row has both equal. [AUTHOR, 12.1 A2] |
| `import_batch` (no `location_id`) | adds nullable `location_id` | `09` §2.6 defines `slice_key = (location_id, ...)`; the location filter needs a column. [AUTHOR, 12.1 A3] |
| `recipe.version` | `recipe.recipe_version` | `09` §2 gives every table a `version` column for optimistic concurrency and §2.4 also names the recipe revision `version`; the revision is stored as `recipe_version`. [AUTHOR, 12.1 A21, C18] |
| `alert`, `price_suggestion`, `report_run` (no `location_id`) | add nullable `location_id` | `get_cost_alerts(location_id?)` (`09` §4.1) and `build_weekly_report(location_id, period)` (`08`) take a location. [AUTHOR, 12.1 A3] |

### 5.7 Table inventory

Columns are exactly those of `09` §2.1-2.5 unless noted; this section adds types, keys and checks. "Shared" columns are those of 5.1. The access class letter is defined in 7.2 and explained per table there. Fact/catalog rule (`09` §2): tables in §2.3 also carry `location_id`, `source_id`, `external_id`, `batch_id`. For catalog rows these are nullable. For fact rows (`sale_ticket`, `sale_line`, `payment`, `item_sales_agg`, `daily_sales_agg`) `location_id`, `source_id` and `batch_id` are `not null`; `menu_item_price.location_id` is `not null`.

**§2.1 Tenancy, identity, sources (8)**

| Table | Class | Notes |
|---|---|---|
| `tenant` | T (root) | No `tenant_id` column (its `id` is the tenant). `name text not null`, `rfc text`, `plan text`, `settings jsonb not null default '{}'`, `status text`. `settings` holds food-cost target and report cadence (`09`) and owner-chosen KPIs (`07`). |
| `location` | L (`id`) | `name text not null`, `timezone text not null` (IANA name; validated by the app, no CHECK), `address text`, `sr_version text`, `sr_edition text`. |
| `app_user` | X | **No `tenant_id`.** `name text not null`, `phone_e164 text unique` with check `~ '^\+[1-9][0-9]{7,14}$'`, `email text`, `auth_user_id uuid unique` (no FK to `auth.users`, to avoid coupling to the auth schema [AUTHOR, 12.1 A6]). |
| `membership` | X | `user_id uuid not null`, `role member_role not null`, `location_ids uuid[] default '{}'` (null = all locations, `09` §2.1), **`all_locations boolean not null default false`**, `can_approve text[] not null default '{}'`. `unique (tenant_id, user_id)`. Check `all_locations = (location_ids is null)`: full scope needs **both** an explicit SQL null and the explicit flag, and a row inserted without stating the scope gets an empty list (no location). A tool that sends `None` by default is rejected instead of silently granting everything. A constraint trigger rejects `location_ids` elements that are not locations of the same tenant (claims are derived from this column, so integrity is a security property). The flag is an addition to `09` §2.1 for the A12 condition [AUTHOR, 12.1 A19]. |
| `channel_identity` | X | **No `tenant_id`.** `user_id`, `channel`, `external_id text not null`, `verified_at timestamptz`. `unique (channel, external_id)`. |
| `consent_log` | X | **No `tenant_id`.** `user_id`, `notice_version text not null`, `channel`, `accepted_at timestamptz not null`, `message_types text[] not null` (`04`: record who, when, which message types). |
| `source` | L (col) | `location_id` nullable, `kind source_kind not null`, `config jsonb not null default '{}'`, `api_key_hash text`, `status text`. Client roles may read all columns **except** `config` and `api_key_hash` (column-level grant, V22). |
| `external_ref` | X | `source_id`, `entity_type text`, `external_id text`, `internal_id uuid` (polymorphic, no FK). `unique (tenant_id, source_id, entity_type, external_id)`. |

**§2.2 Ingestion (3)**

| Table | Class | Notes |
|---|---|---|
| `raw_file` | X | `storage_path text not null`, `sha256 text not null` check `~ '^[0-9a-f]{64}$'`, `mime`, `filename`, `size bigint`, `received_via text`, `sender_user_id uuid references app_user(id)`, `received_at timestamptz not null default now()`, `retention_until timestamptz`. `unique (tenant_id, sha256)` (same file twice is ignored, `03` B.5). |
| `import_batch` | L | `source_id`, `raw_file_id`, `location_id` (added), `parser text not null`, `slice_key text not null`, `status batch_status not null default 'received'`, `stats jsonb not null default '{}'`, `supersedes_batch_id` (self), `quality batch_quality not null default 'file'`, `applied_by`, `applied_at`, `rolled_back_by`, `rolled_back_at` (user ids reference `app_user`). Partial unique index `(tenant_id, slice_key) where status = 'applied'` guarantees one current batch per slice; apply functions must flip statuses in the right order (unique indexes are checked per statement). [AUTHOR, 12.1 A7; behaviour under real apply ordering not yet verified] |
| `import_issue` | LP | `batch_id`, `severity issue_severity not null`, `code text not null`, `message_es text not null`, `row_ref text`. |

**§2.3 Catalog and sales facts (10)**

| Table | Class | Notes |
|---|---|---|
| `menu_category` | T | `name`, `parent_id` (self). Catalog columns nullable. |
| `menu_item` | T | `name`, `normalized_name`, `category_id`, `kind menu_item_kind not null default 'dish'`, `is_active bool not null default true`. Shared across locations: `location_id` null. |
| `menu_item_price` | L | `menu_item_id`, `location_id`, `price_gross bigint` (centavos), `tax_rate numeric(5,4)`, `effective_from date not null`, `effective_to date`, `source text`. Check `effective_to is null or effective_to >= effective_from`. |
| `modifier_link` | T | `menu_item_id`, `modifier_item_id`, `price_delta bigint` (centavos). |
| `staff` | T | `display_name text` (first name only), `external_id`, `role text`. Personal data: minimal. |
| `sale_ticket` | L | `business_date date not null`, `opened_at`, `closed_at`, `channel sale_channel`, `area text`, `table_label text`, `guests int`, `staff_id`, `subtotal, discount, tax, tip, total bigint`, `status ticket_status not null`, `fiscal_status fiscal_status not null default 'none'`. |
| `sale_line` | L | `ticket_id`, `menu_item_id`, `parent_line_id` (self, modifiers), `qty numeric(18,6)`, `unit_price bigint`, `discount bigint`, `tax bigint`, `net bigint`, `is_void bool not null default false`, `void_reason text`, `voided_by` (staff id). |
| `payment` | L | `ticket_id`, `method payment_method not null`, `amount bigint`, `tip bigint`, `provider text`, `provider_ref text`. |
| `item_sales_agg` | L | `location_id`, `period_from`, `period_to`, `menu_item_id`, `units numeric(18,6)`, `gross, discount, net bigint`. |
| `daily_sales_agg` | L | `location_id`, `business_date`, `net_sales, tax bigint`, `tickets int`, `guests int`, `discounts bigint`, `cancellations_amount bigint`, `cancellations_count int`, `payment_mix jsonb not null default '{}'`, `tips bigint`. |

**§2.4 Costing (9)**

| Table | Class | Notes |
|---|---|---|
| `supplier` | T | `name`, `rfc text` (null for informal suppliers), `kind supplier_kind`. |
| `ingredient` | T | `name`, `base_unit base_unit not null`, `category text`, `default_yield_pct numeric(7,4) not null default 100`, `yield_source yield_source not null default 'default'`. |
| `ingredient_alias` | T | `supplier_id`, `source_text`, `ingredient_id`, `pack_qty numeric(18,6)`, `pack_unit text`, `confirmed_by uuid references app_user(id)`. `unique (tenant_id, supplier_id, source_text)`. |
| `unit_conversion` | T | `ingredient_id` nullable (null = global), `from_unit text`, `to_unit text`, `factor numeric(20,10) not null`. `unique nulls not distinct (tenant_id, ingredient_id, from_unit, to_unit)`. |
| `purchase_doc` | T | `supplier_id`, `kind purchase_doc_kind`, `cfdi_uuid uuid`, `issued_at timestamptz`, `subtotal bigint`, `total bigint`, `raw_file_id`. `unique (tenant_id, cfdi_uuid)` (dedup key, `03` C.3). |
| `purchase_line` | T | `purchase_doc_id`, `description text`, `qty numeric(18,6)`, `unit text`, `unit_price_net numeric(20,6)` (pesos per purchase unit), `ingredient_id` nullable until mapped. |
| `ingredient_price` | T | `ingredient_id`, `unit_price_net numeric(20,6)` (pesos per base unit), `effective_from date not null`, `effective_to date`, `source ingredient_price_source not null`, `source_ref text`, `confidence text`, `batch_id`, `pending_change_id`. Check `num_nonnulls(batch_id, pending_change_id) <= 1`. Append-only by convention (priority rules in `03`). |
| `recipe` | T | `menu_item_id`, `produces_ingredient_id`, `version int not null`, `effective_from date`, `effective_to date`, `yield_qty numeric(18,6)`, `status recipe_status not null default 'draft'`. Check `num_nonnulls(menu_item_id, produces_ingredient_id) = 1`. |
| `recipe_line` | T | `recipe_id`, `ingredient_id`, `sub_recipe_id` (references `recipe`), `qty_base numeric(18,6) not null`, `yield_override_pct numeric(7,4)`. Check `num_nonnulls(ingredient_id, sub_recipe_id) = 1`. |

**§2.5 Control, metrics, operations (10)**

| Table | Class | Notes |
|---|---|---|
| `pending_change` | F | `kind text`, `target_type text`, `target_id uuid`, `base_version int`, `payload jsonb`, `diff jsonb`, `proposed_by_user uuid references app_user(id)`, `proposed_via proposed_via`, `required_role member_role`, `status pending_change_status not null default 'pending'`, `expires_at timestamptz`, `resolved_by`, `resolved_at`, `resolved_via text`. |
| `audit_log` | F (append-only) | **No `updated_at`, no `version`.** `ts timestamptz not null default now()`, `actor_user_id`, `actor_kind actor_kind not null`, `channel channel` (null for system), `action text not null`, `entity_type text`, `entity_id uuid`, `before jsonb`, `after jsonb`, `pending_change_id`, `batch_id`, `request_id text`. Trigger `BEFORE UPDATE OR DELETE` and statement trigger `BEFORE TRUNCATE` raise `42501`. Explicit privileges: `SELECT` to `authenticated` (class F policy) and to `service_role`; `INSERT` to `service_role` only; **everything else revoked from every role, `service_role` included** (`UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`; V11). The owner role is stopped by the triggers. |
| `dish_cost_snapshot` | L | `menu_item_id`, `location_id`, `date date`, `cost, price_net, margin bigint` (centavos), `food_cost_pct numeric(7,4)`, `confidence cost_confidence not null`. `unique (tenant_id, menu_item_id, location_id, date)`. |
| `daily_location_metrics` | L | `location_id`, `business_date`, `net_sales bigint`, `tickets int`, `avg_ticket bigint`, `theoretical_food_cost_pct numeric(7,4)`, `cost_coverage_pct numeric(7,4)`. `unique (tenant_id, location_id, business_date)`. |
| `alert` | L | `location_id` (added), `rule text`, `subject text`, `value numeric`, `threshold numeric`, `status text`. |
| `price_suggestion` | L | As `alert`, plus `suggested_price bigint` (centavos), `rationale_code text`. |
| `report_run` | X | `location_id` (added), `kind report_kind`, `period_from date`, `period_to date`, `recipients uuid[]`, `template text`, `status text`, `wa_message_ids text[]`. |
| `conversation` | X | `user_id`, `channel`, `summary text`, `last_turns jsonb`, `window_open_until timestamptz`. `unique (tenant_id, user_id, channel)`. |
| `llm_usage` | X | Fields of `13` §I4: `location_id`, `user_id`, `ts`, `request_id`, `route llm_route`, `model text`, `input_tokens`, `cache_read_tokens`, `cache_write_tokens`, `output_tokens int`, `cost_usd numeric(12,6)`, `latency_ms int`, `tool_calls int`, `validator_result text`, `error text`. |
| `message_log` | X | `wa_message_id text`, `direction text`, `template text`, `pricing_category meta_pricing_category`, `billable bool`, `cost_usd numeric(12,6)`. |

Four tables have no `tenant_id` column: `tenant` (its `id` is the tenant), `app_user`, `channel_identity` and `consent_log`. The other 36 carry it.

## 6. Migrations

### 6.1 Rules

- Created with `supabase migration new <name>` (CLI timestamp names). `08` says "numbered"; the timestamp prefix gives the same ordering and append-only discipline. [AUTHOR]
- Append-only: a merged migration is never edited. A fix is a new migration.
- Each migration applies cleanly on an empty database and in order.
- Every `create table` is followed by the `touch_row` trigger, the composite-FK parent key and a call to `app.secure_table(...)` **in the same migration**, which enables RLS, sets the grants and writes the access-class comment for that table's class. A table never exists without RLS and explicit grants.
- Column `COMMENT`s are written only where a unit tag or a "values not yet specified" note applies (5.1, 5.4).

### 6.2 Order

| # | Migration | Contents |
|---|---|---|
| 1 | `foundations` | schema `app`; `uuid_v7` (with the license header); `touch_row`; `block_mutation`; `current_tenant_id`; `can_see_location`; `has_all_locations`; `secure_table`; default-privilege revokes on `public` for `anon`/`authenticated` (tables, sequences, functions); schema grants (7.4). |
| 2 | `enums` | all enums of 5.3 in schema `app`. |
| 3 | `identity_and_sources` | `tenant`, `location`, `app_user`, `membership` (+ location-integrity trigger), `channel_identity`, `consent_log`, `source`, `external_ref`. |
| 4 | `ingestion` | `raw_file`, `import_batch`, `import_issue`. |
| 5 | `catalog_and_sales` | the 10 tables of §2.3. |
| 6 | `control` | `pending_change`, `audit_log` (+ triggers and revokes), `alert`, `price_suggestion`, `report_run`, `conversation`, `llm_usage`, `message_log`. |
| 7 | `costing` | the 9 tables of §2.4 (references `pending_change`). |
| 8 | `metrics` | `dish_cost_snapshot`, `daily_location_metrics` (reference catalog and `location`). |

Migrations 5 to 8 may be split further if a single file becomes hard to review. There is no size limit. [APPROVED]

## 7. Security design

### 7.1 Three layers (kept separate in the tests)

| Layer | What it controls | In MR-10 |
|---|---|---|
| SQL privileges (`GRANT`/`REVOKE`) | Which role may touch which object (and which columns) at all. Evaluated first. | Explicit grants per table and class. Default privileges revoked for `anon`/`authenticated`. |
| RLS | Which rows a role that already has the privilege may see. | One `SELECT` policy per client-readable table. No write policies. |
| Privileged roles | Who ignores RLS. | `service_role` and `postgres` have `BYPASSRLS` (V5). `SECURITY DEFINER` functions owned by `postgres` bypass RLS and must check tenant, location and role themselves (`09` §6, 7.5.7). `FORCE ROW LEVEL SECURITY` is **not** used: both roles carry `BYPASSRLS` (V5, verified) and, by general Postgres behaviour (not run here), that attribute ignores `FORCE`, so it would add nothing for owner-run definers. [DOC `09` §6] |

### 7.2 Access classification of the 40 tables [resolves O1]

#### 7.2.1 Method

For each table: (a) who writes it, (b) who is documented to read it and how, (c) whether the row can be tied to a location by a column or by a parent row, (d) whether any documented consumer needs a client session to read it. The class follows from the answers. Where the docs are silent, the table is marked **ambiguous** and handled in 7.2.3.

| Class | Meaning | Policy and grants | Tables |
|---|---|---|---|
| **T** tenant-wide | Any member of the active tenant may read, whatever their locations. | `SELECT` to `authenticated`; policy `tenant_id = (select app.current_tenant_id())`. (`tenant` root: `id = ...`.) | 14 |
| **L** location-scoped | Tenant plus location authorization. | As T, plus `and app.can_see_location(<location column>)`. Rows whose location column is null are tenant-level: visible with an explicit all-locations scope or a non-empty list, not with an absent, empty or malformed claim (V29). | 13 |
| **LP** location inherited from a parent | Child of a located row; no own location column. | As T, plus `exists (select 1 from <parent> p where p.tenant_id = child.tenant_id and p.id = child.<fk>)`; the parent's RLS applies inside the subquery (V19). | 1 |
| **F** full-tenant members only | Tenant-wide data with no location column that may reveal other locations; readable only by members whose claim is explicit JSON `null` for `location_ids` ("all locations"). | As T, plus `and app.has_all_locations()` (V21). | 2 |
| **X** backend-only | No client session reads it directly. | RLS enabled, **no policy**, no grants to `anon` or `authenticated`. Only `service_role` (and, in MR-14, the hook role for `membership`) accesses it. | 10 |

#### 7.2.2 Per-table matrix

Documented operation = what the architecture says reads or writes the table. "Backend" means the FastAPI service using `service_role` (`09` D8: the service role is used by ingestion and the apply functions).

| Table | Class | Reason (evidence) | Mechanism |
|---|---|---|---|
| `tenant` | T | `get_food_cost_pct` returns the target from `tenant.settings` (`09` §4.1 #8, §2.1); dashboard KPIs saved in `settings` (`07`). Root row: the member's own tenant. | `id = current_tenant_id()` |
| `menu_category` | T | Shared catalog, no location (`09` §2.3); `get_top_dishes(category)`. | tenant policy |
| `menu_item` | T | "Shared across locations" (`09` §2.3). | tenant policy |
| `modifier_link` | T | Catalog; no location (`09` §2.3). | tenant policy |
| `staff` | T | No location column (`09` §2.3); `get_sales_breakdown(by staff)` and `get_cancellations` "by staff (first names)" (`09` §4.1 #5, #6). First names only. | tenant policy |
| `supplier`, `ingredient`, `ingredient_alias`, `unit_conversion` | T | Costing master data is tenant-level; managers propose and approve `ingredient_price.set` and `ingredient_alias.confirm` for the tenant (`09` §5.1, no location dimension). | tenant policy |
| `purchase_doc`, `purchase_line` | T | Supplier invoices have no location (`09` §2.4); read by cost RPCs (`get_cost_alerts`, `get_dish_margin`). | tenant policy |
| `ingredient_price`, `recipe`, `recipe_line` | T | Read by `get_dish_margin`, `get_cost_alerts`, `get_food_cost_pct` (`09` §4.1); tenant-level catalog changed by tenant-wide approvals (`09` §5.1). | tenant policy |
| `location` | L (`id`) | `compare_locations` and `location_id` arguments act on "every location the user can see" (`09` §4.1); a manager is scoped to one location (`12` §4a, `05` risk 3). | `can_see_location(id)` |
| `source` | L (col) | `get_data_status` reads "last batch per source" (`09` §4.1 #11), so clients need to read it; `location_id` is documented (`09` §2.1); `config` and `api_key_hash` hold secrets by purpose. | `can_see_location(location_id)`; column grant excludes `config`, `api_key_hash` (V22) |
| `import_batch` | L | Read by `get_data_status`; location is part of `slice_key` (`09` §2.6); one uploader per branch (`05` risk 3). Column added (5.6). | `can_see_location(location_id)` |
| `menu_item_price`, `sale_ticket`, `sale_line`, `payment`, `item_sales_agg`, `daily_sales_agg`, `dish_cost_snapshot`, `daily_location_metrics` | L | `location_id` documented in `09` §2.3, §2.5 (`09` D1 puts it on every fact row); read by RPCs 1-6, 8-10 as the user (`09` §4.1). | `can_see_location(location_id)` |
| `alert`, `price_suggestion` | L | `get_cost_alerts(since, location_id?)` returns them (`09` §4.1 #10). Null location = tenant-level (e.g. ingredient price jumps), visible to members who have at least one location or all of them (V29). | `can_see_location(location_id)` |
| `import_issue` | LP | "Shown to the manager in Spanish" (`09` §2.2); the manager is scoped to the batch's location (`12` §4d). Today the backend composes those messages; full detail in the dashboard comes "later" (`03` B.5). The issue has no location of its own, so it follows its batch (V19). | parent `import_batch` visibility |
| `pending_change` | F | **Ambiguous** (7.2.3, AMB-1). Dashboard lists changes "filter by location" (`09` §5.3); approvals are role-based with no location dimension (`09` §5.1); `diff` and `payload` can mention several locations; the row has no location column. | `has_all_locations()` |
| `audit_log` | F | **Ambiguous** (AMB-1). Dashboard "full audit view" (`09` §5.3); `before`/`after` can mention any location; no location column. Append-only (`09` §2.5). | `has_all_locations()` + immutability (8) |
| `raw_file` | X | **Ambiguous** (AMB-2). Written by the webhook before the location is known ("locationHint read from the file", `09` §3); read by the backend to parse and re-parse (`09` §2.2); no RPC or documented dashboard feature reads it; contains `sender_user_id` and filenames. | none for clients |
| `report_run` | X | Written and read by the report job and delivery (`08` Reports row; `09` §2.5); `recipients` are user ids; no client consumer documented. | none for clients |
| `membership` | X | **Ambiguous** (AMB-4). Read by the backend to resolve a sender and by the MR-14 hook; the claim carries `tenant_id`, `app_role`, `location_ids`, so no policy needs it; no RPC reads it. | none for clients (hook role added in MR-14) |
| `external_ref` | X | Internal mapping of SR product codes and CFDI ids (`09` §2.1); parsers only. | none for clients |
| `conversation` | X | Short memory of one user's chat (`09` §2.5, `13` §I1); private to that user and the agent. | none for clients |
| `llm_usage`, `message_log` | X | Internal cost metering and Meta reconciliation (`13` §I4, `04`); MermIA business data, not tenant data. | none for clients |
| `app_user`, `channel_identity`, `consent_log` | X | No `tenant_id` by design (D10); phone numbers and consent evidence are personal data (`05` risk 10, 11); resolved by the backend. | none for clients |

Counts: T 14 (`tenant` plus 13), L 13, LP 1, F 2, X 10 = 40.

#### 7.2.3 Ambiguities, recommendations and consequences

| Id | Ambiguity and evidence | Options | Recommendation and consequences |
|---|---|---|---|
| AMB-1 | `pending_change` and `audit_log`: `09` §6 requires "an additional location filter" without saying which tables. `09` §5.1 gives roles but no location rule. `09` §5.3 lists the dashboard views (Phase 2) with "filter by location", which is a filter, not an authorization. No location column. | (a) T: any member reads. (b) F: only members with all locations. (c) L via a new location column derived from the target (price changes are tenant-wide, so most rows would be null). (d) X: backend/RPC only. | **(b) F.** Fail-safe: no documented reader needs a location-limited session to list changes or audit rows. Today a manager sees pending changes only in WhatsApp, composed by the backend (`09` §5.2, `12` §4). Consequence: a location-limited manager cannot list `pending_change` or `audit_log` from a user session; the Phase 2 dashboard needs a `SECURITY DEFINER` RPC or a policy change (a ticket after MR-10). Opening it later is cheap; undoing a leak is not. Needs approval (12.1 A13). |
| AMB-2 | `raw_file`: no documented client reader. The location is not known at receipt. | (a) X. (b) L via the import batch (`exists` on `import_batch.raw_file_id`). | **(a) X.** The file is evidence for the backend; the manager sees a summary built from `import_batch` (`12` §4d). If a dashboard "uploads" list appears, add (b). Needs approval (12.1 A1). |
| AMB-3 | `import_issue`: `09` says issues are shown to the manager, but the only documented reader is the backend. A direct client read is "later" (`03` B.5). | (a) X now. (b) LP now. | **(b) LP.** The class costs nothing (V19), keeps location isolation if a client ever reads it, and the backend is unaffected (it bypasses RLS). Needs approval (12.1 A14). |
| AMB-4 | `membership`: roles and location lists of colleagues. No documented client reader; the claim already carries what policies need. | (a) X. (b) T. | **(a) X.** The team view in the dashboard (`settings.update`, owner) is not documented as a direct read. The hook (MR-14) gets its own grant. Needs approval (12.1 A1). |
| AMB-5 | Meaning of an **absent** `location_ids` claim. `09` §2.1: `membership.location_ids` null = all. A claim built by hand or by a buggy issuer could omit the key. | (a) absent = all. (b) absent = none; "all" must be the explicit JSON `null`. | **(b) fail-closed** (V20). Consequence: every issuer must always set the claim. A missing key can never widen access. Needs approval (12.1 A12). |
| AMB-6 | `staff` and the T-class catalog and costing tables carry no location; a location-limited manager reads them for the whole tenant. | (a) accept. (b) add location columns. | **(a) accept.** Matches the approval matrix (managers handle tenant-wide costing, `09` §5.1) and `staff` holds first names only. No new column is invented. |
| AMB-7 | Whether `support` (MermIA staff) membership is location-limited. `09` §2.1: "can propose but never approve". | - | Not decided here; `support` follows the same claim rules as any member. |

#### 7.2.4 Do the policies fit the expected operations?

| Documented operation | Reads | Class needed | Satisfied |
|---|---|---|---|
| RPCs 1-6 (sales, compare, top dishes, breakdown, cancellations), run as the user | `daily_location_metrics`, `item_sales_agg`, `daily_sales_agg`, `sale_*`, `payment`, `menu_item`, `menu_category`, `staff`, `location` | L, T | yes |
| RPCs 7-10 (margin, food cost, menu engineering, cost alerts) | `dish_cost_snapshot`, `recipe`, `recipe_line`, `ingredient`, `ingredient_price`, `alert`, `price_suggestion`, `tenant` | L, T | yes |
| RPC 11 `get_data_status` | `import_batch`, `source` (safe columns) | L | yes |
| Upload pipeline, apply, rollback, confirmations, reports, metering | all writes; reads of `raw_file`, `import_issue`, `membership`, `app_user`, `channel_identity`, `consent_log`, `report_run`, `external_ref`, `conversation`, `llm_usage`, `message_log` | X via `service_role` | yes (no client path needed) |
| Dashboard Phase 2: pending changes and audit view for owners | `pending_change`, `audit_log` | F | yes for all-location members; location-limited roles need a later RPC (AMB-1) |
| Manager upload summary and issues (WhatsApp) | `import_batch`, `import_issue` | composed by the backend | yes |
| Any client write | none | - | denied by privileges (30_write_denial); writes go through `pending_change` and apply functions (`09` D7) |

Not covered by MR-10 because no RPC exists yet: views (`v_item_sales_daily`, `v_daily_sales`, `09` §2.6) must be `security_invoker` (8.1). A `SECURITY INVOKER` RPC that needs a class X table is not possible; it must be `SECURITY DEFINER` with its own checks (7.5.7).

#### 7.2.5 Indirect exposure paths [A1, A14 condition]

A column or table can leak without a direct `SELECT`: through a view, an embedded relationship, an exposed function, or another API surface.

| Path | Rule in MR-10 | Checked by |
|---|---|---|
| Views | MR-10 creates **no view** in `public`. Later views must be `security_invoker = true` (8.1). | `50_exposure`: zero views in `public` |
| Functions | **No function in `public`**; every function in `app` has no `PUBLIC`/`anon`/`authenticated` `EXECUTE` except the three helpers; no function in `public` or `app` calls `set_config` on `request.jwt.*`. | `00_catalog`, `50_exposure` |
| Embedded relationships (PostgREST) | A client-readable table whose foreign key points at a class X table exposes no data from it: the embedded table needs its own privilege and policy, which class X denies. Relationships between readable tables apply both tables' policies (V13, V19). | `50_exposure` lists every FK from a client-readable to a class X table; `test_rest_exposure.py` embeds them and expects no data |
| Parent-inherited rows (`import_issue`) | Direct (`import_issue`), embedded from the parent (`import_batch?select=*,import_issue(*)`) and embedded from the child (`import_issue?select=*,import_batch(*)`) all show only rows of locations the claim allows. | `20_location`, `test_rest_exposure.py` |
| Hidden columns (`source.config`, `source.api_key_hash`) | Column grants exclude them: `select *`, explicit selection and embedding (`import_batch?select=*,source(*)`) fail or omit them. | `00_catalog`, `20_location`, `test_rest_exposure.py` |
| GraphQL (`/graphql/v1`, `pg_graphql`) | It runs as the caller's role, so the same privileges and policies apply; class X tables and the hidden columns must not be queryable. | `test_rest_exposure.py` (result recorded; if the local stack lacks the route, it is reported as not run) |
| Generated types and the OpenAPI document | They describe what the role can read; they are not an access path. Tables without client grants must not appear for `authenticated`. | `test_rest_exposure.py` (OpenAPI check, if served) |
| Columns of `NormalizedBatch` / models | The Python package contains no secrets and reads nothing at import. | review |

Residual: PostgREST exposes the foreign-key names of readable tables; that is schema metadata, not data.

#### 7.2.6 `pending_change` and `audit_log`: four separate concerns [A13 condition]

MR-10 provides only the **data model and the read rule**. It does not approve or execute anything, and it adds no RPC for single-location managers (a later phase, AMB-1).

| Concern | Who | Mechanism | Ticket |
|---|---|---|---|
| **Visibility** of pending changes | `authenticated` with explicit `location_ids: null` and a matching tenant (class F). Location-limited members: none. `service_role` always. | `SELECT` policy `tenant_id = current and has_all_locations()` | MR-10 |
| **Approval** of a change | The human approver: role from `required_role` and `membership.can_approve` (`09` §5.1); never the LLM (`09` §5.2). The approval is a button tap relayed by the backend, or a dashboard call, **not a table write**. | Backend or RPC that calls the apply function; clients cannot write `pending_change` (no write privilege, no policy) | MR-32, MR-37 |
| **Execution** of a change | `apply_pending_change(id, user_id)`: tenant from the row, role, status `pending`, expiry, `version = base_version`, location authorization for located targets; writes the audit row in the same transaction | `SECURITY DEFINER`, `EXECUTE` for `service_role` only (V23) | MR-32 |
| **Audit reading** | Same as visibility: all-location members, plus `service_role` | `SELECT` policy of class F | MR-10 |
| **Audit writing** | `service_role` and the definer functions only | Privilege `INSERT` for `service_role` only; clients have none | MR-10 (privilege), MR-32 (writers) |
| **Audit immutability** | Nobody | `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` revoked from every role; triggers raise `42501` for the owner role | MR-10 |

### 7.3 Claims and helpers [APPROVED D3; semantics of absence: 12.1 A12]

| Claim | Type | Meaning |
|---|---|---|
| `tenant_id` | string (uuid) | The active tenant. Required. |
| `app_role` | string | MermIA role in that tenant (`member_role`). **Not read by any MR-10 policy.** Reserved for privileged functions and MR-14. Never use the JWT claim `role` for this (7.5.4). |
| `location_ids` | array of strings, **or explicit JSON `null`** | The locations the member may see. Explicit `null` means all locations of the tenant (`membership.location_ids` null = all, `09` §2.1). **An absent key means none** (fail-closed, V20). |

Helpers (schema `app`, `language sql stable`, `set search_path = ''`). Reference bodies, verified in the PoC (V19-V21):

```sql
create function app.current_tenant_id() returns uuid language sql stable set search_path = '' as $$
  select case when (auth.jwt()->>'tenant_id') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
              then (auth.jwt()->>'tenant_id')::uuid end
$$;

create function app.can_see_location(loc uuid) returns boolean language sql stable set search_path = '' as $$
  select case
    when auth.jwt() is null then false
    when jsonb_typeof(auth.jwt()->'location_ids') = 'null' then true
    when jsonb_typeof(auth.jwt()->'location_ids') = 'array' then
      jsonb_array_length(auth.jwt()->'location_ids') > 0
      and not exists (select 1 from jsonb_array_elements(auth.jwt()->'location_ids') e
                      where jsonb_typeof(e) <> 'string')
      and (loc is null or (auth.jwt()->'location_ids') ? loc::text)
    else false end
$$;

create function app.has_all_locations() returns boolean language sql stable set search_path = '' as $$
  select coalesce(jsonb_typeof(auth.jwt()->'location_ids') = 'null', false)
$$;
```

Behaviour verified: missing claim, malformed `tenant_id`, no claims, empty array, wrong type and absent `location_ids` all yield no rows; explicit `null` yields the whole tenant (V10, V20, V21). A malformed claim never raises an error; it denies. Policies call `current_tenant_id()` as `(select app.current_tenant_id())` so Postgres evaluates it once per statement (`09` §6, [EXT]). A null location column (tenant-level row) is visible to members with an explicit `null` or a non-empty well-formed list, and to nobody else (V22, V29).

`app.secure_table(rel regclass, mode text, loc_col text default null)`: one function that applies a class to a table in the same migration that creates it (`mode` is one of `tenant`, `location`, `full`, `backend`, with `parent` and `tenant_root` written explicitly in the migration). It enables RLS, revokes everything from `anon` and `authenticated`, applies the grants and the policy of the class, and sets the `rls_class` table comment. The class behaviours were verified one by one in the PoC (V10, V19-V22); **the combined multi-mode function is new and unverified** until implementation phase 3.

### 7.4 Grants on the helper schema

`USAGE` on schema `app` and `EXECUTE` on the three helpers to `authenticated`. `USAGE` on `app` and `EXECUTE` on `app.uuid_v7` to `service_role`. Nothing to `anon` or `PUBLIC`. Policies run helper functions with the invoker's privileges (V9, V10). Every future `SECURITY DEFINER` function follows the V23 pattern.

### 7.5 Trust boundary for JWT claims [resolves O2]

#### 7.5.1 What RLS does and does not do

RLS reads `tenant_id` and `location_ids` from the session's claims and filters rows. It has no way to know who produced those claims. **RLS does not make a claim trustworthy.** Everything below describes what makes the claims trustworthy and which part MR-10 can test and which part it cannot.

#### 7.5.2 Who may issue claims, and when they count as trusted

| Issuer | Phase | Trusted when | Built in |
|---|---|---|---|
| Supabase Auth (GoTrue) with the `custom_access_token` hook | 2 (dashboard) | The hook computes claims **inside the database from `membership`**, looked up by the authenticated user id; it takes nothing from client input or from `user_metadata` (user-editable); the hook function is executable only by `supabase_auth_admin`. [EXT] | MR-14 / Phase 2 |
| MermIA backend | 1 (agent, jobs) | After the checks in 7.5.6, it either signs a short-lived JWT with a signing key only it holds, or opens a database session as `authenticated` and sets `request.jwt.claims` inside the transaction. Both are consistent with `09` D8 and §6. Mechanics for signing: Supabase-generated keys cannot be exported; importing your own key requires rotating to it. [EXT] | MR-27 / MR-29 |

Never issuers: any client; the LLM; tool arguments; WhatsApp message content; `user_metadata`; any value a user can edit. The `service_role` key and the JWT secret are server-only and never reach the LLM path (`09` §6). [DOC]

#### 7.5.3 What a client cannot choose

| Claim | Why a client cannot set it | Evidence |
|---|---|---|
| `tenant_id`, `location_ids`, `app_role` | They are inside a signed token. A token altered by the client fails signature verification. | V13 (`401 PGRST301`) |
| any claim | Request headers cannot supply claims. | V25 |
| any claim | The Data API exposes only `public` and `graphql_public`, and `public` holds no functions, so a client cannot reach `set_config` or any function that sets claims. | V7, V24 |
| privileged role | The `role` claim picks the Postgres role. A user token must carry `authenticated`; the issuer sets it, the client cannot. | V13, V14 |

Assumption the model rests on: **clients have no raw-SQL path.** `authenticated` can call `set_config('request.jwt.claims', ...)` in raw SQL (V26). Therefore: no function that sets `request.jwt.*` settings may ever be exposed in `public` or any exposed schema; no RPC or tool may run caller-supplied SQL; MR-10 keeps `public` free of functions and the catalog test fails otherwise. `SET ROLE` is decided by the session user, and the PostgREST login role `authenticator` is a member of `service_role` (V28), so the absence of a raw-SQL path is the only barrier; `30_write_denial` pins the memberships the database does guarantee (`authenticated` and `anon` are not members of `service_role` or `postgres`).

#### 7.5.4 `role` (Postgres) versus `app_role` (application)

| Claim | Consumer | Effect |
|---|---|---|
| `role` | PostgREST | Selects the Postgres role: `anon`, `authenticated` or `service_role`. It decides SQL privileges and whether RLS is bypassed. A token with `role=service_role` reads everything (V14). User tokens must always carry `authenticated`. |
| `app_role` | Application code and privileged functions | MermIA role in the tenant (`owner`, `manager`, `admin`, `support`). Changes no SQL privilege. MR-10 policies do not read it. Privileged functions should **re-derive the role from `membership`** and use the claim only as a hint, because the claim is a snapshot (7.5.5). |

#### 7.5.5 How claims relate to membership and locations

| Claim | Derived from | Guarantee provided by MR-10 |
|---|---|---|
| `tenant_id` | `membership.tenant_id` of the chosen membership (the issuer chooses the active tenant explicitly when a user has several, `09` §2.1) | `unique (tenant_id, user_id)`; composite FKs keep all tenant data inside the tenant (V12) |
| `app_role` | `membership.role` | enum `member_role` |
| `location_ids` | `membership.location_ids`: SQL null becomes JSON `null` (all); an array stays an array | a trigger rejects `location_ids` that are not locations of the same tenant (integrity of the source of the claim) |

Claims are a snapshot taken at issue time. A change or revocation in `membership` takes effect when a new token is issued (hook: next refresh [EXT]; backend: next issue). A short token lifetime bounds the staleness; its value is set in MR-27 and is not decided here.

#### 7.5.6 What the backend must validate before issuing a token (MR-27, MR-29)

1. Sender identity: the `channel_identity` for the channel and `external_id` exists and `verified_at` is set. **Unknown senders are ignored** (`09` §2.1).
2. Consent: an accepted `consent_log` entry for the current notice version (`04`, `05` risk 10; MR-29).
3. Membership: a `membership` row exists for the user in the chosen tenant. If the user has several, the tenant is chosen explicitly (never from message content).
4. Claims are computed from that membership only (7.5.5); `role` is fixed to `authenticated`; no claim comes from the message, the LLM or the client.
5. Short expiry; no `service_role` token on any user or LLM path.
6. Button payloads and ids are re-checked against the database (`04` §6, `09` §5.2): the target belongs to the tenant, is not expired, not already resolved.

#### 7.5.7 What future privileged functions must validate (MR-16, MR-17, MR-32)

1. `security definer`, `set search_path = ''`, `EXECUTE` revoked from `PUBLIC`, `anon` and `authenticated` and granted deliberately (V23).
2. Derive the tenant from the target row, never from an argument (`09` §6: "explicit tenant checks").
3. If the signature carries the acting user (`apply_pending_change(id, user_id)`, `08` C5), grant `EXECUTE` to `service_role` only and verify in the database: the user belongs to the target's tenant, the role is allowed by `required_role` and `can_approve`, the status is `pending`, it is not expired, and the target `version` equals `base_version` (`09` §5.2).
4. For targets that have a location (for example a batch approval), authorize the location from `membership`, not from the claim alone. [recommendation; not in the docs]
5. Write the `audit_log` row in the same transaction.
6. Views created `security_invoker = true`; RPCs that need class X tables are `SECURITY DEFINER` with these checks (8.1).

#### 7.5.8 Risks RLS cannot address

Compromise or leak of the signing key or the `service_role` key (V14); an issuer that chooses the wrong tenant or location; token replay until expiry; stale claims after a membership change. MR-10 tests everything below the claim. It does not, and cannot, secure the issuer.

#### 7.5.9 What this section does not introduce

No new authentication architecture. The mechanisms are those already in `09` D8 and §6 (a hook for the dashboard; a backend-issued identity for the agent). Production custody of keys is out of MR-10 (7.6).

#### 7.5.10 Issuing the `location_ids: null` (all locations) claim [A12 condition]

`null` widens access to every location of the tenant, so it is the most sensitive value of the claim.

| Question | Answer |
|---|---|
| Who may issue it | Only a trusted issuer (7.5.2): the `custom_access_token` hook (MR-14) or the MermIA backend (MR-27/29). Never a client, the LLM, a tool argument or message content. |
| Under what condition | Only when the chosen `membership` row has `all_locations = true` **and** `location_ids is null`. The database check makes the two inseparable (5.7). A membership created without stating its scope has an empty list, so the issuer emits `[]` (no location). |
| How the issuer validates it | By reading `membership` inside the database (the hook) or through the backend's own database read, keyed by the verified user and the explicitly chosen tenant. The issuer never copies a scope from the request. |
| Which roles may hold it | Not restricted by MR-10. Role/scope pairing (for example `owner`) is a product rule for MR-14/29; MR-10 records it as a dependency (7.6). |
| How a client cannot obtain it | The scope lives in `membership`, a class X table with no client privilege and no policy; clients cannot write it (V10, V22, V24). The token is signed (V13). Headers are ignored (V25), but that is **not** the proof: the proof is signature verification, key custody and the absence of any client path to SQL or to a claim-setting function (7.5.3, V26). |
| How an exposed function cannot grant it | `public` has no functions; no function in `public` or `app` may call `set_config` on `request.jwt.*` (test); future definers follow 7.5.7 and are executable only by `service_role` or `supabase_auth_admin`. |
| What is still not guaranteed | A compromised issuer or key can mint `null` (V14). Production key custody and issuer tests are conditions in 7.6, outside MR-10. |

### 7.6 Conditions for production and the tickets that carry them

| Condition | Ticket | Needed before |
|---|---|---|
| Signing key (or backend database credentials) held only in the host's secret store; not in the repo, not in the LLM path; a rotation procedure; the legacy shared secret not used in production [EXT recommends signing keys over a shared secret] | MR-9 (accounts), MR-27/29 (issuer), MR-40 (deploy) | any real tenant data |
| `custom_access_token` hook reads `membership` only, grants limited to `supabase_auth_admin`; a test that hook output equals `membership` | MR-14 / Phase 2 | dashboard use |
| Behavioural tests with the real issuer: tenant B cannot read tenant A through the RPCs; a location-limited token cannot read another location (`08` manual test step 7) | MR-31, MR-41 | go-live |
| Privileged functions follow 7.5.7 | MR-16, MR-32 | their merge |
| Views `security_invoker`; RPCs that need class X tables are definers with checks | MR-17, MR-24 | their merge |
| Token lifetime and `sub` mapping (user id versus `auth_user_id`) decided | MR-27 / MR-29 | issuer merge |
| Production deploy never receives the local demo secret | MR-40 | deploy |
| Role and scope pairing for `all_locations = true` memberships, and issuer tests that a membership without the flag never yields `null` | MR-14, MR-29 | first real issuer |

## 8. Triggers, functions and integrity

| Object | Behaviour | Tested by |
|---|---|---|
| `app.touch_row()` | `BEFORE UPDATE`: sets `updated_at = now()`, increments `version`, raises if `tenant_id` changed (compared through `to_jsonb(old)` so it also works on tables without that column). Attached to every table with `updated_at`. | `40_integrity` |
| `app.block_mutation()` | Raises `42501 audit_log is append-only`. Row trigger on `UPDATE`/`DELETE` and statement trigger on `TRUNCATE` for `audit_log`. | `30_write_denial`, `40_integrity` |
| Membership location trigger | Rejects `location_ids` that are not locations of the membership's tenant. | `40_integrity` |
| Composite FKs | Reject cross-tenant references, for every role (V12). | `40_integrity` |
| Partial unique index on `import_batch` | One `applied` batch per `(tenant_id, slice_key)`. | `40_integrity` |
| `num_nonnulls` checks | `recipe`, `recipe_line`, `ingredient_price`. | `40_integrity` |
| No functions in `public` | The Data API cannot reach claim-setting functions (7.5.3). | `00_catalog` |

### 8.1 Note for later tickets

Views over these tables must be created `with (security_invoker = true)`, otherwise they run with the owner's privileges and `postgres` has `BYPASSRLS` (V5). `SECURITY INVOKER` RPCs (`09` §4.1) need `SELECT` on every table they read; class X tables are not readable by clients, so an RPC that needs one must be `SECURITY DEFINER` with its own checks (7.5.7). Not done in MR-10.

## 9. Contradictions, evidence and how this spec handles them

### 9.1 Contradictions found

| # | Evidence | Handling |
|---|---|---|
| C1 | Ticket #10 and `08` ("Everything lives in `packages/contracts`", C1 row) place the SQL migrations in `packages/contracts`; `09` §1 places them in `packages/db`. | [APPROVED D2] root `supabase/`. Update `08`, `09`, the tickets (section 11). |
| C2 | `09` §2: money is `bigint` centavos. `09` §2.4 `ingredient_price.unit_price_net` is "per base unit" (`03` C.6: g, ml, pza). | [APPROVED D6] split rule, 5.4. |
| C3 | `09` D8: the JWT holds "tenant_id, role and locations". PostgREST uses `role` as the Postgres role. | [APPROVED D3] `app_role` (7.5.4). Update `09` D8 and §6. |
| C4 | `09` §2: `tenant_id` on every table. `09` §2.1 `app_user`: one person can belong to several tenants. | [APPROVED D10] three tenant-less tables, backend-only. |
| C5 | `09` §2/§9 and `07`: UUIDv7 everywhere. The platform default is Postgres 17, which has no `uuidv7()`. | [APPROVED D5] vendored function, 5.2. |
| C7 | `08` C5: 5 `PendingChange` kinds. `09` §5.1 also names `ingredient_alias.confirm` and `settings.update`. | `pending_change.kind` stays `text`; MR-11 decides. |
| C9 | `09` §2: `updated_at` and `version` on every table. `09` §2.5: `audit_log` is append-only. | [APPROVED] omit in `audit_log`. |
| C10 | `08` MVP: roles "owner, manager, support". `09` §2.1 adds `admin`. `07` and `09` §5.1/§9 add `cashier`, `waiter` in Phase 3. | Enum has the four roles of `09` §2.1; Phase 3 adds values. |
| C11 | `09` §4.1 `get_cancellations` "by staff" and `get_sales_breakdown` by `staff`, `hour`; `14` bases leak patterns on per-waiter reports (`11` E3, E4, E6). The aggregate tables of §2.3 have no staff or hour dimension. `06` §5 puts Cancelaciones/Descuentos in the MVP; `08` does not. | [APPROVED] out of MR-10. A later table can be added without touching these. |
| C12 | `09` §2: no `location_id` column on `import_batch`, `alert`, `price_suggestion`, `report_run`, but `slice_key` includes a location and `get_cost_alerts`, `build_weekly_report` take one. | Nullable `location_id` added (5.6, 12.1 A3). |
| C13 | External docs say a minted JWT cannot go in the `apikey` header; the local stack accepted it (V17). | Not MR-10's concern; recorded for MR-14/27. |
| C14 | `03` says `ingredient_price.source` includes `ocr_note`; `09` says `nota`. | `09` is canonical (`03` states this itself). |
| C15 | `09` §6 requires an "additional location filter" without saying which tables; `09` §5.1/§5.3 give no location rule for approvals or the audit view. | Resolved per table in 7.2; the ambiguous cases are AMB-1 to AMB-7 and need approval. |
| C18 | `09` §2 gives every table a `version` column (optimistic concurrency) and §2.4 names the recipe revision `version` too. | Revision stored as `recipe_version` (5.6, A21). |
| C17 | `09` §2.1: `membership.location_ids` null means all locations, so a NULL by default or by omission widens access. | Explicit `all_locations` flag and an empty-list default (5.7, A19). |
| C16 | `09` §2.2 `import_issue` is "shown to the manager", yet the only documented reader is the backend; `03` B.5 says full detail in the dashboard "later". | Class LP (AMB-3). |

### 9.2 Severity check [APPROVED D12]

`severity` appears only in `09` §2.2 (`import_issue`) and §3 (`IssueIn`), without values. No other document, ticket or contract constrains it, so `info, warning, error` contradicts nothing.

### 9.3 Cancellation check

Section 5.5.

### 9.4 Unverified formats the docs themselves flag

SR 10-12 column layouts, the Corte Z format and whether recipes carry costs are **unverified** in `01`/`03`. They affect `ItemSalesIn`, `DailySalesIn`, `MenuItemIn` and `RecipeIn` (10.1), not the SQL.

## 10. Python contract and tests

### 10.1 `NormalizedBatch` [DOC `09` §3, APPROVED D8]

Wire format is JSON with `snake_case` names. Models use `extra='forbid'`, `frozen=True` and `Cents`/`Quantity`/`UnitPrice` annotated types. Enums are **imported from the generated `db/models.py`** (single source: the SQL). `Grain` is the only enum defined in `batch.py`, because it is not a database enum.

```text
Cents      = int, strict (no float, no str)
Quantity   = Decimal, max 18 digits, 6 decimal places
UnitPrice  = Decimal, max 20 digits, 6 decimal places    # pesos per unit
Grain      = ticket | item_daily | daily | purchase | catalog      # 09 section 3
AwareDatetime for every instant; date for every business date
```

```text
NormalizedBatch
  contract_version: Literal[1] = 1
  parser: str                      # pattern ^[a-z0-9_.]+@v[0-9]+$, e.g. "sr.productos_vendidos@v1"
  source_kind: SourceKind
  quality: BatchQuality = file     # not in the 09 section 3 sketch; 09 section 2.2 and the section 3 table require it for OCR
  location_hint: str | None
  period: Period                   # from_ (alias "from") <= to
  grain: Grain
  totals: Totals                   # net_sales: Cents | None, units: Quantity | None, lines: int >= 0
  menu_items: list[MenuItemIn] = []
  item_sales: list[ItemSalesIn] = []
  daily_sales: list[DailySalesIn] = []
  tickets: list[TicketIn] = []
  purchases: list[PurchaseIn] = []
  recipes: list[RecipeIn] = []
  issues: list[IssueIn] = []
```

Input types. Every field maps to a column in 5.7; the loader fills `tenant_id`, `batch_id`, `source_id`, `location_id` (resolved from `location_hint`). **Basis** says why the type can or cannot be trusted yet.

| Type | Fields | Basis |
|---|---|---|
| `MenuItemIn` | `external_id?`, `name`, `category?`, `kind = dish`, `price_gross: Cents?`, `tax_rate?` (`09` §3 sketch: `externalId?, name, category?, price?`) | **PROVISIONAL**: which report supplies menu prices, categories and modifiers is unverified (`01`, `05` risk 4) |
| `ItemSalesIn` | `item_external_id?`, `item_name`, `period_from`, `period_to`, `units: Quantity`, `gross`, `discount`, `net: Cents` | **PROVISIONAL**: "Productos vendidos" columns for SR 10-12 are unverified (`01`, `11` E1); whether a range export is allowed is unconfirmed (`12` §4c shows a single day) |
| `DailySalesIn` | `business_date`, `net_sales`, `tax`, `tickets: int`, `guests: int?`, `discounts`, `cancellations_amount: Cents?`, `cancellations_count: int?`, `payment_mix: dict[PaymentMethod, Cents]`, `tips: Cents` | **PROVISIONAL**: Corte Z / "Ventas por día" format is unverified (`01` §2); which of these fields a given file supplies is unknown |
| `RecipeIn` | `menu_item_external_id?`, `menu_item_name`, `yield_qty: Quantity`, `lines: list[RecipeLineIn]` (never applied directly; the loader turns it into a `pending_change`, `09` §3) | **PROVISIONAL**: whether the "Recetas" export carries costs and yields is unverified (`03` C.1, `11` E7) |
| `RecipeLineIn` | `ingredient_name`, `ingredient_external_id?`, `qty_base: Quantity`, `unit`, `yield_override_pct?` | **PROVISIONAL** with `RecipeIn` |
| `TicketIn` | `external_id`, `business_date`, `opened_at?`, `closed_at?`, `channel`, `area?`, `table_label?`, `guests?`, `staff?: StaffIn`, `subtotal`, `discount`, `tax`, `tip`, `total: Cents`, `status`, `fiscal_status = none`, `lines: list[TicketLineIn]`, `payments: list[PaymentIn]` | Documented source: the ERP/PMS JSON payload fields are **verified** in `01` §5, but the adapter is Phase 1b; the mapping is untested |
| `StaffIn`, `TicketLineIn`, `PaymentIn` | as in 5.7 (`staff`, `sale_line`, `payment`) | same as `TicketIn` |
| `PurchaseIn` | `supplier: SupplierIn`, `kind`, `cfdi_uuid?`, `issued_at`, `subtotal`, `total: Cents`, `lines: list[PurchaseLineIn]` | Documented source: CFDI 4.0 fields in `03` C.3, marked **likely**, to validate against the SAT XSD; Phase 1 stretch |
| `SupplierIn`, `PurchaseLineIn` | `SupplierIn`: `name`, `rfc?`, `kind`. `PurchaseLineIn`: `description`, `qty: Quantity`, `unit`, `unit_price_net: UnitPrice`, `ingredient_name?` | same as `PurchaseIn` |
| `IssueIn` | `severity`, `code: str` (pattern `^[a-z0-9_.]+$`), `message_es: str`, `row_ref: str?` | Documented (`09` §2.2, §3); `row_ref` type is [AUTHOR] |

How provisional types are marked and used:
- The class docstring starts with `PROVISIONAL:` and names the unverified source (`test_batch_provisional.py` asserts the marker on exactly these classes).
- `README.md` of `packages/contracts` lists them.
- `contract_version` stays 1. Changes to provisional types are allowed until the first real parser lands (MR-15, MR-23); the golden tests of those tickets then pin them. Changes after that are contract changes.
- No Corte Z, "Productos vendidos" or "Recetas" column names are written into the contract. Only table-derived fields are.

Required for the current parsers (week 1-2): `item_sales`, `daily_sales`, `menu_items`, `recipes`. Defined but empty by default (Phase 1b / week-3 stretch): `tickets`, `purchases`. [DOC `08` MVP scope, `09` §3 table]

Deliberately **not** validated in the model: the match between `grain` and the populated lists, and "totals equal the sum of lines" (`03` B.5; the loader's job, MR-16). Neither is documented as a model rule. Model-level validation is limited to `period` order, tz-aware datetimes, patterns, strict money and extra-field rejection.

Documenting and testing the input types: each field has a docstring naming its table column; `test_models_match_db.py` fails if a `*In` field that claims a column does not exist in the generated model of that table or has an incompatible nullability or type.

### 10.2 Generator

`python -m mermia_contracts.tools.gen_db_models --db-url <url> [--check]` (default URL `postgresql://postgres:postgres@127.0.0.1:54322/postgres`, the local CLI value [VERIFIED]).

- Reads `pg_catalog` for tables in `public` only, and the enums in `app`. Never reads `auth`, `storage` or other schemas.
- Mapping: `uuid` to `UUID`; `text`/`varchar` to `str`; `int` to `int`; `bigint` to `int` (tag `unit=centavos` yields `Cents`); `numeric(p,s)` to `Decimal` with `max_digits`/`decimal_places` from the type modifier (tag selects `Quantity`/`UnitPrice`/percent); `boolean` to `bool`; `date` to `date`; `timestamptz` to `AwareDatetime`; `jsonb` to `JsonValue` unless `overrides.py` names a model; `bytea` to `bytes`; arrays to `list[T]`; enums to a `StrEnum` with labels in `enumsortorder`; `NOT NULL` without default to a required field; nullable to `T | None`; defaults noted in the field description only. [catalog queries verified in V16; the mapping code is not written yet]
- Output classes `<TableName>Row` (PascalCase), sorted alphabetically, with columns in `attnum` order. No Insert/Update models: client roles cannot write and backend writes go through functions.
- `db/overrides.py` types only documented shapes: `import_batch.stats` (rows, totals, anomalies, per `09` §2.2), `daily_sales_agg.payment_mix` (map of `payment_method` to centavos), `tenant.settings` (food-cost target and report cadence, extra keys allowed, per `09` §2.1 and `07`). Everything else (`pending_change.payload/diff`, `audit_log.before/after`, `conversation.last_turns`, `source.config`) stays `JsonValue` until MR-11.
- Deterministic: the generator emits canonical formatting itself, with no timestamps and no dependence on an external formatter, so output is byte-identical across machines. The header holds `generator_version` and `migrations_sha256` (SHA-256 over the sorted list of `<filename>\n<contents>` of `supabase/migrations/*.sql`).
- Staleness checks:
  1. `test_generator_hash.py` (no database): recomputes `migrations_sha256` and compares it with the header. Catches "migration added, models not regenerated".
  2. `test_generator_fresh.py` and `--check` (database): regenerate from the freshly reset database into memory and require byte equality with the committed file. Catches generator or tag changes.
  3. `test_models_match_db.py`: every column of every public table exists in the generated model with the right nullability, and every enum equals its `pg_enum` labels.

### 10.3 Contract tests (`pytest`)

| Area | Cases |
|---|---|
| Types | `Cents` rejects `float`, `str` and `bool`; accepts negative values (refunds). `Quantity`/`UnitPrice` reject `float` and excess scale; `Decimal` stays exact. Naive datetimes are rejected. |
| Nullability | Required fields are required; every `?` field accepts `None` and omission; empty lists are valid. |
| Enums | Every enum value round-trips; an unknown value is rejected; the Python enum labels equal the database labels (DB test). |
| JSON | Valid and invalid example batches in `tests/examples/`; JSON round-trip equality; `payment_mix` keyed by `PaymentMethod`; `issues`; `period` alias `from`; `extra` fields rejected; a JSON Schema snapshot test pins the exported schema. |
| Contract | `contract_version` other than 1 rejected; `parser` pattern; `period.from > period.to` rejected; `quality` default `file`. |
| Provisional | Exactly the types marked in 10.1 carry the `PROVISIONAL:` marker. |

### 10.4 Database tests (`supabase/tests/`, pgTAP) [APPROVED]

All tests run in a transaction and roll back. Helpers (a `try_as(role, claims, stmt)` function in `pg_temp` and the dummy-row generator) are repeated at the top of each file because each file runs separately (V3, V10, V15). Layer separation: each assertion states whether it proves a **privilege**, a **policy** or a **privileged-role** behaviour.

| File | Layer | Proves |
|---|---|---|
| `00_catalog.test.sql` | all | Exactly the 40 expected tables in `public` (a hard-coded list in the test, equal to 7.2.2); no other table; **no function in `public`**; RLS enabled on all; the `rls_class` comment of each table equals the class in 7.2.2; per class: T/L/F tables have exactly one `SELECT` policy and no write policy, LP has the parent-`exists` policy, X tables have no policy and no client grant; `source` column grants exclude `config` and `api_key_hash`; `audit_log` privileges; no table has `FORCE`; `anon` has no privilege on any `public` table; default privileges for `anon`/`authenticated` are revoked; every function in `app` has no `PUBLIC`/`anon` `EXECUTE`; helper-schema grants; roles' `rolbypassrls`; enum labels equal 5.3; unit tags present on every money/price/quantity/percent column; the license notice is present in the `uuid_v7` migration. |
| `10_isolation.test.sql` | policy + privilege | Data-driven over every T, L, LP and F table: with `session_replication_role = replica` insert one dummy row per tenant (L tables: one row per location), then as `authenticated`: tenant A sees its rows, tenant B sees its rows, no `tenant_id` claim sees 0, malformed claim sees 0, `anon` is denied, `postgres` and `service_role` see all. X tables: `authenticated` denied at the privilege layer. |
| `20_location.test.sql` | policy | `can_see_location` and `has_all_locations`: explicit `null` sees the whole tenant; one-element array sees that location; empty array, wrong type and **absent key** see none; null location column visible to all members. Checked on `location`, `import_batch`, `sale_ticket`, `daily_sales_agg`. LP: `import_issue` follows its batch (Centro-only sees Centro issues). F: `pending_change` and `audit_log` visible only with explicit `null`. Column grants: `select *` on `source` fails; safe columns work. |
| `30_write_denial.test.sql` | privilege, policy, privileged role | For each client role (`anon`, `authenticated`) and each of `INSERT/UPDATE/DELETE/TRUNCATE`: denied at the **privilege layer** (`permission denied for table X`). A scratch table with a grant and no policy shows the **RLS layer** (`new row violates row-level security policy`). `service_role` writes succeed on class T/L tables (privileged role). `audit_log`: `service_role` blocked by privileges; `postgres` blocked by the trigger; `INSERT` allowed. Role memberships (V28). The V23 pattern (a definer with `EXECUTE` only for `service_role`) is exercised on a scratch function. |
| `50_exposure.test.sql` | all | Indirect paths (7.2.5): zero views and zero functions in `public`; no function in `public` or `app` references `set_config` with `request.jwt`; every FK from a client-readable table to a class X table is listed and has no client privilege on the target; `source` column privileges for `authenticated` exclude `config` and `api_key_hash`; `membership` has the `all_locations` check and an insert without scope yields an empty list and `all_locations = false`; an insert with `location_ids = null` and `all_locations = false` fails; every `text` column of `public` has the not-blank check; `audit_log` privileges are exactly `SELECT` (`authenticated`, `service_role`) and `INSERT` (`service_role`). |
| `40_integrity.test.sql` | integrity | Cross-tenant composite-FK inserts fail for `postgres` and `service_role`; `touch_row` bumps `version` and `updated_at`; a `tenant_id` change fails; `uuid_v7` properties (10,000 values: version 7, variant, unique, zero inversions, timestamp round-trip); membership `location_ids` validation; partial unique index on applied batches; `num_nonnulls` checks; nullability spot-checks. |

The data-driven generator in `10_isolation` needed no per-table fixtures beyond three pinned columns (`recipe.menu_item_id`, `recipe_line.ingredient_id`, `import_issue.batch_id`); replica mode works under `pg_prove` (V30). Mutation checks confirmed that the matrix detects weakened policies.

### 10.5 Commands

Prerequisites: Docker running, `brew install supabase` (CLI 2.121.0 was used for the PoC), `uv`.

```bash
# from anywhere inside the repo (the CLI searches upward for supabase/)
supabase start -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
supabase db reset          # applies every migration from an empty database
supabase test db           # pgTAP: 00..50 files

cd packages/contracts
uv run pytest                                              # contract tests (no DB needed)
MERMIA_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run pytest -m db
MERMIA_API_URL=http://127.0.0.1:54321 MERMIA_JWT_SECRET=<local secret from `supabase status`> MERMIA_API_KEY=<local publishable key> \
  uv run pytest -m rest   # exposure through PostgREST and GraphQL; local stack only
MERMIA_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres \
  uv run python -m mermia_contracts.tools.gen_db_models --check
```

The `-x` list starts only the database, Auth, PostgREST and the gateway [VERIFIED V1-V3, V13]. `supabase db lint` is not part of the acceptance set because it was not exercised in the PoC. For MR-9 (CI, not built here): run the same commands after `supabase start`, plus `uv run ruff check` and `mypy`.

## 11. Files created and modified

**Created:** `supabase/config.toml`, `supabase/.gitignore`, eight (or more) files in `supabase/migrations/`, six files in `supabase/tests/`; everything under `packages/contracts/` listed in section 4; `.gitattributes`; this spec; the implementation plan that follows it.

**Modified:**

| File | Change |
|---|---|
| `README.md` | Developer commands (10.5), layout and prerequisites. |
| `docs/kickoff/09-architecture.md` | Module table: replace the `packages/db` row with `supabase/` and move "pgTAP tests" there. §2 header: money rule split (5.4), `tenant_id` exceptions (C4), UUIDv7 note (5.2), `audit_log` columns (C9). §2.3: `cancellations_amount`/`cancellations_count`, `table_label`, `item_sales_agg` period. §2.5: split `alert` and `price_suggestion`; `location_id` additions. §3: state that the Pydantic model in `packages/contracts` is the source of truth and the TypeScript sketch is illustrative; snake_case. D8 and §6: claim names `tenant_id`, `app_role`, `location_ids` and the absent-key rule; add a pointer to the trust boundary (7.5). |
| `docs/kickoff/08-mvp-4-week-plan.md` | Line 29 ("Everything lives in `packages/contracts`") and the C1 row: DDL in `supabase/migrations`, generated models in `packages/contracts`. Ownership row "Database". |
| `docs/process/ticket-guide.md` | Line 73 stays true (contracts need both approvals); no change unless the owner wants the migrations path mentioned. |

**Outward-facing, not changed without the owner's go-ahead:** the body of GitHub issue #10 (it also says `packages/contracts`) and the bodies of MR-11, MR-13 and MR-14 where they refer to those paths. I recommend editing #10 once the PR is open.

## 12. Items for the owner

### 12.1 Review of the spec author's calls

Status key: **Documented** = a repo document states or directly implies it; **Recommended** = design choice that fits the docs and is verified or low risk; **Approval** = changes schema, security or compatibility and needs the owner's explicit yes. "Evidence" cites the docs and the PoC ids.

| # | Call | Status | Evidence | If rejected or changed |
|---|---|---|---|---|
| A1 | **Class X (backend-only)**: `app_user`, `channel_identity`, `consent_log` (approved D10) plus `membership`, `raw_file`, `report_run`, `external_ref`, `conversation`, `llm_usage`, `message_log`. `source` is class L with a column grant that hides `config` and `api_key_hash`. | Recommended, **Approval** | No RPC in `09` §4.1 and no documented dashboard feature reads these tables; they are written by the backend; they hold personal data or internal costs (`05` risk 10, 11; `13` §I4); `get_data_status` needs `source` (`09` §4.1 #11) so it stays readable minus secrets; V22 (column grants verified, also over PostgREST). | Opening a table to clients later is a new policy plus a grant; removing exposure after data exists is not. Clients must name columns when reading `source` (verified: `select *` fails). |
| A2 | `item_sales_agg` uses `period_from`/`period_to`. | Recommended, **Approval** | `09` §2.3 says "business_date (or period)"; `12` §4c shows a daily upload ("el día que cerraste"). Whether range exports are allowed is unverified (section 16). | Alternative: one `business_date` and the parser rejects ranges (`needs_review`). Changing later alters a stored column and the contract. |
| A3 | Nullable `location_id` on `import_batch`, `alert`, `price_suggestion`, `report_run`. | Documented derivation, Recommended | `slice_key` includes a location (`09` §2.6); `get_cost_alerts(location_id?)` (`09` §4.1 #10); `build_weekly_report(location_id, period)` (`08`). Nullable = tenant-level. `report_run` is class X, so its column has no policy role. | Without the column on `import_batch`, location-limited managers could not be isolated (class L). |
| A4 | `table` renamed `table_label`; `alert` and `price_suggestion` as two tables. | Rename: Recommended. Split: Recommended, **Approval** | `table` is a reserved SQL word [general SQL knowledge, not run here]. `09` §2.5 writes `alert / price_suggestion` as one row; `03` names them as separate entities. (Revision 1 claimed `09` counts 10 tables only if split; `09` makes no count. That claim is withdrawn.) | A single table needs a `kind` column and nullable `suggested_price`/`rationale_code`; the counts in this spec become 39. |
| A5 | Percentages as percent points `numeric(7,4)`; tax rate as a fraction. | Recommended, **Approval** | Names end in `_pct` and the docs show "34.1%" (`12`); no document fixes the representation. | Changing later alters stored data, generated types and RPC formatting. |
| A6 | No FK from `app_user.auth_user_id` to `auth.users`. | Recommended | Avoids coupling to the Supabase-owned auth schema; WhatsApp-only users have no auth user (`04`). Not PoC'd. | With an FK, local fixtures need auth rows and `db reset` depends on the auth schema. |
| A7 | `unique (tenant_id, sha256)` on `raw_file`; partial unique index "one applied batch per slice". | Rule: Documented (`03` B.5, `09` §2.6). DB enforcement: Recommended | Not run under a real apply sequence (section 16). Unique indexes are checked per statement, so apply functions must flip statuses in order. | A deferrable exclusion constraint is the alternative if ordering proves awkward. |
| A8 | Enums where values are documented; `text` without CHECK elsewhere. | Documented values; text: Recommended, **Approval** | 5.3 cites each source; the `text` list is in 5.3. Adding enum values later is cheap; removing them is not. | Inventing values would be new requirements. |
| A9 | `currency char(3)` default `'MXN'` with a format check. | Recommended | `09` §2 writes "plus currency char(3)"; `CLAUDE.md`: product for Mexico. | No default means every insert must state it. |
| A10 | UUIDv7 as vendored sub-ms function under the PostgreSQL License. | Requirement: Documented. Implementation: **Approval** (external code) | V8 (ordering and validity on Postgres 17), V18 (license and upstream status). Upstream's license text requires the notice (5.2). | Fallback: `gen_random_uuid()` default and application-supplied v7; loses index locality. |
| A11 | Cancellation columns nullable ("not reported" is not zero). | Recommended (D7 approved) | 5.5; Corte Z format unverified. | Non-null defaults would turn "unknown" into zero. |
| A12 | `location_ids` is **fail-closed**: an absent key means none; explicit JSON `null` means all. | Recommended, **Approval** (contract semantics) | `09` §2.1 null = all; V20 (absent key returns no rows). Consequence: every issuer must always set the claim (7.5.6). | Fail-open (absent = all) is simpler but lets a missing key widen access. |
| A13 | `pending_change` and `audit_log` readable by all-location members only (class F). | Recommended, **Approval** | AMB-1; V21. | Option T (any member) is wider; option X pushes every read to an RPC. |
| A14 | `import_issue` inherits location visibility from its batch (class LP). | Recommended, **Approval** | AMB-3; V19. | Option X is stricter; costs nothing now but hides a future dashboard read. |
| A15 | Composite FKs. | **Approved** (D18) | V12, V13 (cross-tenant blocked; PostgREST embedding works). Self-referencing FKs not yet tested (section 16). | - |
| A16 | One multi-mode `app.secure_table` function; table comment `rls_class=...` checked by the catalog test. | Recommended (implementation detail, no approval needed) | Each class behaviour verified (V10, V19-V22); the combined function is not. | Per-table statements in each migration; same behaviour, more repetition. |
| A17 | No function in `public`; catalog test enforces it. | Recommended | V24, V26 (7.5.3). | A function that sets claims in an exposed schema would break the trust model. |
| A18 | Tenant-wide catalog, costing and `staff` tables readable by location-limited members (AMB-6). | Recommended | `09` §5.1 (managers handle tenant-wide costing), `09` §2.3 (no location on these tables), `staff` is first names only. | Adding location columns would be an invented requirement. |

Owner decisions of 2026-10-18 on these calls are in 2.3: A1, A12, A13, A14, A2, A4, A5, A8 and A10 are **approved** (with the conditions listed there); the rest are kept where consistent with the canonical documents. Two calls were added to satisfy those conditions:

| # | Call | Status | Evidence | If rejected or changed |
|---|---|---|---|---|
| A19 | `membership.all_locations boolean not null default false`, `location_ids` default `'{}'`, check `all_locations = (location_ids is null)`. | Recommended; added for the A12 condition ("membership expressly authorizes full scope"). Deviation from `09` §2.1, which says only "null = all". | `09` §2.1; a tool or ORM that sends `None` for an unspecified scope would otherwise grant all locations. Verified behaviour of the claim side: V20, V21. The CHECK and default are not yet run (16.4). | Without the flag, a default NULL grants everything; the issuer cannot tell "all" from "forgot to set". |
| A20 | `app.add_text_checks(rel)` adds a not-blank check to every `text`/`varchar` column. | Recommended; added for the A8 condition ("do not skip integrity validations because a column is text"). | A8; no value list is introduced. Not yet run (16.4). | Blank strings could be stored where the doc implies a value. |

Implementation findings that need the owner's attention (found by the tests, section 17):

| # | Call | Status | Evidence | If rejected or changed |
|---|---|---|---|---|
| A21 | `recipe.recipe_version` replaces `recipe.version` (C18). | Recommended, **Approval** (column name) | `09` §2 and §2.4 use the same name for two meanings. | Keep `version` for the revision and rename the concurrency column on that table only, which breaks the shared trigger. |
| A22 | Tenant-level rows (null location) are hidden from absent, empty and malformed `location_ids` claims (V29). | Recommended, **Approval** (refines the approved fail-closed rule) | The owner's A12: absent or malformed claim means no location, an empty list means none. A first version leaked tenant-level rows to those claims. | Showing tenant-level rows to empty-list members is simpler but contradicts "empty list: no location". |
| A23 | Global revoke of `PUBLIC` execute for functions created by `postgres` (V27). | Recommended | V27; secure default for every future function. | Each future function must revoke `PUBLIC` explicitly; the catalog test would still catch a miss. |
| A24 | `pg_graphql` is not enabled locally, so GraphQL exposure is untested; hosted Supabase projects normally enable it. | **Approval** for a follow-up | V31. The architecture uses the Data API and RPCs only. | Leave as is and rely on identical privileges and policies, which is unverified for GraphQL. Recommended follow-up: confirm the extension state on the hosted project and consider `drop extension pg_graphql` there. |

### 12.2 Open items not resolved here

| # | Item | Evidence | Recommendation and consequence |
|---|---|---|---|
| O2' | **Issuer of claims and production key custody.** Documented in 7.5 and 7.6 as conditions; not built here. | V13, V14, V17; external signing-keys docs. | Decide the issuer mechanism and key storage in MR-27/29 and MR-40 before any real data. |
| O3 | **Claim `sub` and identity mapping.** `app_user.auth_user_id` may be null for WhatsApp-only users, so what `sub` carries for backend-issued tokens is undefined. | `09` §2.1; no document decides it. | Decide in MR-27/29. MR-10 policies do not read `sub`. |
| O4 | **Corte Z and report formats are unverified** (`01`). The provisional types of 10.1 depend on the pilot samples (`11` E1, E2, E5, E7). | `01` §2, `03` B. | Revise before MR-15/MR-23; additive changes only. |
| O5 | **GitHub issues** #10, #11, #13, #14 mention `packages/contracts` for migrations. | Section 11. | Edit after the PR opens. |
| O6 | **`public` reserved**: any non-domain table (for example Procrastinate's) breaks `00_catalog`. | Approved. | The Procrastinate ticket sets `search_path` on its connector to a dedicated schema ([EXT]: Procrastinate supports a custom schema through connector options). |
| O7 | **GraphQL surface (A24).** Untested because `pg_graphql` is off locally. | V31 | Check the hosted project and disable the extension if unused; run `test_graphql_*` on a stack where it is enabled. |
| AMB-1..4 | Location handling of `pending_change`, `audit_log`, `raw_file`, `membership`; see 7.2.3. | `09` §5.1, §5.3, §6. | Recommended in 12.1 (A1, A13). Needs your decision. |

## 13. Implementation order (single branch, single PR)

Each phase is a commit `MR-10: <what>`; the PR is squash-merged.

1. **Environment and branch.** Create `MR-10-contracts-schema` from `main`. Run `supabase init` at the repo root (generates `supabase/config.toml` and `supabase/.gitignore`) and re-run V1-V3 there.
2. **Scaffold `packages/contracts`.** `pyproject.toml`, package, `py.typed`, `.gitignore`, a trivial passing test, `.gitattributes`.
3. **Foundations (migrations 1-2) and their tests.** Tests first: the helper and grant assertions of `00_catalog`, the helper cases of `20_location` (including fail-closed), the `uuid_v7` cases of `40_integrity`. Then the SQL, including `secure_table`. Confirm `supabase db reset` and `supabase test db`.
4. **Tables (migrations 3-8)** in order, running `supabase db reset` and `supabase test db` after each, including `00_catalog`, `10_isolation`, `20_location` and `30_write_denial` as the tables arrive. Confirm that `pg_prove` accepts `session_replication_role`; if not, switch `10_isolation` to the fixture fallback in 10.4.
5. **Integrity tests** (`40_integrity`) for composite FKs (including self-referencing ones through PostgREST), triggers, constraints and the partial unique index.
6. **Generator and generated models**, then `test_generator_hash`, `test_generator_fresh` and `test_models_match_db`.
7. **`NormalizedBatch` and the `*In` types**, then the contract tests, example batches and the provisional markers.
8. **Docs.** `README.md` and the edits to `09` and `08` (section 11).
9. **Full verification from a clean database.** `supabase stop --no-backup`, `supabase start`, `supabase db reset`, `supabase test db`, `uv run pytest` and `-m db`, `gen_db_models --check`. Record the output in the PR description. Only then open the PR (`MR-10 Contract: database schema and NormalizedBatch`, body `Closes #10`).

## 14. Acceptance criteria

All must hold on a clean checkout with Docker running. Each item is reported with the command and its real result; a check that could not be run is listed as not run (section 16.4).

1. `supabase db reset` applies every migration to an empty database with no error. [Ticket #10: "Migrations run on a fresh local Supabase"]
2. `supabase test db` passes all six test files (10.4), and `uv run pytest -m rest` (the exposure test through PostgREST/GraphQL) passes or is explicitly reported as not run with the reason.
3. There are exactly 40 tables in `public` and no function in `public`; each has RLS enabled and the `rls_class` of 7.2.2; T/L/F tables have one `SELECT` policy and no write policy; LP has the parent policy; class X tables are unreadable by `authenticated` and `anon`.
4. For every client-readable table, tenant A, tenant B, no-claim, malformed-claim and `anon` behave as in `10_isolation`; location filtering, the fail-closed absent claim, the LP inheritance and the F rule behave as in `20_location`.
5. Write denial is shown per layer (privilege, policy, trigger, privileged role) and `audit_log` cannot be changed by any role (`30_write_denial`).
6. Cross-tenant references are rejected by composite FKs for `postgres` and `service_role` (`40_integrity`).
7. `app.uuid_v7()` passes the version, variant, uniqueness, ordering and round-trip checks over at least 10,000 values, and the license notice is present.
8. `uv run pytest` passes without a database; `-m db` passes with one; `gen_db_models --check` reports no differences.
9. `NormalizedBatch` and the input types pass the contract tests of 10.3; `tests/examples/*.json` behave as labelled; provisional types carry their marker.
10. Sections 5.4 (units, conversion, rounding), 7.5 and 7.6 (trust boundary and production conditions) appear in the repo docs (`README.md` and `09`).
11. No file is touched outside `supabase/`, `packages/contracts/`, `.gitattributes`, `README.md` and `docs/`. There is no root `pyproject.toml` and no CI file.
12. Every item in 12.1 and 12.2 is either approved by the owner or has an explicit note in the PR description.

## 15. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| R1: the data-driven fixture generator cannot satisfy some real CHECK or trigger. | `10_isolation` needs per-table fixtures. | Fallback in 10.4; the loop covers the rest. |
| R2: `pg_prove` does not allow `session_replication_role` as `psql` did (V15). | Same. | Detect in phase 4; fixtures in dependency order instead of replica mode. |
| R3: composite FKs make DDL verbose and a self-referencing FK may behave differently in PostgREST. | Review time; possible embedding limits. | V13 covers the plain case; phase 5 tests the self-referencing case. |
| R4: a client-readable table exposes a column it should not. | Data exposure. | Column grant on `source`; the catalog test lists every client-readable table and its columns for review. |
| R5: Supabase changes default grants or exposure. | Silent exposure of a future table. | Explicit `REVOKE`/`GRANT` per table; catalog test asserts the final privileges, not the defaults (V6). |
| R6: provisional `*In` types (O4). | Rework in MR-15/23. | Additive changes only; marker and README; `contract_version` stays 1. |
| R7: the PostgreSQL License notice is omitted when vendoring `uuid_v7`. | License breach. | Required header in migration 1; a test greps for it. |
| R8: a future issuer or exposed function breaks the trust boundary (V26). | Cross-tenant exposure. | 7.5.3 rule, `no function in public` test, 7.6 conditions before go-live. |
| R9: fail-closed location claim breaks an issuer that forgets the key. | Users see no data. | Intended; 7.5.6 makes the claim mandatory; tests in MR-14/27. |
| R10: class X or F hides data a dashboard later needs. | Rework of one policy or a new RPC. | Recorded in AMB-1 to AMB-4; cheap to open, costly to close. |

## 16. Evidence ledger

The five buckets the owner asked to keep apart.

### 16.1 Validated by tests (local PoC, 2026-10-18)

V1-V26 in section 3: Postgres 17 and the CLI project layout; pgTAP workflow; `auth.jwt()` definition; role attributes; default privileges and their revocation; the exposed schema; UUIDv7 validity, uniqueness and ordering; invoker privileges on column defaults; tenant, location and fail-closed isolation; the full-tenant policy; parent-inherited location; column grants (SQL and PostgREST); the three failure layers and the audit immutability pattern; composite FKs (block and PostgREST embedding); signature rejection; that the Data API cannot set claims and ignores headers; the definer-function privilege pattern; replica-mode fixtures in `psql`; catalog introspection.

### 16.2 Defined by the architecture documents

Table list and columns (`09` §2.1-2.5); batch lifecycle (§2.6); `NormalizedBatch` sketch (§3); RPC list and "location null = every location the user can see" (§4.1); reads as the user, writes through `pending_change` (D5, D7, D8); the extra location filter (§6); approval matrix and dashboard views (§5.1, §5.3); manager scoped to one location (`12` §4, `05` risk 3); UUIDv7, `audit_log` immutability, roles, LLM usage fields, Meta pricing categories (section 2.2).

### 16.3 Owner approvals and what is still a recommendation

Approved on 2026-10-18 (2.3): A1, A2, A4 (split kept), A5, A8, A10, A12, A13, A14. Kept as recommended because consistent with the canonical documents: A3, A6, A7, A9, A11, A15, A16, A17, A18. Added for the approval conditions and awaiting the owner's review of the final PR: A19, A20. AMB-1 to AMB-4 follow the approved classes; AMB-7, `sub` and key custody stay as documented dependencies.

### 16.4 Technical verifications

Ran and passed on 2026-10-18 (section 17): whole schema under `supabase db reset` from an empty database; all six pgTAP files (219 tests) including the 40-table isolation matrix under `pg_prove` with replica mode; `touch_row`, the membership trigger, `uuid_v7` (10,000 values), the partial unique index and the composite foreign keys; the generator, its determinism, the hash and freshness guards and `--check`; the `NormalizedBatch` contract tests (86 without a database); 22 REST exposure tests through PostgREST including embedding, hidden columns, OpenAPI and forged tokens; `ruff check`, `ruff format --check` and `mypy` on the package.

Not run, with the reason:
- **GraphQL exposure**: `pg_graphql` is not enabled on the local stack (V31).
- **`supabase db lint`**: not part of the acceptance set (not exercised).
- **PostgREST embedding through a self-referencing composite foreign key** (`sale_line.parent_line_id`, `menu_category.parent_id`, `recipe_line.sub_recipe_id`): the plain composite case is verified (V13); the self-referencing case was not exercised through the API.
- **The partial unique index under a real apply sequence**: only the constraint itself is tested; the apply functions do not exist yet (MR-16).
- **Production behaviour**: key custody, the Supabase Auth hook, token lifetime, the backend issuer (7.6; out of MR-10), and the hosted project's extensions and default grants.
- **Repo CI**: no CI exists yet (MR-9); `.claude/skills/check/check.sh` ran and reported pgTAP PASS and Python checks skipped (no root `pyproject.toml`), so the Python checks were run directly with `uv`, `uvx ruff` and `uvx mypy`.

### 16.5 Validations that need real pilot samples

From `11` §2.2 and `01`: the "Productos vendidos" export (E1) for `ItemSalesIn`, `MenuItemIn` and the period question; the Corte Z or "Ventas por día" export (E2) for `DailySalesIn`, cancellation granularity and `payment_mix`; "Formas de pago" (E5); the recipes exports (E7) for `RecipeIn`; SR 10/11/12 layout differences, modifiers and branch fields (`05` risk 4); whether CFDI XML arrives over WhatsApp (`03` C.3, `04`). None of the types or columns that depend on these has been validated against a real file.

## 17. Verification record (2026-10-18, local stack only)

Run from a clean state: `supabase stop --no-backup`, `supabase start -x ...`, `supabase db reset`. Supabase CLI 2.121.0, Postgres 17.11, Python 3.12.12, `uv` 0.12.5, `ruff` 0.17.1. No remote or shared database was used.

| Command | Result |
|---|---|
| `supabase db reset` | 8 migrations applied from an empty database, no error |
| `supabase test db` | 6 files, 219 tests, PASS |
| `cd packages/contracts && uv run pytest` | 86 passed (no database) |
| `MERMIA_DB_URL=... uv run pytest -m db -k 'not rest_exposure'` | 5 passed |
| `MERMIA_DB_URL=... MERMIA_API_URL=... MERMIA_JWT_SECRET=... MERMIA_API_KEY=... uv run pytest -m rest -rs` | 22 passed, 1 skipped (GraphQL: `pg_graphql` not enabled) |
| `uv run python -m mermia_contracts.tools.gen_db_models --check` | `db/models.py` is up to date |
| `uvx ruff check .` and `uvx ruff format --check .` (package) | passed |
| `uvx --with pydantic --with psycopg mypy src` | no issues in 8 source files |
| `bash .claude/skills/check/check.sh` | pgTAP PASS; Python checks skipped (no root `pyproject.toml`) |

Findings the tests produced while building (all fixed or recorded): V27, V28, V29, V30, V31, V32, V33, V34, C18, the invalid `SET ROLE` test replaced by membership checks, and a first version of `can_see_location` that leaked tenant-level rows.

