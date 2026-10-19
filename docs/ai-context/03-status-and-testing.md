# 03 - Current status and testing

Snapshot 2026-10-18. Sources: `git log`, `git branch -a`, `gh issue list --state all`, `gh pr list --state all`, file reads. Issue/PR state can change; re-query before relying on it: `gh issue list --state all --limit 100`.

Tags: **[CODE]** present in repo; **[REPORTED]** result stated in the MR-10 spec §17 (author-run, 2026-10-18), **not** re-executed for this pack; **[UNK]**. Counts of test files below were taken by listing files; test totals are the spec's.

---

# Current status and backlog

## Git / PR state [verified with git and gh]

| Item | State |
|---|---|
| `origin/main` | `ca5bb10` - includes PRs #1 (kickoff docs), #45 (ticket guide), #46 (Python backend plan), #47 (Claude skills/hooks), #48 (MR-9: uv workspace, FastAPI `/health`, CI) |
| Working branch `MR-10-contracts-schema` | 20 commits ahead of the older base `d39d5ea`; **does not contain MR-9**. PR **#49** open ("Closes" issue #10). Working tree clean at snapshot |
| Merge with `origin/main` | `git merge-tree` shows conflicts in `.gitignore` and `README.md` |
| Other remote branches | `MR-1-ticket-guide`, `MR-46-python-backend`, `MR-9-accounts`, `ai-skills`, `docs/kickoff-research` (all merged per PR list) |
| Issue #9 (accounts) | still OPEN although PR #48 for `MR-9-accounts` is merged; whether its "done when" (cloud accounts) is met is [UNK] - the PR content is only the code skeleton and CI |

## Done (verified in code on the MR-10 branch)

| What | Evidence |
|---|---|
| 8 migrations: foundations (helpers, UUIDv7, `finish_table`), enums (24), identity & sources, ingestion, catalog & sales, control, costing, metrics -> **40 tables** | `supabase/migrations/*`; count of `create table public.*` = 40 |
| 6 pgTAP files (catalog, isolation matrix, location, write denial, integrity, exposure) | `supabase/tests/*.test.sql`; spec §17 reports 228 tests PASS on 2026-10-18 (**not re-run for this pack**) |
| DB model generator + generated models + freshness guards | `packages/contracts/src/mermia_contracts/tools/gen_db_models.py`, `db/models.py` |
| `NormalizedBatch` + input types + example JSON batches (5 valid, 11 invalid, 1 JSON schema file in `tests/examples/`) | `batch.py`, `tests/examples/` |
| REST exposure tests (local stack) | `tests/test_rest_exposure.py` |
| Docs updated for the contracts/DB move (README, `09`, `08`) | `README.md`, `docs/kickoff/09-architecture.md` |
| Process tooling: ticket guide, issue template, `/check`, `/review`, `/start-ticket`, skeptic reviewer, hooks | `docs/process/`, `.github/ISSUE_TEMPLATE/`, `.claude/` |
| (main) uv workspace, FastAPI health endpoint with one test, CI (python + pgTAP jobs) | `git show origin/main:...` |

Verification status of MR-10 per its own spec §17 (2026-10-18, local stack): `supabase db reset` 8 migrations OK; `supabase test db` 228 pass; `uv run pytest` 89 pass; `-m db` 5 pass; `-m rest` 25 pass + 1 skip (GraphQL; `pg_graphql` not enabled locally); generator `--check` clean; ruff/mypy clean on the package. A pre-PR review fixed 5 findings. **I did not execute any of this**; treat as author-reported.

## Incomplete / known gaps in the delivered MR-10 work

| Gap | Source |
|---|---|
| Provisional types depend on unverified SR formats (`MenuItemIn`, `ItemSalesIn`, `DailySalesIn`, `RecipeIn`, `RecipeLineIn`); `PurchaseIn` unvalidated vs SAT XSD; `TicketIn` has no adapter | `packages/contracts/README.md`; spec §16.5 |
| GraphQL exposure untested; hosted-project extensions and default grants unchecked (A24, O7) | spec §16.4, §12.2 |
| Partial unique index "one applied batch per slice" untested under real apply ordering | spec §16.4 |
| `public` holds no functions: metric RPCs, `apply_*` have no home yet beyond the rule that they go through `SECURITY DEFINER` with explicit checks | spec §8.1 |
| No unique key on ticket `(tenant_id, source_id, external_id)`; no cross-field validation in `NormalizedBatch` -> MR-16 must handle | spec §8.2 |
| Model-freshness and REST tests skip in CI because `MERMIA_DB_URL` etc. are unset | spec §8.2; `ci.yml` |
| Contracts package not yet integrated into the root workspace (own lock/Python pin; root mypy `files` lists only `apps`) | `origin/main:pyproject.toml` |
| Spec text drift: header says "Branch (not yet created)"; calls the function `secure_table` (code: `finish_table`); implementation status line contradicts | spec lines 3, 5.1, 6.1 |

