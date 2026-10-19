# 02 - Conventions and decisions

Tags: **[CODE]**, **[DOC]**, **[APPROVED]** decided by the owner in chat and recorded in the MR-10 spec (2026-10-18), **[HYP]**, **[UNK]**. See `00-overview-and-prompting.md`.

There is **no `AGENTS.md`** in the repo (checked). The instruction files are `CLAUDE.md` (project) and `~/.claude/CLAUDE.md` (user-global, only about the graphify tool; irrelevant to product work).

Kickoff docs (2026-10-15) are recommendations by the kickoff agent unless founders confirmed them; they call their own design choices "opinion". Whether the founders accepted the kickoff recommendations is **[UNK]** except where `CLAUDE.md` restates them.

---

# Technical conventions

## Instructions from CLAUDE.md [DOC `CLAUDE.md`]

- **Language:** code, technical docs, dev communication in English. Everything customers see (agent replies, WhatsApp messages, reports, UI text, marketing) in **Mexican Spanish**.
- **Proven models first:** replicate features/business models that already work (e.g. Toast IQ); do not invent from scratch.
- **DB writes need human approval:** any create/edit/delete the agent triggers needs explicit confirmation from an owner, manager or admin and is audit-logged.
- **Lean agent:** backend RPCs do the heavy lifting; the LLM is a broker to keep token cost low.
- **Contracts first:** two devs agree on schema/RPC/tool interfaces first and build against mocks. Changes to `packages/contracts` need both devs' approval. [DOC `docs/process/ticket-guide.md` §4]
- Workflow: `/start-ticket MR-<n>`, `/check`, `/review` (built-in `/code-review`, then `skeptic-reviewer`). Hooks: `uv sync` at cloud session start, `ruff format` on edited Python, block edits to `.env`/key files.

Note: this pack is in English per the repo convention; the same convention means any text a customer reads must be Spanish (es-MX).

## Process conventions [DOC `docs/process/ticket-guide.md`]

| Thing | Format |
|---|---|
| Issue title | `MR-<n> <Title>` (n = GitHub issue number; rename after creation) |
| Branch | `MR-<n>-<short-slug>` |
| Commit | `MR-<n>: <what changed>` |
| PR | title = issue title; body `Closes #<n>`; squash merge; plan target < ~400 lines (the MR-10 owner waived this for MR-10 only) |
| Labels | one each of sprint (`sprint-1`), owner (`dev-a`, `dev-b`, `both`, `founders`), week (`week-1..4`) |
| Ticket body | sections 🎯 🧩 ✅ (max 7 steps) 🏁 (checkable) 🔗 ⏱ 🌿; plain short sentences; time as a number |
| Rules | one ticket = one owner = 1-2 days; "Done when" checkable by someone else; dependencies by number |

Trunk-based, short branches, other dev reviews same day. [DOC `docs/kickoff/08-mvp-4-week-plan.md`]

## Code patterns observed

- **Migrations** [CODE `supabase/migrations/`, README]: created with `supabase migration new <name>`; append-only (never edit a merged one); every new table must call `app.finish_table(...)` in the same migration (RLS, privileges, text checks, `touch_row` trigger, class comment) and tag unit columns with `app.tag(...)`; the catalog test fails otherwise. Tables use `id uuid default app.uuid_v7()`, `tenant_id`, `created_at`, `updated_at`, `version`; FKs `on delete restrict`; helpers/enums in schema `app`; `public` = domain tables only, no functions, no views (views later must be `security_invoker = true`).
- **Contracts** [CODE `packages/contracts`]: wire format JSON snake_case; models `extra="forbid"`, `frozen`; money is strict `int` centavos (`Cents`); quantities/unit prices `Decimal`; datetimes `AwareDatetime`; `db/models.py` is generated, marked `linguist-generated` in `.gitattributes`, **never hand-edited**; typed jsonb shapes in `db/overrides.py`; new `NormalizedBatch` input fields must also be added to the MAP / LOADER_ONLY tables in `tests/test_batch_matches_db.py`.
- **Naming:** snake_case tables (singular), Pydantic classes PascalCase, input types suffixed `In` (`TicketIn`), enums generated from DB enums.
- **Customer text in code:** `import_issue.message_es` is Spanish; templates are `es_MX`.

