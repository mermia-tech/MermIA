# MR-26: router and zero-token templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The top 8 owner questions are answered by code (router + RPC + es-MX template, 0 tokens). Everything the router is not sure about goes to a `Broker` interface, which is a stub in this ticket.

**Architecture:** A new package, `apps/api/src/mermia_api/agent/`, with three pieces:
- `route(text, locations) -> Match | None` is pure and works on a closed vocabulary: any word it does not know means no match.
- `render(rpc, args, envelope, locations)` copies figures from the RPC data into a Spanish reply.
- `answer(request, *, locations, rpc, broker)` connects them, checks the RPC's data against its model and handles RPC failures.

The work is built in vertical slices: the first slice takes one intent end to end, and each later slice adds intents, with each intent's router rule and template written together.

**Tech Stack:** Python 3.12, pydantic v2, pytest, `uv`. It uses what already exists:
- `mermia_contracts.agent` (C6);
- `mermia_contracts.rpc` (C3 `RPCS`, `RpcEnvelope`);
- `mermia_contracts.keys.normalize_name`;
- the RPC examples in `packages/contracts/tests/examples/rpc/`;
- the eval cases in `apps/eval/cases/`.

**Spec:** `docs/superpowers/specs/2026-11-04-mr-26-router-templates-design.md` (revised after the senior review). Branch `MR-26-router-templates`, cut from `main`.

## Global Constraints

- No change to `packages/contracts`, `apps/eval/cases/` or the ingestion code. No new dependency.
- Rendering copies figures from the RPC data: `text` fields, `name`s, `Count` integers, and dates through the one helper. No arithmetic, no reformatting of money or percentages.
- When in doubt the router returns `None`. A wrong match is a bug; a missed match is not.
- Every `Match.args` validates against `RPCS[match.rpc].args` before the call. Every `data` validates against `RPCS[rpc].data` before rendering.
- Word lists (triggers, measures, fillers, write verbs, period phrases) are data in `router.py`, matched on whole words after `normalize_name`.
- Customer-facing text is in Mexican Spanish. Code, comments, test names and logs are in English.
- Each task starts with failing tests. Helpers are pytest fixtures, not imported functions (`--import-mode=importlib`).
- Test locations (El Güero, from `apps/eval/src/mermia_eval/config.py`): Centro `705e8e51-376b-5785-adbb-405eff4e2a22`, Polanco `fdda5e3b-6bcd-5c48-a6de-f524be37463e`.
- Commits are `MR-26: <what changed>`.

## Review Focus

- **The one failure that matters:** a message routed to a call that differs from its eval case's arguments (F3, compared after `model_validate(...).model_dump(mode="json", exclude_defaults=True)`).
- **A word the router does not know must give `None`.** That includes a dish, a staff name, a payment filter on a sales total, a location the user cannot see, or "mes" read inside "meseros".
- **Comparisons:** "este mes contra el mes pasado" and any pair other than last week against the week before must give `None`.
- **Rendering:** a null figure shown as 0; a flag's message missing from the reply.
- **`pc:` action ids** reaching anything but the broker.

---

### Task 1: Router core with closed vocabulary, and the sales total intent (intents 1-2)

**Goal:** build the precision rules all intents share, prove them on the simplest intent, and add the eval sweep that guards every later task.

**Files:**
- Create: `apps/api/src/mermia_api/agent/__init__.py` (docstring only), `apps/api/src/mermia_api/agent/router.py`
- Test: `apps/api/tests/agent/conftest.py` (El Güero locations fixture), `apps/api/tests/agent/test_router.py`

**Interfaces:**
- Produces:
  - `Intent = Literal["sales_yesterday", "sales_period", "compare_periods", "top_dishes", "food_cost", "compare_locations", "payment_methods", "data_status"]`.
  - A frozen `Match(intent, rpc, args)`.
  - `route(text: str, locations: Mapping[UUID, str]) -> Match | None`.

