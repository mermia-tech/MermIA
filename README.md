# MermIA

Restaurant intelligence for Mexico. See `CLAUDE.md` for the product, the stack and the
conventions, and `docs/kickoff/` for the research and plan.

## Layout

```
apps/api/                 The one FastAPI service (uv workspace member)
apps/mock-rpc/            Mock server for the 11 read RPCs, answered from the fixtures
supabase/                 Supabase CLI project: migrations (append-only), pgTAP tests
packages/contracts/       Python package: generated DB row models and the NormalizedBatch contract
docs/kickoff/             Research, architecture (09) and the 4-week plan (08)
docs/superpowers/         Design specs and implementation plans
.github/workflows/ci.yml  CI: ruff, mypy, pytest, pgTAP
```

## Prerequisites

Docker running, the Supabase CLI (`brew install supabase`; 2.121.0 was used) and `uv`.
The Supabase CLI finds `supabase/` from any folder inside the repo, so run its commands
from wherever you are.

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed by uv from `.python-version`.

```bash
uv sync --all-packages --all-groups   # install every workspace member and dev tools
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run uvicorn mermia_api.main:app --reload   # local API at http://127.0.0.1:8000/health
```

Or run all checks at once: `.claude/skills/check/check.sh` (`/check` in Claude Code).

Layout (a `uv` workspace, see `docs/kickoff/09-architecture.md` §1):
- `apps/api`: the one FastAPI service.
- `packages/*`: shared code, starting with `packages/contracts` (MR-10) and `packages/db` (MR-14).

CI (`.github/workflows/ci.yml`) runs ruff, mypy and pytest on every PR, plus pgTAP once a `supabase/` project exists.

## Database

```bash
supabase start -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
supabase db reset          # applies every migration from an empty database
supabase test db           # pgTAP: structure, privileges, tenant and location isolation
supabase stop --no-backup
```

Migrations are created with `supabase migration new <name>` and never edited once merged.
A new table must call `app.finish_table(...)` in the same migration (RLS, privileges, text
checks) and tag its unit columns with `app.tag(...)`; the catalog test fails otherwise.

## Contracts package

```bash
cd packages/contracts
uv run pytest                                   # contract tests, no database needed
export MERMIA_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
uv run pytest -m db                             # generated models against the live schema
uv run python -m mermia_contracts.tools.gen_db_models           # regenerate db/models.py
uv run python -m mermia_contracts.tools.gen_db_models --check   # fail if it is stale
```

`mermia_contracts/db/models.py` is generated from the migrated database; never edit it. After
any migration, run `supabase db reset` and regenerate. The exposure test through the Data API
(`uv run pytest -m rest`) also needs `MERMIA_API_URL`, `MERMIA_JWT_SECRET` and `MERMIA_API_KEY`
from `supabase status -o env`; they are local demo values.

## Units, conversion and rounding

| What | Type | Unit |
|---|---|---|
| Ledger amounts (sales, taxes, tips, totals, prices, margins, dish cost) | `bigint` | centavos |
| Unit prices and unit costs (`ingredient_price`, `purchase_line`) | `numeric(20,6)` | pesos per base unit (per purchase unit on `purchase_line`) |
| Quantities | `numeric(18,6)` | the row's unit |
| Percentages (`*_pct`) | `numeric(7,4)` | **percent points**: 34.1 means 34.1 %, never 0.341 |
| Tax rate | `numeric(5,4)` | fraction: 0.1600 is 16 % |

Convert pesos to centavos once, at the end of a calculation: `round(pesos * 100)` (half away
from zero). Never round intermediate results and never use floating point for money.

## Security model in one paragraph

Every table has row-level security; clients read through `authenticated` with the claims
`tenant_id`, `app_role` and `location_ids` (never the JWT `role` claim). An absent, empty or
malformed `location_ids` means no location; only an explicit `null` from a trusted issuer, for a
membership with `all_locations = true`, means all. Ten tables are backend-only. RLS reads claims
but does not make them trustworthy: see sections 7.5 and 7.6 of
`docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md` for who may issue them and
what production needs before real data is loaded.
