# 00 - Overview and prompting context

AI context pack for MermIA. Snapshot **2026-10-18**, branch `MR-10-contracts-schema` @ `094fecd`, compared with `origin/main` @ `ca5bb10`. Written for ChatGPT as a planning companion to Claude Code. Nothing in the application, config or existing docs was changed; only this folder was added. Start here, then `01`.

Files are in English (repo convention); the user speaks Spanish.

## Pack index

| File | Contains |
|---|---|
| `00-overview-and-prompting.md` | This file: product overview, what exists, how an assistant should work |
| `01-architecture-and-domain.md` | Stack, repo layout, data flows, 40 entities, implemented vs pending rules |
| `02-conventions-and-decisions.md` | Process/code conventions, approved decisions, hard constraints |
| `03-status-and-testing.md` | Git/PR state, backlog, blockers, test suites, acceptance criteria |
| `04-glossary-and-open-questions.md` | Glossary, contradictions, open questions |

## Tags

| Tag | Meaning |
|---|---|
| **[CODE]** | Verified by reading code, SQL or tests in the repo (path cited). Not necessarily executed by the author of this pack. |
| **[DOC]** | Decision or plan written in a repo document (path cited). Says nothing about whether it is built. |
| **[APPROVED]** | Owner decision recorded in the MR-10 spec. |
| **[HYP]** | Hypothesis or assumption that needs confirmation (the kickoff docs label many as *unverified*). |
| **[UNK]** | Unknown, stale, or not verifiable from the repo. |
| **[REPORTED]** | Result claimed by a repo document but not re-run here. |

## Sources used

- `CLAUDE.md`, `README.md`, `packages/contracts/README.md`, `docs/process/ticket-guide.md`, `.github/ISSUE_TEMPLATE/ticket.md`
- `docs/kickoff/` (read in full: `00`, `11`, `08`; read in part: `09` §1, §2 headers, §4-§10, `05`, `06`, `07`, `13` H4; skimmed headings: `14`; **not read**: `01`, `02`, `03`, `04`, `10`, `12`, `research/`, most of `13`/`14` - their claims are cited only as summarised by `00`, `05`, `06`, `07`, `09`, `11`)
- `docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md` (read ~85%; sections 6.2, 7.2-7.5, 10.1-10.4 only skimmed) and the head of the implementation plan
- `supabase/migrations/*` (greps for tables, `finish_table`, policies; foundations function read), `supabase/tests/*` (headers/greps), `packages/contracts/src` (`batch.py` head, `overrides.py`) and `tests/` (file inventory)
- `.claude/` skills, hooks, agent, settings
- `git log`, `git branch -a`, `git show origin/main:<path>`, `git merge-tree` (read-only), `gh issue list`, `gh pr list`

Not used: GitHub issue bodies and comments (only titles, states, labels), PR descriptions, any CI run results, any database.

## What is missing from this pack

- Issue bodies (each has a "Done when" list): fetch with `gh issue view <n>`.
- Real Soft Restaurant sample exports, the pilot's identity and SR version, founders' answers to `11` F1-F13.
- Full content of kickoff research files `01-04`, `10`, `12`, `research/pos-legal-stack-notes.md`.
- Any test execution result: no test, migration or generator was run for this pack. Spec §17 results are author-reported.
- Production/hosted environment facts (Supabase project, Render, Meta, Anthropic accounts): nothing in the repo shows they exist.
- Coverage figures, CI run history, open PR review comments on #49.

## Needs human validation

1. Whether the kickoff recommendations (pricing, weekly default, LLM choices, Phase 3 gate) were accepted by the founders, beyond what `CLAUDE.md` restates.
2. Whether the 4-week calendar and week labels on issues still apply.
3. Owner approval of spec items A19-A24 and the stale-spec fixes (`04` contradictions 2-3).
4. Merge plan for MR-10 vs MR-9 (conflicts in `.gitignore`, `README.md`; workspace integration).
5. Status of issue #9 (open although PR #48 merged) and the scope overlap between #10 and #14.
6. Accuracy of counts in `03` vs a fresh run (`supabase test db` totals, pytest totals).

## Keep updated as the project evolves

| Document | Update when |
|---|---|
| `03-status-and-testing.md` | every merge, ticket change, branch change, new test suites or CI changes (most volatile) |
| `01-architecture-and-domain.md` | new migrations, RPCs, policies, contract changes, modules, or MR-9/MR-10 merge |
| `02-conventions-and-decisions.md` | any owner decision or approval; process/tooling changes |
| `04-glossary-and-open-questions.md` | questions answered, new contradictions |
| `00` | rarely: only on direction or assistant-workflow changes |

Suggested practice: regenerate the "Git/PR state" block in `03` at the start of each ChatGPT planning session, and append the date and commit here.

---

# Project overview

## What the product is

MermIA is restaurant intelligence for Mexico. [DOC `CLAUDE.md`, `docs/kickoff-prompt.md`]

