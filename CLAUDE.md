# MermIA

Restaurant intelligence for Mexico. Phase 1: WhatsApp agent fed by Soft Restaurant (SR) report exports. Phase 2: mobile-first dashboard. Phase 3: own cloud POS that keeps working offline (a decision gate at ~month 9, not a commitment). Each phase reuses the one before. Sell cost-side value (margin alerts, price suggestions, CFDI/receipt price capture), not sales Q&A that SR already gives free. MVP ingestion = WhatsApp upload + email inbox; target = SR ERP/PMS JSON push.

## Key docs
- Kickoff: `docs/kickoff/` — start with `00-executive-summary.md`; architecture `09`, 4-week plan (Dev A / Dev B) `08`, LLM and token strategy `13`, sample agent messages `12`, features vs SR and Toast IQ `14`. Brief: `docs/kickoff-prompt.md`.
- Per-ticket specs and plans: `docs/superpowers/specs/`, `docs/superpowers/plans/`. Ticket format: `docs/process/ticket-guide.md`.

## Stack
Python 3.12, `uv` workspace (`apps/*`, `packages/*`), FastAPI (one always-on service on Render), Pydantic v2 contracts, Supabase (Postgres, RLS, pgTAP), Agno for LLM calls (OpenAI, Google, Anthropic) with Langfuse traces. Planned: Procrastinate jobs; Phase 2 React + Vite with TypeScript types generated from the Pydantic JSON Schema. Details: `docs/kickoff/09-architecture.md` §7.

## Commands
- Install: `uv sync --all-packages --all-groups`
- All checks: `.claude/skills/check/check.sh` (`/check`): ruff, ruff format, mypy strict, pytest, pgTAP
- API: `uv run uvicorn mermia_api.main:app --reload`
- Mock RPC: `uv run uvicorn mermia_mock_rpc.app:app`
- Eval (paid calls): `uv run --env-file .env mermia-eval [--models provider:id,...] [--runs N]`
- DB: `supabase start -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor`, `supabase db reset`, `supabase test db`
- DB tests: `MERMIA_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run pytest -m db`
- Regenerate models after a migration: `uv run python -m mermia_contracts.tools.gen_db_models` (`--check` fails if stale)

## Layout
- `packages/contracts`: source of truth. C3 read RPCs (`rpc.py`), C4 the 12 agent tools (`agent_tools.py`), C5 pending changes (`pending.py`), C6 AgentRequest/AgentResponse (`agent.py`), NormalizedBatch (`batch.py`). `db/models.py` is generated: never edit it.
- `apps/api`: the one FastAPI service (ingestion today; the agent, WhatsApp channel and confirmation service go here).
- `apps/mock-rpc`: one fixed answer per RPC from `packages/contracts/tests/examples/rpc/`; it ignores the args.
- `apps/eval`: Agno eval harness (tool / args / numbers scores, Langfuse traces).
- `supabase/`: migrations (append-only, never edit once merged) and pgTAP tests. A new table calls `app.finish_table(...)` and tags unit columns with `app.tag(...)` in the same migration.
- `fixtures/`, `packages/fixtures`: the "Taquería El Güero" seed and synthetic SR exports.

## Agent rules (`09` §4-5)
- **Lean agent:** router -> handler (button taps) | template (top ~8 questions, 0 tokens) | LLM broker with the 12 tools. Backend RPCs do the heavy lifting; the LLM is a broker.
- Every number in a reply must come from a tool result (number validator); the LLM never computes money.
- **DB writes need human approval:** only via `propose_change` -> `pending_change` -> confirmation by an owner, manager or admin -> `apply_pending_change` by the confirmation service; audit-logged. The LLM never calls `apply_*`.
- Static prompt prefix byte-identical across tenants; tenant, date, role and locations go in a tail message.
- No phone numbers, RFCs or full staff names to the LLM. No service role in the tool path.

## Conventions
- **Language:** code, technical docs and dev communication in English. Everything customers see (agent replies, WhatsApp messages, reports, UI text, marketing) in Mexican Spanish.
- **Money:** bigint centavos; unit prices numeric pesos; `*_pct` in percent points (34.1 = 34.1 %); no floats; round once at the end.
- **Target customers:** independent owners and small chains (2–10 locations). Phase 1 MVP goal: live pilot within 4 weeks.
- **Team:** 2 devs in parallel; agree on contracts first (both devs approve changes to `packages/contracts`) and build against mocks.
- **Proven models first:** replicate and adapt what already works elsewhere (e.g. Toast IQ); don't invent from scratch.
- Branch `MR-<n>-slug`; commits `MR-<n>: <what changed>`. Tests first for non-trivial logic.
- Never print `.env` values; check variable names only.

## Claude Code workflow
Project skills in `.claude/skills/`: `/start-ticket MR-<n>` to begin a ticket, `/check` for the checks, `/review` before opening a PR (built-in `/code-review`, then the `skeptic-reviewer` agent in `.claude/agents/`). Hooks in `.claude/settings.json` run `uv sync` at cloud session start, run `ruff format` on edited Python files, and block edits to `.env` and key files.