**Steps:**
- [x] **Step 1: Failing tests.**
  - **Eval sweep.** Parametrized over every `apps/eval/cases/*.json`, read as JSON by path:
    - `test_eval_cases_never_mismatch`: F3, using the normalized comparison.
    - `test_must_match`: the `MUST_MATCH` list, starting with `sales_yesterday` and `sales_last_week`.
    - `test_must_not_match`: all 25 ids of the spec's `MUST_NOT_MATCH` list, from day one, since they must already hold.
  - `test_match_args_validate`.
  - **Hand-written positives:**
    - accents and case ("¿Cuánto VENDÍ ayer?");
    - every period phrase in the spec's table, including "en lo que va del mes";
    - fillers ("oye, dime cuánto vendí ayer porfa").
  - **Hand-written negatives**, each must give `None`:
    - no period ("cuánto vendí");
    - two periods;
    - leftover digit ("vendí $200,000 la semana pasada, ¿cierto?", "del 5 al 11 de octubre");
    - write verb ("redondéame las ventas de ayer"), while past tense still matches when the rest is known;
    - an unknown word ("cuánto vendí ayer de tacos al pastor", "cuánto vendió Pepe ayer");
    - "en Centro" from a Polanco-only user;
    - two locations;
    - the substring trap ("meseros").
  - **Location.** The longest name is matched first; with no location, `location_id` is absent.
- [x] **Step 2: Run** `uv run pytest apps/api/tests/agent -q`. Expected: FAIL.
- [x] **Step 3: Implement** `router.py` with the shared rules and the sales total triggers only.
- [x] **Step 4: Run** the tests, then `uv run mypy`. Expected: PASS, clean.
- [ ] **Step 5: Commit** `MR-26: router core with closed vocabulary and the sales total intent`. Include the spec and this plan.

**Result (2026-11-04):**
- Red: collection failed (`mermia_api.agent` did not exist).
- Green: `uv run pytest apps/api/tests/agent` gives 99 passed. `uv run mypy` is clean, and `ruff check` / `ruff format --check` on `apps/api` are clean.
- Eval cases matched: only `sales_yesterday` and `sales_last_week`, both with their expected args.
- The leftover-digit rule needs no code of its own: a digit is never in the vocabulary, so the closed vocabulary already rejects it.
- Step 5 (commit) is waiting for authorization.

**Acceptance:**
- The sweep is green on 40 cases.
- The 2 MUST_MATCH and the 25 MUST_NOT_MATCH cases hold.
- Every hand-written negative gives `None`.

**Dependencies:** none. **Scope:** S (2 source files, 2 test files).

### Checkpoint 0: before Task 2
- [x] Confirm the two shapes MR-27 will build on. Changing either after Task 2 means rework.
  - The `Broker` signature: `(request, locations) -> AgentResponse`, with the RPC caller given when the broker is built.
  - `render(rpc, args, envelope, locations)`, reused by MR-27.
  - MR-26 and MR-27 have the same owner (`p0sin`), so this is a decision to write down, not a meeting.
  - Done: confirmed with the approved spec on 2026-11-04.

### Task 2: Rendering, pipeline and stub broker for the first slice

**Goal:** "¿cuánto vendí ayer?" works end to end (`answer()` → router → RPC → Spanish reply), and any other message reaches the stub.

**Files:**
- Create: `apps/api/src/mermia_api/agent/templates.py`, `apps/api/src/mermia_api/agent/broker.py`
- Modify: `apps/api/src/mermia_api/agent/__init__.py` (`answer`, `RpcCall`), `apps/api/tests/agent/conftest.py` (fixtures)
- Test: `apps/api/tests/agent/test_templates.py`, `apps/api/tests/agent/test_answer.py`