## Commands [DOC `README.md`, spec §10.5; not executed by the author of this pack]

```bash
# DB (needs Docker + Supabase CLI)
supabase start -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
supabase db reset
supabase test db          # pgTAP, 6 files
supabase stop --no-backup

# Contracts (cd packages/contracts)
uv run pytest                                   # no DB; default addopts excludes db/rest markers
export MERMIA_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres   # local demo values
uv run pytest -m db
uv run pytest -m rest                           # also MERMIA_API_URL, MERMIA_JWT_SECRET, MERMIA_API_KEY from `supabase status -o env`
uv run python -m mermia_contracts.tools.gen_db_models --check   # or without --check to regenerate

# Aggregate checks (repo root) - ruff, mypy, pytest, pgTAP; --fix applies ruff
.claude/skills/check/check.sh [--fix]
```

On `origin/main` (post MR-9), the root commands are `uv sync --all-packages --all-groups`, `uv run ruff check . && uv run ruff format --check .`, `uv run mypy`, `uv run pytest`, `uv run uvicorn mermia_api.main:app --reload`. [CODE via `git show origin/main:README.md`]

## Lint / type / format configuration

- Root (main only): ruff line-length 100, target py312, rules `E F W I B UP SIM RUF`; mypy `strict = true`. [CODE `git show origin/main:pyproject.toml`]
- `packages/contracts/pyproject.toml` on this branch has **no** ruff/mypy config; the spec says ruff and mypy were run via `uvx` on the package. [CODE; spec §17]
- CI (main only): job `python` (ruff, format check, mypy, pytest with `uv sync --locked`) and job `db` (pgTAP via `supabase db start` + `supabase test db`, skipped when no `supabase/tests`). Contract `db`/`rest` tests need env vars that CI does not set, so they **skip** in CI. [CODE `ci.yml`; spec §8.2]

## Secrets and sensitive values

- `.env`, `*.pem`, `*.key`, `service-account*.json` are write-blocked by hook; `.env.example` allowed. [CODE `.claude/hooks/protect-secrets.sh`]
- The local Supabase JWT secret/keys are published demo values (`supabase status`); never use them for anything real. Production key custody is undefined (see constraints below).

---

# Decisions and constraints

## Restated as project direction in CLAUDE.md (treat as confirmed) [DOC `CLAUDE.md`]

- Sell cost-side value, not sales Q&A. MVP ingestion = WhatsApp upload + email inbox; target = SR ERP/PMS JSON push. Phase 3 POS = decision gate at ~month 9, not a commitment.
- Stack: Python 3.12 + FastAPI (one always-on service on Render), Pydantic contracts, Supabase (Postgres, RLS), Procrastinate, `uv`; Phase 2 React + Vite with generated TS types.
- DB writes need human approval and audit log; lean agent; proven models first; English for dev, Mexican Spanish for customers; 2 devs in parallel with contracts first.

## Architecture decisions (kickoff, `docs/kickoff/09-architecture.md`) [DOC]

| # | Decision |
|---|---|
| D1 | One normalized POS-agnostic Postgres model; fact rows carry tenant/location/source/external_id/batch_id |
| D2 | Adapter = transport x parser; every parser emits one `NormalizedBatch` |
| D3 | Facts insert-only and batch-scoped; rollback = status flip, never delete |
| D4 | Two grains (ticket, aggregate) behind unified daily views |
| D5 | Metrics = Postgres SQL functions (RPC), `SECURITY INVOKER`, called through PostgREST under RLS |
| D6 | Deterministic router first, LLM second; 12 tools; number validator after the LLM |
| D7 | Writes only via `pending_change` + `apply_pending_change()` after role-checked human approval; append-only `audit_log` |
| D8 | Tool calls run as the user (short-lived identity with claims) so RLS applies to the agent |
| D9 | Python backend + TypeScript frontend; Pydantic is the contract source of truth |

Rejected alternatives recorded: Supabase Edge Functions for everything; TypeScript backend; separate metrics microservice; Next.js on Vercel (`09` §7). Rejected strategic ideas: "most restaurants use SR" premise, daily manual upload as the backbone, own POS as a committed plan, local DB connector as first choice (legal/EULA risk), Twilio (markup) (`06`, `09` §10, `04`).