## Backlog: GitHub issues (all OPEN at snapshot; all labelled `sprint-1`)

| Week | Dev A (data) | Dev B (conversation) | Both / founders |
|---|---|---|---|
| 1 | #10 schema + NormalizedBatch (PR #49, in review); #12 fixtures "Taquería El Güero" seed; #14 migrations/RLS/security tests (largely covered by MR-10 content; scope overlap [UNK]); #15 parser "Productos vendidos"; #16 `apply_batch`/`rollback_batch`; #17 first 4 read RPCs | #3 register +52 number; #4 submit 6 WhatsApp templates; #13 mock RPC server; #18 LLM eval harness; #19 write 40 eval questions; #20 run eval, decide model (gate); #21 WhatsApp webhook + file download; #22 test sending exports iOS/Android | #9 dev accounts; #11 contract: RPC shapes, agent tools, pending changes (both); founders: #2 Meta Business Verification, #5 pilot + sample exports, #6 10 owner interviews, #7 ERP/PMS price + SR form, #8 lawyer |
| 2 | #23 parsers Ventas por día/Corte Z + Recetas; #24 remaining 7 read RPCs; #25 costing engine + recipe importer; #30 tenant/user admin script | #26 router + zero-token templates; #27 broker loop + number validator; #28 upload flow messages + Deshacer; #29 opt-in, identity mapping, roles | #31 integration mock -> real RPCs (both) |
| 3 | #32 `apply_pending_change` (5 kinds); #33 margin alerts + price suggestions; #34 `build_weekly_report`; #35 load pilot history/recipes/prices; #36 stretch CFDI XML parser | #37 confirmation service; #38 weekly report job + "Ver detalle"; #39 email inbox; #40 prod deploy, Sentry, cost metering | #41 dress rehearsal + go/no-go (both) |
| 4 | #42 go-live cross-check | #43 go-live daily review | #44 day-20 review (both) |

Issue titles are in `gh issue list`; there is no issue for the Phase 1b/2 items in `07-roadmap.md`. The calendar attached to these labels (week-1..4 from kickoff) may no longer match reality ([UNK]; the MR-10 spec dropped calendar planning).

## Blockers and dependencies that can be verified

