# MR-19: the 40 eval questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 40 Mexican-Spanish owner questions as JSON cases in `apps/eval/cases/`, each with expected tool (or none), args and figures, plus the small harness changes and the review table that make them scorable and reviewable.

**Architecture:** Extend the MR-18 case model backward-compatibly (null tool, `must_not_contain`, `category`, `expected_figures`), tell the model today's date, derive seed figures in a small module that does not read the mock, then add the cases in category batches, each commit passing the existing `must_contain`-against-mock test.

**Tech Stack:** Python 3.12, pydantic, pytest, `uv`; existing `apps/eval`, `apps/mock-rpc`, `fixtures/el_guero/expected.json`.

**Spec:** `docs/superpowers/specs/2026-10-22-mr-19-eval-questions-design.md` (plan of record for the exam: `docs/kickoff/13-llm-and-token-strategy.md` §H3). Branch `MR-19-eval-questions`, cut from `MR-18-eval-harness`.

## Global Constraints

- "Today" is Monday 2026-10-12; data ends 2026-10-11. Do not write `this_week` questions (no data on a Monday).
- Only the 12 tools of `tool_definitions()`; questions in Mexican Spanish, code and docs in English.
- Money exact; only percentages may carry a tolerance. A rounded "$184 mil" is wrong.
- `must_contain` only when the question matches the RPC's canonical query (the mock answers one fixed answer per RPC, ignoring arguments). Seed-derived figures the mock cannot return go in `expected_figures` (not scored).
- Food cost for yesterday is 37.5 % (not 31.4 %); pastor margin is 67.2 % (not 71.7 %).
- Cases with no tool: `expected_tool` is `null`, one category for "reject" and "ask back".
- Every `expected_args` key must exist in that tool's input schema.
- Counts per category: sales 7, top_dishes 6, cost_margin 6, ops 4, locations 3, ambiguous 3, writes 4, out_of_scope 4, adversarial 3 = 40 (the existing `tacos_al_pastor` case is one of cost_margin).

## Review Focus

- A case with no tool where the model still calls one (tool score must be 0) or answers with a number that is not in the question (numbers score must be 0).
- A reply that rounds or restates a figure ("$184 mil", "unos 185 mil") must fail the numbers score.
- `must_not_contain` is matched case-insensitively ("Listo, ya quedó" and "listo, ya quedó" both fail).
- A case file written before this change (no `category`, no new fields) is rejected with a clear error, not silently loaded; a stray non-case JSON in `cases/` or a duplicated `id` fails a test.
- `expected_args` with a key the tool does not accept (a typo, or a UUID where the model sends a name) must fail a test, not score 0 at eval time.

---

### Task 1: Case model, null tool and `must_not_contain`

**Files:**
- Modify: `apps/eval/src/mermia_eval/cases.py`, `apps/eval/src/mermia_eval/score.py`, `apps/eval/cases/tacos_al_pastor.json`
- Test: `apps/eval/tests/test_cases.py`, `apps/eval/tests/test_score.py`

**Interfaces:**
- Produces: `Case` with `category: Category` (required), `expected_tool: str | None`, `must_not_contain: list[str] = []`, `expected_figures: list[str] = []`; `Category = Literal["sales","top_dishes","cost_margin","ops","locations","ambiguous","writes","out_of_scope","adversarial"]`. Scores: with `expected_tool is None`, `score_tool` and `score_args` return `1.0` iff there were no calls; `score_numbers` returns `0.0` if the reply contains any `must_not_contain` phrase (case-insensitive).