## MR-10 decisions [APPROVED, `docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md` §2.1, §2.3]

| Id | Decision |
|---|---|
| P1 | One PR, no 400-line limit for MR-10 |
| D2 | Migrations in root `supabase/` (the CLI finds it from anywhere); `docs/kickoff/09` and `08` were updated to match. GitHub issue bodies #10, #11, #13, #14 still say `packages/contracts` [UNK whether edited] |
| D3 | Claims `tenant_id`, `app_role`, `location_ids`; trust comes from key custody of whoever signs the JWT |
| D6 | Ledger = bigint centavos; unit prices/costs = `numeric(20,6)` pesos per base unit |
| D7 | Cancellations split: amount + count |
| D8 | JSON snake_case |
| D10 | `app_user`, `channel_identity`, `consent_log` have no `tenant_id`; backend-only |
| D12 | `issue_severity` = `info, warning, error` |
| D18 | Composite FKs `(tenant_id, id)` |
| D5 | UUIDv7 required; vendored sub-ms SQL implementation (PostgreSQL License) |
| - | `public` is reserved for domain tables; Procrastinate gets its own schema; waiter/hour reports out of MR-10; `audit_log` has no `updated_at`/`version` and is immutable |
| A1 | Keep 10 backend-only tables; `source.config`/`api_key_hash` hidden by column grants |
| A12 | Fail-closed `location_ids`; `null` = all only from a trusted issuer **and** `membership.all_locations` |
| A13 | `pending_change` and `audit_log` visible only to all-location members (class F); no extra RPC for single-location managers (later) |
| A14 | `import_issue` inherits visibility from its batch |
| A2, A4, A5, A8, A10 | Accepted with conditions (period columns, alert/price_suggestion split, percent points, no invented enums / no skipped integrity checks, vendored UUIDv7) |
| A18 | Four catalog/staff tables with nullable `location_id` are class L (approved after review) |

Items still marked **Recommended, awaiting owner review of the final PR** in spec §16.3: A19 (`all_locations` flag), A20 (not-blank text checks), A21 (`recipe_version`), A22 (tenant-level rows hidden from malformed claims), A23 (global revoke of PUBLIC execute), A24 (GraphQL follow-up). Whether the owner has since approved them is **[UNK]**.

## Constraints

| Constraint | Source |
|---|---|
| No agent code merges before the LLM eval gate (tool selection >= 95%, args >= 95%, numeric fidelity 100%, tone >= 4/5, p95 <= 8 s) | `07-roadmap.md` M2, `13` H3 |
| MR-10: no merge, no ticket close, no remote/shared database without the owner's go-ahead; report unrun checks as not run | spec §2.3 |
| Do not touch other tickets' code (root `pyproject.toml`, CI) in MR-10 | plan "Global Constraints" |
| Views over these tables must be `security_invoker = true`; RPCs needing class X tables must be `SECURITY DEFINER` with own tenant/role checks; `SECURITY DEFINER` functions must never touch `session_replication_role`/trigger state | spec §8.1, §8.2 |
| Production: signing key only in host secret store; not in repo or LLM path; never use local demo secret; rotation procedure | spec §7.6 |
| Meta/WhatsApp: no payment method => service messages stop after 1,000/month; billing currency cannot be changed later; templates need approval; 24-hour free-form window; AI-provider policy | `04`, `11` F4 |
| Privacy (LFPDPPP 2025): aviso de privacidad, encargado clause, minimise personal data (waiter names first-name only) | `05` #10, `11` F9 |
| SR EULA bans reverse engineering; local connector only after legal review and written customer consent | `01` §7, `05` #17 |
| Phase 3 gate: >=150 paying locations, churn < 3%, >=30% owners asking for POS, funding for 2+ more engineers | `06` §4, `07` |

## Technical decisions found in code but not in a decision record [CODE]

- `app.finish_table` is the name in SQL and README. The MR-10 spec text still calls it `app.secure_table` (naming drift; see `04`).
- `packages/contracts` carries its own `.python-version`, `pyproject.toml`, `uv.lock` (spec: "replaced by MR-9's root lock when the workspace lands" - not yet done on this branch).