**Interfaces:**
- Produces:
  - `RpcCall = Callable[[str, dict[str, Any]], RpcEnvelope[Any]]`;
  - `render(rpc, args, envelope, locations) -> TextMsg`;
  - the `Broker` protocol;
  - `StubBroker`, which returns `route="fallback"` and a fixed text (the menu arrives in Task 7);
  - `answer(request, *, locations, rpc, broker) -> AgentResponse`.
- Fixtures:
  - `fake_rpc`: returns `RpcEnvelope.model_validate(example["response"])` from `packages/contracts/tests/examples/rpc/<rpc>.json`, can be overridden per test, and records the calls;
  - `counting_broker`.

**Steps:**
- [x] **Step 1: Failing tests.**
  - **Rendering:**
    - Sales summary from the example equals the exact expected string. It shows `net_sales.text`, `tickets` as the integer it is, `avg_ticket.text` and `change_vs_previous.text`.
    - The `get_sales_summary.nulls.json` variant leaves out the null lines.
    - With no location the reply says "en tus 2 sucursales"; with one location it gives the name.
    - `missing_days`, `previous_partial` and `partial_data` each add their message as their own line, in order. A flag without a message adds nothing.
  - **Pipeline:**
    - A matched text returns `route="template"` and the broker is not called.
    - Unmatched text, `pc:<uuid>:approve` and media call the broker once with the request unchanged.
    - `locations` that differ from `request.location_ids` raise.
  - **Failures:**
    - `no_data` (`get_sales_summary.error.json`) returns "No tengo datos de ayer todavía." with `route="template"`.
    - `internal`, a raised exception and data that does not fit `SalesSummaryData` return the fixed "No pude consultar eso ahora…" with `route="fallback"`. The error is logged (`caplog`) and the broker is not called.
  - **N1:** a subprocess imports `mermia_api.agent` and asserts that no `agno`, `openai`, `anthropic` or `google` module is in `sys.modules`.
- [x] **Step 2: Run** `uv run pytest apps/api/tests/agent -q`. Expected: FAIL.
- [x] **Step 3: Implement.** One dict of Spanish period labels (`yesterday` → "ayer"…) and one date helper (America/Mexico_City), each defined once.
- [x] **Step 4: Run** the tests and `uv run mypy`. Expected: PASS.
- [ ] **Step 5: Commit** `MR-26: sales total answered end to end, stub broker for the rest`.

**Result (2026-11-04):**
- Red: collection failed (`mermia_api.agent.templates` did not exist).
- Green: `uv run pytest apps/api` gives 158 passed and 16 skipped (the `db` tests). `uv run mypy` is clean, and `ruff check` on `apps/api` is clean.
- Three test bugs were fixed along the way: the contract models are frozen, so the tests now use `model_copy(update=...)`.
- Data validation lives in `render()`, and `answer()` turns the `ValidationError` into the fallback reply. The behavior is the one the spec gives: MR-27 gets the check too, since it reuses `render()`.
- Step 5 (commit) is waiting for authorization.

**Acceptance:**
- The end-to-end slice is green.
- Failures, bad shapes and fallback routes behave as the spec says.
- The no-LLM import check passes.

**Dependencies:** Task 1, Checkpoint 0. **Scope:** M (3 source files, 3 test files, all small).

### Checkpoint A: after Tasks 1-2
- [x] `.claude/skills/check/check.sh` green (2026-11-04: ruff, format, mypy, pytest, pgTAP all PASS; pgTAP ran from the `mermia-pr-review-9277cb` worktree the local Supabase points at, and this change has no SQL).
- [ ] Show the human the router's word lists and the first exact reply before adding six more intents. Changing the approach is cheapest here.

### Task 3: Last week against the week before (intent 3)

**Files:** Modify `router.py`, `templates.py`; tests in `test_router.py`, `test_templates.py`.