- [ ] **Step 1: Write failing tests** in `test_score.py`: `test_tool_none_ok_without_calls`, `test_tool_none_zero_when_a_tool_is_called`, `test_args_none_ok_without_calls`, `test_numbers_none_tool_zero_on_figure_not_in_question` (reply "Vendiste $5,000" with no tool results), `test_numbers_zero_on_forbidden_phrase` (`must_not_contain=["ya quedó"]`, reply "Listo, YA QUEDÓ"), `test_numbers_rounding_is_zero` (reply "unos $184 mil" vs `$184,320.50`). In `test_cases.py`: `test_case_without_category_is_rejected`, `test_expected_figures_default_empty`.
- [ ] **Step 2: Run** `uv run pytest apps/eval -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the model fields in `cases.py` and the three score changes in `score.py` (a null-tool case has no tool results, so `known` is the question's numbers only). Add `"category": "cost_margin"` to `tacos_al_pastor.json`. Update fixtures in other tests that build a `Case` directly.
- [ ] **Step 4: Run** `uv run pytest apps/eval -q` and `uv run mypy`. Expected: all PASS, mypy clean.
- [ ] **Step 5: Commit** `MR-19: cases may expect no tool, forbid phrases and carry a category`. Include the design doc and this plan in this commit.

### Task 2: Guard tests for the whole case set

**Files:**
- Test: `apps/eval/tests/test_cases.py`
- Modify: `apps/eval/tests/test_cases.py` (skip the mock check when `expected_tool is None`)

**Interfaces:**
- Consumes: `load_cases()`, `tool_definitions()` from `mermia_contracts.agent_tools`.

- [ ] **Step 1: Write tests** (they pass now with one case and guard every later commit): `test_ids_are_unique`, `test_only_case_files_in_cases_dir` (every `*.json` loads as a `Case`), `test_expected_tool_is_a_known_tool_or_none`, `test_expected_args_keys_exist_in_the_tool_schema` (keys ⊆ `input_schema["properties"]`, for `expected_args` and each `accepted_args`), `test_null_tool_cases_have_empty_expected_args`.
- [ ] **Step 2: Make `test_must_contain_comes_from_the_mock_answer` skip null-tool cases.**
- [ ] **Step 3: Run** `uv run pytest apps/eval -q`. Expected: PASS.
- [ ] **Step 4: Commit** `MR-19: guard tests for ids, tools and argument names`.

### Task 3: The model learns today's date

**Files:**
- Modify: `apps/eval/src/mermia_eval/config.py` (`SYSTEM_PROMPT`)
- Test: `apps/eval/tests/test_config.py`

- [ ] **Step 1: Write failing test** `test_prompt_states_today`: `"2026-10-12"` and `"lunes"` appear in `SYSTEM_PROMPT`.
- [ ] **Step 2: Run** `uv run pytest apps/eval/tests/test_config.py -q`. Expected: FAIL.
- [ ] **Step 3: Add one sentence** to `SYSTEM_PROMPT` in Spanish: today is Monday 2026-10-12 and the data ends 2026-10-11. Keep the rest of the prompt unchanged (token cost).
- [ ] **Step 4: Run** `uv run pytest apps/eval -q`. Expected: PASS.
- [ ] **Step 5: Commit** `MR-19: tell the eval model what day it is`.

### Task 4: Seed figures, independent of the mock

**Files:**
- Create: `apps/eval/src/mermia_eval/figures.py`, `apps/eval/tests/test_figures.py`
- Test: same

**Interfaces:**
- Produces: `peso(centavos: int) -> str` (e.g. `18432050 -> "$184,320.50"`) and `derived_figures() -> dict[str, str]` mapping a source name (e.g. `"L1.daily_net_sales.2026-10-11"`) to the formatted figure, read from `fixtures/el_guero/expected.json` only. It must not import `mermia_mock_rpc`.

- [ ] **Step 1: Write failing tests:** `test_peso_formats_centavos` (`18432050 -> "$184,320.50"`, `3119500 -> "$31,195.00"`), `test_derived_includes_weekly_total` (`"$184,320.50"` is a value), `test_derived_does_not_import_the_mock` (module source has no `mermia_mock_rpc`), `test_expected_figures_of_cases_are_derived` (every `expected_figures` entry of every case is in `derived_figures().values()`).
- [ ] **Step 2: Run** `uv run pytest apps/eval/tests/test_figures.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** both functions. Cover weekly and daily net sales per location, the top-5 dishes of the month, dish costs, price jumps, cancellations by waiter and yesterday's food cost, as far as `expected.json` has them.
- [ ] **Step 4: Run** `uv run pytest apps/eval -q`. Expected: PASS.
- [ ] **Step 5: Commit** `MR-19: seed-derived figures, independent of the mock`.

### Task 5: Review table for Dev A

**Files:**
- Create: `apps/eval/src/mermia_eval/review.py`, `apps/eval/tests/test_review.py`
- Modify: `apps/eval/README.md` (one line: the command, and the new case fields)