- Real SR export samples (#5) block parsers #15/#23 and finalising provisional contract types. Fallback in `08`: build fixtures from the SR 8 manual and swap later (risk: rework).
- #11 (RPC shapes, tool schemas, `PendingChange` kinds) blocks #13, #17/#24, #18, #26-#27, #32; kinds are unresolved (5 in `08` vs 7 in `09` §5.1).
- Meta Business Verification (#2) and number (#3) block any real WhatsApp testing; templates (#4) need approval time.
- The JWT claim issuer (#27/#29/#40) must exist before real tenant data (spec §7.6).
- LLM eval gate (#20) blocks agent code merges.

## Risks (documented; probabilities are the kickoff's opinion) [DOC `docs/kickoff/05-risks-and-friction.md`]

Top: manager stops uploading (#1); cost data missing/stale (#5); low willingness to pay vs free SR Admin (#8); one wrong number kills trust (#6, #7); Haiku 5.5 unproven (#15); 2-dev capacity (#16); small SR-only market ~4% (#18); legal (LFPDPPP, SR EULA); Meta category/pricing changes.
Additional engineering risks from MR-10 spec §15: fail-closed claim breaks an issuer that forgets the key (R9); class X/F may hide data a later dashboard needs (R10); unauthorised exposure through a future table or Supabase default change (R4, R5).

## Known defects

No open defect list exists in the repo or in GitHub issues (no `bug` label observed). Defects found and fixed during MR-10 are listed in spec §17.1. Any currently failing test is [UNK] because the suite was not run for this pack.

---

# Testing and quality

## Existing tests

### pgTAP (`supabase/tests/`, run by `supabase test db`) [CODE]

| File | Proves |
|---|---|
| `00_catalog.test.sql` | exactly 40 tables in `public`, no functions/views there; RLS on; `rls_class` comment per table; exact privileges per class; no `PUBLIC`/`anon` execute on functions; text checks and unit tags present (the UUIDv7 license notice is checked by `test_migration_notices.py`) |
| `10_isolation.test.sql` | data-driven matrix over all client-readable tables: tenant A / tenant B / no claim / malformed claim / `anon` |
| `20_location.test.sql` | `can_see_location` fail-closed cases; class F (`pending_change`, `audit_log`) all-location members only; LP inheritance for `import_issue`; the four class L catalog/staff tables |
| `30_write_denial.test.sql` | clients cannot write; `audit_log` immutable for every role; membership checks instead of invalid `SET ROLE` |
| `40_integrity.test.sql` | `touch_row`, membership location trigger, `uuid_v7` (>= 10,000 values: version/variant/uniqueness/ordering/round-trip), partial unique index, `num_nonnulls` checks, composite FKs reject cross-tenant for `postgres`/`service_role` |
| `50_exposure.test.sql` | indirect exposure paths (views, relationships, functions) |

[REPORTED] 6 files, 228 tests, PASS. Mutation checks (dropping/widening a policy) were detected by the matrix.

### Python (`packages/contracts/tests/`) [CODE]

| Group | Files | Needs |
|---|---|---|
| Contract types and examples | `test_batch_types.py`, `test_batch_enums_json.py`, `test_batch_examples.py` (+ `examples/*.json`, `normalized_batch.schema.json`), `test_batch_provisional.py`, `test_models_static.py`, `test_smoke.py`, `test_migration_notices.py` | nothing |
| Generator guard (hash of migrations) | `test_generator_hash.py` | nothing (fails if a migration is edited after generation, also fails outside the repo - intended) |
| Models vs live DB | `test_generator_fresh.py`, `test_models_match_db.py`, `test_batch_matches_db.py` | `MERMIA_DB_URL`, marker `db` |
| REST exposure (PostgREST) | `test_rest_exposure.py` | local stack + `MERMIA_API_URL`, `MERMIA_JWT_SECRET`, `MERMIA_API_KEY`, marker `rest` |

Default pytest addopts: `-m 'not db and not rest'`. [REPORTED] 89 passed without DB; 5 passed with `-m db`; 25 passed + 1 skipped (GraphQL) with `-m rest`.

### App code (main only) [CODE via `git show origin/main:`]

`apps/api/tests/test_health.py`: one test for `GET /health`. Nothing else in the application is tested because nothing else is built.

## Coverage and quality gaps (verified or reported)

- No coverage tooling is configured (no coverage config in `pyproject.toml`) [CODE]. Coverage percentage is [UNK].
- GraphQL exposure untested (`pg_graphql` off locally) [REPORTED].
- Hosted Supabase project behaviour (extensions, default grants, auth hook, signing keys) untested; no remote DB exists in the repo's evidence [REPORTED].
- CI skips DB-dependent contract tests (no env vars), so a stale `db/models.py` would pass CI unless MR-9 CI is extended [CODE `ci.yml`; spec §8.2].
- CI's pgTAP job uses `supabase db start` + `supabase test db`; whether this works with the 8 migrations on the CI runner is [UNK] (never run: the MR-10 branch has not been merged with MR-9's CI).
- Performance: per-row cost of `can_see_location` at scale not measured (spec §17.1 "rejected after testing: measure at scale").
- Parsers, RPCs, agent, eval, webhook: no tests because no code.
- Planned but non-existent: golden-file tests (SR sample -> expected `NormalizedBatch`), contract tests "real RPC output parses with C3 models", 40-question LLM eval (subset of 10 per prompt change, full 40 nightly), manual day-15 script (8 steps) [DOC `08`].

## Acceptance criteria

- **Per ticket:** the "🏁 Done when" checklist in the GitHub issue; must be checkable by someone who did not write the code. [DOC ticket guide]
- **MR-10:** 12 acceptance criteria in spec §14 (fresh `db reset`; 6 pgTAP files pass; exactly 40 tables and no function in `public`; isolation matrix; layered write denial; composite FK; UUIDv7 checks; pytest/db/generator `--check`; contract examples; docs updated; no files touched outside the allowed areas; owner items approved).
- **Pilot (Phase 1):** data for >= 85% of business days; >= 95% of files parsed without a dev; daily net sales within +-0.5% of SR on 100% of checked days; zero wrong numbers reported; LLM <= US$1/month for the pilot tenant; WhatsApp billed cost within 5% of `message_log`. [DOC `08` "Pilot success criteria"; targets, not measurements]
- **LLM gate:** tool selection >= 95%, args >= 95%, numeric fidelity 100%, tone >= 4/5, p95 <= 8 s. [DOC `07` M2]

## Checks to run before proposing or accepting a change

1. Read the relevant ticket's "Done when" (`gh issue view <n>`), and the affected spec section.
2. Database change: new migration (never edit a merged one) -> `supabase db reset` -> `supabase test db` -> regenerate models (`gen_db_models`) -> `uv run pytest`, `-m db`, `-m rest`, `gen_db_models --check`. A new table needs `app.finish_table` and unit tags; update `00_catalog` expectations (the count of 40 is asserted).
3. Contract change: update `batch.py`, the MAP/LOADER_ONLY tables, example JSONs and `normalized_batch.schema.json`; both devs approve (ticket guide §4).
4. Security-relevant change: think cross-tenant, cross-location, unapproved write, claim trust. Use `/review` (code-review then `skeptic-reviewer`).
5. Always run `.claude/skills/check/check.sh` (ruff, mypy, pytest, pgTAP); report failures as they are; never skip/delete a test to pass.
6. Report unrun checks explicitly as "not run" with the reason (project convention, spec §2.3).