**Steps:**
- [x] **Step 1: Failing tests.**
  - **Matches:**
    - "¿cómo me fue la semana pasada contra la antepasada?" and "la semana pasada vs la anterior" give `last_week` vs `prev_week` with `net_sales`.
    - "ticket promedio" gives `avg_ticket`.
  - **`None`:**
    - "este mes contra el mes pasado" and "esta semana vs la pasada" (incomplete periods);
    - "ayer contra antier";
    - an unknown metric ("propinas").
  - **Rendering:**
    - From `compare_periods.json`, the exact expected string with the `a`, `b`, `abs_change` and `pct_change` texts.
    - A null `pct_change` leaves its line out.
    - `missing_days` adds its message.
- [x] **Step 2: Run, FAIL. Step 3: Implement. Step 4: Run, PASS, mypy clean.**
- [x] **Step 5: Commit** `MR-26: compare last week against the week before`.

**Result (2026-11-04):**
- Red: 8 failed (router matches, both templates, the no_data reply). The negatives already passed.
- Green: `uv run pytest apps/api` gives 173 passed and 16 skipped; mypy and ruff are clean.
- Eval matches are unchanged (`sales_yesterday`, `sales_last_week`). `sales_avg_ticket` and `sales_vs_previous_week` fall through, as optional cases may.
- Deviation from the plan: the positive "¿cómo me fue la semana pasada contra la antepasada?" names no metric. The spec says no metric means no match, so the test uses "¿cuánto vendí…?" and "la semana pasada contra la anterior" (no metric) is a negative.
- The router now picks one intent: the specific intents (`_SPECIFIC`) win over the sales total, and two specific intents give None.

**Acceptance:** the sweep is still green, `sales_month_vs_last` still gives `None`, and the hand-written matches hold.
**Dependencies:** Task 2. **Scope:** S.

### Task 4: Top and bottom dishes (intent 4)

This is the largest parser, so it gets its own task.

**Files:** Modify `router.py`, `templates.py`; tests as above.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - Add `top_dishes_top5_month_units` and `top_dishes_top3_revenue_30d` to `MUST_MATCH`.
  - **Matches:**
    - N as a number word ("los tres platillos") or as a digit, right before "platillo(s)".
    - Without N: plural gives 5, singular gives 1.
    - "menos vendido" and "menor" give `order="asc"`.
    - "ganancia en pesos" gives `margin`; "porcentaje de ganancia" gives `margin_pct`.
  - **`None`:**
    - two measures ("me deja el menor porcentaje de ganancia");
    - "platillos estrella";
    - "el más rentable";
    - a count above 10;
    - "platillos" with no measure;
    - "dos" not right before "platillos".
  - **Rendering:**
    - The ranked list of `name` and `value.text` from `get_top_dishes.json` equals the exact string.
    - Empty `rows` give "No hay ventas registradas en {periodo}."
    - `uncosted_sales` adds its message.
- [ ] **Steps 2-4:** FAIL, implement, PASS + mypy.
- [ ] **Step 5: Commit** `MR-26: top and bottom dishes intent`.

**Acceptance:** the sweep is green, and the PR records which of the 3 optional `top_dishes_*` cases match.
**Dependencies:** Task 2 (independent of Task 3). **Scope:** S.

### Task 5: Food cost and data status (intents 5 and 8)

**Files:** Modify `router.py`, `templates.py`; tests as above.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - Add `cost_margin_food_cost_yesterday` and `out_of_scope_data_status` to `MUST_MATCH`.
  - **Food cost:**
    - `group_by` is left at its default.
    - The reply shows the theoretical figure, the target when there is one, and always the coverage.
    - `cost_estimated` and `cost_confirmed` add their message; `missing_days` adds its message.
  - **Data status:**
    - "¿ya están al día mis datos?" calls `get_data_status` with empty arguments.
    - The reply shows the last load (a date from the helper), the missing days or "no falta ningún día", `stale_costs` as the integer and `coverage.text`.
  - **`None`:**
    - "food cost" with no period;
    - "¿cuántos empleados tengo?";
    - two intents ("ventas y food cost de ayer").