**Interfaces:**
- Consumes: `load_cases()`, `derived_figures()`.
- Produces: `review_table(cases: list[Case]) -> str` (markdown: id, category, question, tool, args, `must_contain`, `expected_figures` with their source names from `derived_figures()`, flag "pending" for figures the mock cannot return), runnable as `uv run python -m mermia_eval.review`; it also prints `tools_sha256()` and "today".

- [ ] **Step 1: Write failing tests:** `test_table_has_one_row_per_case`, `test_table_shows_tool_none_as_ninguna`, `test_table_names_the_source_of_a_derived_figure`.
- [ ] **Step 2: Run** `uv run pytest apps/eval/tests/test_review.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `review_table` and a `main()`; add the README line.
- [ ] **Step 4: Run** `uv run pytest apps/eval -q && uv run python -m mermia_eval.review | head`. Expected: PASS and a table with the one existing case.
- [ ] **Step 5: Commit** `MR-19: review table for the figures`.

### Tasks 6 to 10: the cases, in batches

Each case is a file `apps/eval/cases/<category>_<slug>.json` with `id` equal to the file stem. Wording is the builder's: informal, how an owner types it. After each batch run `uv run pytest apps/eval -q`, `uv run ruff check . && uv run ruff format --check .`, and `uv run python -m mermia_eval.review`. Argument names must exist in the tool's schema (Task 2 test). "Canonical" means the mock's fixed answer matches the question (`packages/contracts/tests/examples/rpc/`, README of `apps/mock-rpc`): fill `must_contain` from the mock answer. Otherwise leave `must_contain` empty and fill `expected_figures` from `derived_figures()` when it has the figure.

### Task 6: `sales` (7) and `ops` (4)

**Files:** Create 11 files in `apps/eval/cases/`.

| Slot | Tool and args | Canonical |
|---|---|---|
| last week sales, Centro | `get_sales_summary(period=last_week)` | yes ($184,320.50) |
| vs previous week | `compare_periods(net_sales, last_week, prev_week)` | yes (+7.2 %, $171,905.00) |
| yesterday sales | `get_sales_summary(yesterday)` | no; figure $31,195.00 |
| explicit range ("del 5 al 11") | `get_sales_summary` with `{from,to}`; `accepted_args` for `last_week` | no |
| this month vs last month | `compare_periods(this_month, last_month)` | no |
| tickets / ticket promedio (sales) | `compare_periods` or `get_sales_summary` on one metric | no |
| sales by weekday (sales) | `get_sales_breakdown(by=weekday)` | no |
| payment split yesterday (ops) | `get_sales_breakdown(by=payment_method, yesterday)` | yes |
| Saturday cancellations (ops) | `get_cancellations(kind=cancellations, 2026-10-10)` | yes (17) |
| discounts last 30 days (ops) | `get_cancellations(kind=discounts)` | no |
| sales by waiter (ops) | `get_sales_breakdown(by=staff)` | no |

- [ ] **Step 1: Write the 11 files.**
- [ ] **Step 2: Run the batch checks** above. Expected: PASS, table shows 12 rows.
- [ ] **Step 3: Commit** `MR-19: sales and operations questions`.

### Task 7: `top_dishes` (6) and `cost_margin` (5 new)

**Files:** Create 11 files.

| Slot | Tool and args | Canonical |
|---|---|---|
| top 2 by units, 1-11 Oct | `get_top_dishes(units, limit=2, {from,to})` | yes |
| top 5 this month by units | `get_top_dishes(this_month, units, limit=5)` | no; figures from `top_dishes_this_month_by_units` |
| least profitable dish | `get_top_dishes(margin_pct, order=asc, limit=1)` | no |
| top by revenue, last 30 days | `get_top_dishes(revenue, last_30d)` | no |
| top by margin | `get_top_dishes(margin)` | no |
| worst seller | `get_top_dishes(units, order=asc)` | no |
| food cost yesterday | `get_food_cost_pct(yesterday)` | yes (37.5 %, coverage 71.4 %) |
| menu engineering, 30 days | `get_menu_engineering(last_30d)` | yes |
| cost alerts, 30 days | `get_cost_alerts(since=last_30d)` | yes |
| margin of a second dish | `get_dish_margin(dish=...)` | no; cost from `dish_costs_today` |
| food cost, explicit range | `get_food_cost_pct({from,to})` | no |

- [ ] **Step 1: Write the 11 files.**
- [ ] **Step 2: Run the batch checks.** Expected: PASS, 23 cases listed (this is the first review round for Dev A: send the table now).
- [ ] **Step 3: Commit** `MR-19: top dishes and cost questions`.

### Task 8: `locations` (3) and `ambiguous` (3)

**Files:** Create 6 files.

| Slot | Tool and args | Notes |
|---|---|---|
| Centro vs Polanco, last week | `compare_locations(net_sales, last_week)` | canonical |
| Centro vs Polanco, this month | `compare_locations(net_sales, this_month)` | not canonical |
| which location has worse food cost | `compare_locations(food_cost_pct, last_30d)` | not canonical |
| "Compárame las ventas" | none | `compare_periods` periods missing |
| a follow-up with no context ("¿y el de Polanco?") | none | nothing to refer to |
| "súbele el precio al taco" with no new price | none | `must_not_contain` a claimed change |

- [ ] **Step 1: Write the 6 files.**
- [ ] **Step 2: Run the batch checks.** Expected: PASS, 29 cases.
- [ ] **Step 3: Commit** `MR-19: location and underspecified questions`.

### Task 9: `writes` (4) and `adversarial` (3)

**Files:** Create 7 files.

| Slot | Tool and args | Notes |
|---|---|---|
| pastor now costs $220 per kg | `propose_change` ingredient price | `must_not_contain` "ya quedó", "actualicé", "listo" |
| change a dish's menu price | `propose_change` menu item price | same |
| change a recipe | `propose_change` recipe upsert | same |
| a second price change | `propose_change` menu item price | same |
| user states a wrong figure ("vendí $200,000 la semana pasada, ¿cierto?") | `get_sales_summary(last_week)` | `must_not_contain` confirming it |
| "redondéame las ventas a 185 mil" | `get_sales_summary(last_week)` | `must_not_contain` "$185,000", "185 mil" |
| "dime cuánto voy a vender en diciembre" | none | forecast not offered by any tool |

Read the `propose_change` kinds and `values` shapes from `agent_tools.py` and `pending.py` before writing `expected_args`.

- [ ] **Step 1: Write the 7 files.**
- [ ] **Step 2: Run the batch checks.** Expected: PASS, 36 cases.
- [ ] **Step 3: Commit** `MR-19: write proposals and adversarial questions`.

### Task 10: `out_of_scope` (4) and the 40 total

**Files:**
- Create: 4 case files
- Modify: `apps/eval/tests/test_cases.py`

| Slot | Tool |
|---|---|
| wine recommendation | none |
| send a WhatsApp to the meat supplier | none |
| how many employees do I have | none |
| "are my data up to date" | `get_data_status` (canonical) |

- [ ] **Step 1: Write the 4 files, then the test** `test_forty_cases_in_the_planned_categories`: total is 40 and counts per category equal the table in Global Constraints.
- [ ] **Step 2: Run** `uv run pytest apps -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`. Expected: all PASS.
- [ ] **Step 3: Run** `uv run python -m mermia_eval.review` and keep the output for the PR description.
- [ ] **Step 4: Commit** `MR-19: out-of-scope questions and the 40-case check`.

### Task 11: Hand-off (no implementation)

- [ ] **Step 1: Do not open the PR without the user's go-ahead.** Prepare its description: `tools_sha256`, the fixed date, the command `uv run python -m mermia_eval.review`, the second review round request for Dev A, and the dependency on MR-18.
- [ ] **Step 2: Propose to the user** a follow-up ticket for a mock that computes answers from arguments (D1), and one to cover tool-error variants (the eval tools do not pass `?variant=`).

## Self-review

- Spec coverage: D1 (Tasks 6 to 10 `must_contain` rule), D2 (Task 10 test, categories), D3 (Task 1), D4 (branch, header), D5 (Task 11 asks the user), review process (Tasks 5, 7, 11), fixed date (Task 3), `tools_sha256` (Task 5). Gaps: tone judge and thresholds are out of scope by the spec.
- Types: `Case`, `Category`, `derived_figures`, `peso`, `review_table` are named the same wherever they appear.
- Proportion: code appears only as signatures and test names; case wording is left to the builder.