| Phase | Content | Status |
|---|---|---|
| 1 | WhatsApp agent fed by Soft Restaurant (SR) report exports; owner asks questions, gets weekly reports, margin alerts and price suggestions | Planned; only the data foundation exists (see below) |
| 2 | Mobile-first dashboard (React + Vite) | Not started; planned months 3-6 [DOC `docs/kickoff/07-roadmap.md`] |
| 3 | Own cloud POS that works offline | **A decision gate at ~month 9, not a commitment** [DOC `docs/kickoff/00-executive-summary.md`, `07-roadmap.md`] |

Each phase must reuse the previous one. [DOC `CLAUDE.md`]

## Users and customers

- **Target customers:** independent owners and small chains (2-10 locations). [DOC `CLAUDE.md`]
- **Roles in the data model:** `owner`, `manager`, `admin`, `support` (enum `app.member_role`). [CODE `supabase/migrations/20261018184746_enums.sql`] Phase 3 would add `cashier`, `waiter`. [DOC spec §5.3]
- **Typical flow:** a manager sends an SR export (xlsx) to a MermIA WhatsApp number; an owner asks questions in WhatsApp. [DOC `docs/kickoff/08-mvp-4-week-plan.md`]
- **Team:** two devs (Dev A = data, Dev B = conversation) plus founders (customers, legal, Meta verification). [DOC `08`, `CLAUDE.md`]

## Direction (documented, from kickoff of 2026-10-15)

- Sell **cost-side value**: recipe costing, margin and price-shock alerts, price suggestions, CFDI/receipt price capture. Sales Q&A is included but is not the paid value because SR already gives it free. [DOC `00-executive-summary.md`, `14-product-features.md`]
- MVP ingestion: WhatsApp upload plus an email inbox (SR 12 Corte Z email, CFDI XML). Target ingestion: SR ERP/PMS JSON push (Phase 1b). Local DB connector: fallback only after legal review. [DOC `00`, `09` §10]
- Proposed pricing (Márgenes MXN 899/location/month, etc.) is a **recommendation to be tested in the pilot**, not a decision. [DOC `00`, `10-business-model.md`; HYP]
- Reports: weekly by default, daily opt-in. Models: Claude Haiku 5.5 primary, Sonnet 5.5 escalation, both gated by a 40-question eval. [DOC `00`, `13`]

## What exists today (verified)

Only the **data foundation** of Phase 1 exists in code:

| Piece | Where | State |
|---|---|---|
| 40-table Postgres schema with RLS, grants, triggers, pgTAP tests | `supabase/migrations/*` (8 files), `supabase/tests/*` (6 files) | [CODE] On branch `MR-10-contracts-schema` only. **Not on `main`**; PR open: mermia-tech/MermIA#49 (issue #10) |
| Generated Pydantic row models | `packages/contracts/src/mermia_contracts/db/models.py` | [CODE] generated; on the MR-10 branch only |
| `NormalizedBatch` parser-output contract | `packages/contracts/src/mermia_contracts/batch.py` | [CODE] hand-written; some input types are PROVISIONAL |
| FastAPI skeleton (`/health` only), uv workspace, GitHub Actions CI | `apps/api/`, `pyproject.toml`, `.github/workflows/ci.yml` on `origin/main` | [CODE via `git show origin/main:`] merged by PR #48 (MR-9); **not present on the MR-10 branch** |
| Claude Code skills, hooks, skeptic reviewer | `.claude/` | [CODE] merged (PR #47) |
| Research/plan | `docs/kickoff/*` (15 files + `research/`), `docs/kickoff-prompt.md` | [DOC] dated 2026-10-15 |

**Nothing else is built**: no parsers, no WhatsApp webhook, no RPCs (metrics), no `apply_batch`, no agent, no LLM code, no jobs, no dashboard, no fixtures/seed data. Each is a numbered open issue (see `03-status-and-testing.md`). A spec describing a feature is not evidence it exists.

## Known scope boundaries

- Phase 1 MVP goal: **live pilot ~day 16 of a 4-week plan** with one pilot restaurant. [DOC `08`] Whether that calendar is still valid is [UNK]; the MR-10 spec explicitly says "no calendar plan" for that ticket (P1).
- Out of MVP: dashboard, local connector, ERP/PMS push, photo OCR, inventory, self-serve signup/billing, voice, >2 locations. [DOC `08` "Out"]
- The pilot restaurant, its SR version, and real SR export samples are **not in the repo** ([UNK]; tickets #5, #6 open).

---

# How an AI assistant should work on this project

Audience: ChatGPT (or any assistant without repo access) acting as planning / requirements / prompt-design partner next to Claude Code, which executes in the repo. The assistant cannot see code unless the user pastes it. Treat this pack as a snapshot of **2026-10-18**; ask for fresh `git status`, `gh issue view <n>` and diffs before relying on it.

## Role split

| Who | Does |
|---|---|
| ChatGPT (you) | Clarify requirements, analyse trade-offs, break work into tickets, draft implementation prompts and review checklists, challenge assumptions, summarise decisions |
| Claude Code | Reads and edits the repo, runs checks, commits, opens PRs, applies `/start-ticket`, `/check`, `/review` |
| The human (owner / founders / devs) | Approves contracts, security-relevant choices, merges, anything customer-facing, anything legal |

Never claim a feature is done because a document describes it. Use the tags of this pack: **[CODE]** verified in code, **[DOC]** written plan/decision, **[HYP]** assumption, **[UNK]** unknown. When you answer, keep that distinction and say which tag each important statement has.

## Before proposing any change, establish

1. **Which ticket** (`MR-<n>`) and its "Done when" list. Ask for `gh issue view <n>`. If there is no ticket, propose one in the repo's format (`docs/process/ticket-guide.md`: short sentences, <= 7 steps, checkable, time as a number, English).
2. **Which branch/base.** The MR-10 branch does not contain MR-9; confirm what is merged on `main` (`git log origin/main`).
3. **Which contract is touched**: DB schema (migrations), `NormalizedBatch`, RPC shapes, tool schemas, `PendingChange`. Contract changes need both devs and must be made first, with mocks for the other side.
4. **Security impact**: tenant isolation, location scope, who can write, whether a claim's trust changes. Re-read `01` (domain rules) and spec §7.
5. **Unverified inputs**: does the work depend on SR report formats, Corte Z, CFDI, Meta behaviour or model quality that are still **unverified**? If yes, say so and propose how to get the sample/eval first.
6. **Existing code**: ask Claude Code to search for an existing helper/pattern before inventing one; check `docs/kickoff/09-architecture.md` and the spec section named by the ticket.
7. **Customer-facing text?** It must be Mexican Spanish; everything else English.

## Phases to keep separate

1. **Plan** (you + human): goal, non-goals, contract impact, risks, test list, split into steps <= ~400 lines / 1-2 days. Output: a plan the human approves. No code.
2. **Implement** (Claude Code): tests first where logic is non-trivial (the repo uses TDD for MR-10); one branch `MR-<n>-slug`, commits `MR-<n>: ...`.
3. **Test**: run `/check` and the ticket's own commands (see `03`); report real output; unrun checks are "not run".
4. **Review**: `/review` (code-review then `skeptic-reviewer`: cross-tenant leaks, unapproved writes, wrong money numbers, broken contracts). A different pass from the author's.
5. **Human merge**: no merge, no ticket close, no push to shared infrastructure without the human.

## Hard constraints (do not propose violating them)

- Agent writes only through `pending_change` + human approval + audit log; the LLM never calls `apply_*`.
- Numbers shown to customers are produced by code (SQL/RPC), validated against tool output; never let an LLM compute money.
- Every new table: tenant-scoped, RLS, explicit grants via `app.finish_table`, composite FK to tenant-scoped parents, `restrict` deletes; never edit a merged migration; never put functions/views/non-domain tables in `public`; never hand-edit `db/models.py`.
- Money: bigint centavos for ledger values, `numeric` pesos for unit prices, percent points for `*_pct`; no floats; round once at the end.
- Preserve fail-closed location semantics; do not give a client a path to set claims; do not use the service role in the LLM tool path.
- Personal data minimal (first names only; no phone/RFC to the LLM). Do not paste secrets, tokens, real customer data or SR exports with personal data into ChatGPT; the local Supabase demo keys are fine but still not to be reused anywhere real.
- Do not invent requirements: if the docs are silent, list it as an open question (`04`) with options and a recommendation.
- Do not re-open decisions marked **[APPROVED]** in `02` without saying that you are proposing to change an approved decision and why.

## Regression risks to name explicitly in any proposal

- Changing a migration/enum/column without regenerating models (hash + freshness tests fail).
- Widening an RLS policy, adding a client grant, or exposing a relationship (catalog, isolation, exposure tests fail by design).
- Adding a table: the catalog test asserts 40 tables; the generator and `NormalizedBatch` MAP tables may need updates.
- Changing provisional `*In` types: additive changes only until real parsers land.
- Touching `.gitignore`/`README.md`/workspace config: known merge conflicts with `origin/main`.
- Changing the LLM prompt prefix or tool schemas: breaks cache assumptions (static, byte-identical prefix) and requires the eval subset.

## How to write a prompt for Claude Code (template)

```
Ticket: MR-<n> <title>  (paste the issue body and its "Done when")
Branch: MR-<n>-<slug>, base: <verified base>
Context to read first: <exact files/sections, e.g. docs/kickoff/09-architecture.md §4.1; spec §7.2>
Goal (one sentence) and explicit non-goals:
Contract impact: <none | which contract, and who must approve>
Constraints: <copy the relevant hard constraints above>
Steps: 1. write failing tests for <behaviour> 2. implement 3. run <exact commands> 4. report real output
Done when: <checkable list>
Do not: touch <files/areas>, merge, push, edit merged migrations, change approved decisions
Report back: files changed, commands run with results, anything not run, open questions
```

## When you are unsure

Say what you do not know, which tag it has, and ask the human or Claude Code to verify with a specific read-only command (for example `git log origin/main --oneline`, `gh issue view <n>`, `rg <symbol>`, `supabase test db`). Prefer one recommendation with reasons over a survey of options.