- [ ] **Steps 2-4:** FAIL, implement, PASS + mypy.
- [ ] **Step 5: Commit** `MR-26: food cost and data status intents`.

**Acceptance:** the sweep is green, both MUST_MATCH cases match, the coverage is always in the food cost reply, and the two-intent message gives `None`.
**Dependencies:** Task 2. **Scope:** S.

### Task 6: Compare locations and payment methods (intents 6 and 7)

**Files:** Modify `router.py`, `templates.py`; tests as above.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - Add `locations_centro_vs_polanco_last_week`, `locations_this_month_sales` and `ops_payment_split` to `MUST_MATCH`.
  - **Compare locations:**
    - A one-location user gets `None`.
    - "food cost por sucursal la semana pasada" gives `food_cost_pct`, and wins over intent 5.
    - Location names in the text are accepted, but `location_ids` is never sent.
    - The reply shows the ranked rows with `value.text` and `diff_vs_best.text`.
    - `missing_locations` and, for `food_cost_pct`, `cost_estimated` add their messages.
  - **Payment methods:**
    - Triggered by "por tarjeta, efectivo y transferencia" or "formas de pago"; wins over the sales total.
    - Labels: Tarjeta, Efectivo, Transferencia; an unknown key is shown as is.
    - Each row shows `share.text`.
    - Empty rows give the empty message.
    - `partial_data` ("Solo 3 de 7 días con ventas tienen este detalle.") adds its message.
  - **`None`:**
    - "¿quién de mis meseros vende más este mes?";
    - "¿qué día de la semana me deja más?".
- [ ] **Steps 2-4:** FAIL, implement, PASS + mypy.
- [ ] **Step 5: Commit** `MR-26: compare locations and payment methods intents`.

**Acceptance:** the sweep is green and all 9 MUST_MATCH cases match.
**Dependencies:** Task 2. **Scope:** S.

### Task 7: The fallback menu and `tpl:` taps

**Files:** Modify `router.py` (menu table: intent → fixed arguments), `broker.py` (menu), `__init__.py` (`tpl:` handling); test `test_answer.py`.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - The stub's reply is one `choices` message with the 8 options from the spec. The locations option is left out for a one-location user. Ids are `tpl:<intent>`. Every label fits in 24 characters, including "Semana vs anterior".
  - Each `tpl:<intent>` runs its fixed arguments and returns `route="template"`.
  - An unknown `tpl:foo`, and `tpl:compare_locations` from a one-location user, go to the broker.
- [ ] **Steps 2-4:** FAIL, implement, PASS + mypy.
- [ ] **Step 5: Commit** `MR-26: fallback menu and template taps`.

**Acceptance:** every menu option is answered by a template, and no button is left without an answer.
**Dependencies:** Tasks 3-6 (the menu needs every intent). **Scope:** S.

### Checkpoint B: after Tasks 3-7
- [ ] `.claude/skills/check/check.sh` green.
- [ ] Go through the spec's acceptance criteria one by one and tick them.
- [ ] List which of the 6 optional eval cases match.

### Task 8: PRs (no new code)

The work ships as two PRs, because `docs/process/ticket-guide.md` asks for PRs under about 400 lines:
- **PR 1 (Tasks 1-2):** the router core, one intent end to end, and the stub broker. It opens after Checkpoint A, so the product owner reviews the approach on a small diff.
- **PR 2 (Tasks 3-7):** the other intents and the menu, branched from PR 1 (or from `main` once PR 1 is merged).

For each PR:
- [ ] Paste the exact replies from the tests into the PR description, so the product owner can approve the wording. PR 1 has 1 reply; PR 2 has the other 7.
- [ ] Put in the PR body:
  - the optional-case list from Checkpoint B;
  - the spec's follow-ups: LLM picks / template answers for MR-27, the scope and flags of the remaining RPCs for MR-31, and the business-day cutoff.
- [ ] Run `/review` (the built-in `/code-review`, then the `skeptic-reviewer` agent), fix the findings and open the PR.

**Dependencies:** PR 1 on Checkpoint A; PR 2 on Checkpoint B.

## Parallelization

Tasks 3, 4, 5 and 6 depend only on Task 2. Each one edits `router.py` and `templates.py`, so doing them in parallel would conflict at merge. Do them in order, one person. Task 4 is the riskiest of them: do it early if time is short.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| The router matches a message it should not (a wrong confident figure) | High | Closed vocabulary; the 40-case sweep with explicit MUST_NOT_MATCH; negatives in every task; one-intent and priority rules |
| The closed vocabulary is too strict and few messages match | Medium | Accepted by the spec (precision over coverage). Filler lists grow from pilot data (spec follow-up) |
| Word lists grow into an unreadable pile | Medium | Lists as data, one small function per intent; Checkpoint A reviews them before 6 more intents |
| Food cost, compare locations and breakdown are only in open PR #77; it may change before merge | Medium | `data` is validated against the contract model (a mismatch gives the fallback reply, not a crash). Flags are shown by message, not code, so a new code needs no change. MR-31 runs the exact replies against the real RPCs |
| A flag message reads badly next to a template line | Low | Product owner reads the exact replies with flags in PR 2; MR-24 review note |
| `Broker` and `render` do not fit MR-27 | Low | Same owner; Checkpoint 0 before Task 2 |
| PR over the ~400-line guideline | Low | Two PRs (Task 8) |
| `locations` is not loaded by anything yet (D1) | Low for this ticket | The channel ticket loads it from `location`; noted in the PR |
| The mock returns one fixed answer per RPC, whatever the arguments | Low | Router arguments are checked against the eval cases and rendering against the examples, as the spec intends |

## Self-review: spec coverage

| Spec item | Task |
|---|---|
| Whole words, closed vocabulary, leftover digits, write verbs, named periods | 1 |
| Triggers and priority, one intent, no fallback to another intent | 1, 5, 6 |
| Location: visible names, longest first, invisible names fall through, intent 6 never sends ids | 1, 6 |
| Intent 3 restricted to complete weeks | 3 |
| Intent 4 measures, order, N placement | 4 |
| `render` keyed by RPC; number sources; labels; nulls; empty rows | 2-6 |
| Food cost coverage line; data status dates | 5 |
| Every flag message shown, one test per code of the 8 RPCs; no message → nothing | 2, 3, 4, 5, 6 |
| Data validated against the RPC model; `no_data`, other errors, exceptions | 2 |
| `locations` agrees with `request.location_ids` | 2 |
| `Broker` protocol and stub; signature agreed with MR-27 | Checkpoint 0, 2 |
| Fallback menu, `tpl:` taps, unknown `tpl:`, one-location user | 7 |
| `pc:`, media and other actions → broker | 2 |
| F3 with normalized comparison; MUST_MATCH (9); MUST_NOT_MATCH (25); optional (6) | 1, 3-6, Checkpoint B |
| N1 import check; N2 pure router; N3 `/check`; N4 no dependency | 2, 1, checkpoints, global |
| Exact replies; wording approved in the PR | 2-6, 8 |
| Follow-ups for MR-27, MR-24 review note, MR-31; pilot | 8 |
| Two PRs under the ~400-line guideline | 8 |

Not covered, by design (out of scope in the spec): the LLM broker loop and validator, channels, `pc:` handlers, memory, caps, `llm_usage`, explicit dates, incomplete-period comparisons, the business-day cutoff.

## Open items

- **Checkpoint 0:** the `Broker` and `render` signatures, with the owner of MR-27. This is the only coordination step before Task 2.
- **Checkpoint A:** the word lists and the first exact reply, reviewed by the human.
