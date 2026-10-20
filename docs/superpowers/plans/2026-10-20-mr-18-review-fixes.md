# MR-18 review fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the nine defects (A1-A9) confirmed by the code review of `apps/eval`, each with a test that fails first.

**Architecture:** Same modules as the first plan; no new files. Scorer, cost, tool backend, CLI argument handling and CLI output change in place.

**Tech Stack:** unchanged (Python 3.12, Agno 3.1.6, pytest, uv).

**Spec:** `docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md` (the anti-goal "a provider or backend failure is never scored as a wrong answer" is what A1 and A2 restore). First plan: `docs/superpowers/plans/2026-10-20-mr-18-eval-harness.md`.

## Design (decisions for each defect)

| Defect | Decision |
|---|---|
| A1 backend down scored as wrong answer | Tool calls to the mock record infrastructure failures (connection or timeout error, HTTP status >= 500, or any exception while calling) in a list; `run_case` turns a non-empty list into `error`. A 422 (bad arguments) is the model's fault and still counts against it. |
| A2 errors never shown | After the table, one line per model on stderr: `model: <first error>`, cut to 300 characters, with the values of the secret environment variables (names containing KEY, SECRET or TOKEN) replaced by `***`. |
| A3 Gemini cost too low | `RunResult.reasoning_tokens`; `cost_usd` adds them to the output tokens for `google:` models only (OpenAI's output count already includes reasoning). |
| A4 numbered list marker scored as invented number | Strip `^\s*\d+[.)]\s+` from each line of the reply before extracting numbers (reply only, not tool results). |
| A5 comma misread in lists | A comma is a thousands separator only before exactly three digits. |
| A6 `--runs 0` | Rejected by argparse with a message (integer >= 1). |
| A7 `--models ""` runs everything | Ids are stripped of spaces; an empty id is rejected. |
| A8 case-sensitive arguments | **User decision:** compare argument strings in lower case on both sides (recursively through dicts and lists). |
| A9 Ctrl-C loses everything | Print the header once and each model's row as soon as that model finishes its runs. |

Not in this plan: the review's suggestions (span error status, https check, batch span processor, dependency bounds, Anthropic cache-write cost). They stay noted, not built.

## Global Constraints

- Code, comments, docs in English. ruff line 100, mypy strict. No new dependencies.
- Tests offline. The only paid call is Task 7, step 2 (one OpenAI and one Gemini run).
- No commits unless the user asks.
- `Case.must_contain` / `expected_args` stay as they are; the lower-case rule applies only at comparison time.

## Review Focus

- A secret value must never reach stdout or stderr through the new error lines (Task 6 test).
- A real model mistake (wrong arguments, 422) must still be scored, not turned into `error` (Task 3 test).
- `--models` with spaces around ids and `--runs` as text, not just numbers (Task 4).
- An interrupted run keeps the rows already printed (Task 5).
- The number rule stays strict: an invented number inside a sentence still gives 0 after the marker stripping (Task 1).

---

### Task 1: Scorer (A4, A5, A8)

**Files:**
- Modify: `apps/eval/src/mermia_eval/score.py`
- Test: `apps/eval/tests/test_score.py`

**Interfaces:** unchanged signatures (`score_tool`, `score_args`, `score_numbers`).

- [ ] **Step 1: Write the failing tests:** `test_numbers_ignore_list_markers` (parametrised over 1..9: `f"{n}. " + REPLY` scores 1.0 against `ANSWER`; also `"2) "` and `"  3. "`); `test_numbers_marker_strip_keeps_invented_figures` (`"1. Unos $40 de utilidad"` still 0.0); `test_numbers_comma_only_before_three_digits` (reply "3,4 y 5" read as 3, 4, 5; `"$1,840.00"` read as 1840; assert through `score_numbers` with a tool result containing 3, 4, 5 and a case whose `must_contain` is empty); `test_args_ignore_case` (`{"dish": "Tacos Al Pastor"}` scores 1.0) and `test_args_case_insensitive_inside_nested_values` (alternative with `{"period": {"from": "2026-10-05", "to": "2026-10-11"}}` vs upper-case keys' values).
- [ ] **Step 2: Run** `uv run pytest apps/eval/tests/test_score.py -q` → the new tests FAIL (marker 7 gives 0.0; "Tacos Al Pastor" gives 0.0; "3,4" reads 34).
- [ ] **Step 3: Implement.** In `score.py`: number pattern `\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?`; in `score_numbers` apply `re.sub(r"(?m)^\s*\d+[.)]\s+", "", reply)` before `_numbers`; `_clean` also lower-cases strings recursively (`_norm(value)`: str → lower, dict → mapped, list → mapped, other → unchanged), applied to both expected and actual.
- [ ] **Step 4: Run** the same file → all PASS (old tests included).

### Task 2: Cost with thinking tokens (A3)

**Files:**
- Modify: `apps/eval/src/mermia_eval/run.py`
- Test: `apps/eval/tests/test_run.py`

**Interfaces:**
- Produces: `RunResult.reasoning_tokens: int` as a new field **after `cached_tokens`** and before `seconds` (update every constructor call in tests: `test_run.py::_result`, `test_cli.py::_ok/_err`).
- `run_case` fills it from `out.metrics.reasoning_tokens`.

- [ ] **Step 1: Write the failing tests:** `test_cost_adds_thinking_tokens_for_google` (`google:gemini-3.5-flash-lite`, input 0, output 1_000_000, reasoning 500_000, `Price(0.30, 0.03, 2.50)` → `1.5 * 2.50 = 3.75`); `test_cost_ignores_reasoning_tokens_for_openai` (same numbers on `openai:gpt-5.6-luna` → output only); `test_success_maps_reasoning_tokens` (`RunMetrics(reasoning_tokens=42)` → `result.reasoning_tokens == 42`).
- [ ] **Step 2: Run** → FAIL (no such field).
- [ ] **Step 3: Implement** the field, the mapping in `run_case`, and in `cost_usd`: `output = result.output_tokens + (result.reasoning_tokens if result.model.startswith("google:") else 0)`.
- [ ] **Step 4: Run** `uv run pytest apps/eval -q` → PASS.

### Task 3: Backend failures become `error` (A1)

**Files:**
- Modify: `apps/eval/src/mermia_eval/tools.py`, `apps/eval/src/mermia_eval/run.py`, `apps/eval/src/mermia_eval/cli.py` (wiring only)
- Test: `apps/eval/tests/test_tools.py`, `apps/eval/tests/test_run.py`, `apps/eval/tests/test_cli.py` (fakes accept the new argument)

**Interfaces:**
- Produces: `class Backend` in `tools.py` — callable `(name: str, args: dict[str, Any]) -> str` (so `build_tools(call: RpcCaller)` is unchanged) with attribute `failures: list[str]`; `make_rpc_caller(base_url: str | None = None) -> Backend`.
- `run_case(model, case, tools, agent_factory=Agent, failures: Sequence[str] = ())`: after the call, if `failures` is non-empty and no error is set yet, `error = "tool backend failed: " + failures[0]` (cut to 300 characters).
- `cli.main` creates one backend, clears `backend.failures` before each run and passes `failures=backend.failures`.

- [ ] **Step 1: Write the failing tests:** `test_unreachable_backend_records_a_failure` (`make_rpc_caller("http://127.0.0.1:1")("get_dish_margin", {"dish": "x"})` returns text, does not raise, and `failures` has one entry); `test_server_error_status_is_a_failure` (a handler returning 500 via `httpx.MockTransport` injected through a `client=` keyword of `make_rpc_caller`, or by monkeypatching its `post`); `test_422_is_not_a_failure` (bad argument name → `failures == []`); `test_run_case_turns_backend_failures_into_error` (`failures=["ConnectError"]` with an otherwise successful fake run → `error` starts with "tool backend failed"); `test_run_case_keeps_a_422_as_a_scored_run` (empty `failures` → `error is None`). Update the fakes in `test_cli.py` to `lambda model, case, tools, **kw: ...`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `Backend.__call__` wraps the post in try/except Exception, appends `f"{type(e).__name__}: {e}"` to `failures` and returns that text; a status >= 500 appends `f"HTTP {status}"` and returns the response text. Keep in-process default. Wire `cli.main`.
- [ ] **Step 4: Run** `uv run pytest apps/eval -q` → PASS.

### Task 4: Argument validation (A6, A7)

**Files:**
- Modify: `apps/eval/src/mermia_eval/cli.py`
- Test: `apps/eval/tests/test_cli.py`

**Interfaces:** `main(argv)` unchanged.

- [ ] **Step 1: Write the failing tests:** `test_runs_must_be_at_least_one` (`"0"`, `"-2"`, `"abc"` each raise `SystemExit` with code 2); `test_empty_models_is_rejected` (`--models ""` → `SystemExit` 2, and `run_case` is never called); `test_models_are_stripped` (`"openai:gpt-5.6-luna, google:gemini-3.8-flash"` runs both, with `run_case` faked).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** a `_positive_int(text: str) -> int` argparse `type=`; split `--models` on commas, strip each id, reject empty ids through `parser.error`.
- [ ] **Step 4: Run** → PASS.

### Task 5: Print each row as it finishes (A9)

**Files:**
- Modify: `apps/eval/src/mermia_eval/cli.py`
- Test: `apps/eval/tests/test_cli.py`

**Interfaces:**
- Produces: `format_header() -> str` and `format_row(row: Mapping[str, Any]) -> str`; `format_table(rows)` stays and equals header plus rows joined by newlines (existing test keeps passing).

- [ ] **Step 1: Write the failing tests:** `test_rows_are_printed_as_each_model_finishes` (fake `run_case` raises `KeyboardInterrupt` for the second model; `pytest.raises(KeyboardInterrupt)`; captured stdout contains the header and the first model's row); `test_format_table_is_header_plus_rows` (equals `format_header() + "\n" + "\n".join(format_row(r) ...)`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Split `format_table`; in `main` print the header once, then after each model's runs for a case call `summarize` on that model's results and print `format_row(...)` with `flush=True`. Keep the exit-code rule and the final `force_flush` in a `finally`.
- [ ] **Step 4: Run** → PASS.

### Task 6: Error lines on stderr, Langfuse warning test (A2)

**Files:**
- Modify: `apps/eval/src/mermia_eval/cli.py`, `apps/eval/README.md`
- Test: `apps/eval/tests/test_cli.py`

**Interfaces:**
- Produces: `redact(text: str, env: Mapping[str, str]) -> str` (replaces every value of an env var whose name contains KEY, SECRET or TOKEN and whose value is at least 8 characters with `***`); `main` prints `f"{model}: {redact(first_error, env)[:300]}"` to stderr, once per model that had an error, after the table.

- [ ] **Step 1: Write the failing tests:** `test_redact_hides_secret_values` (env `{"OPENAI_API_KEY": "sk-abcdef123456"}`; text containing the value → `***`; a short value and a non-secret name are left alone); `test_errors_are_listed_once_per_model_on_stderr` (two errored runs of one model → one line `model: no credit`; stdout has no error text); `test_error_line_never_contains_a_secret` (monkeypatched env with a key; fake error text includes it; stderr has `***` and not the key); `test_missing_langfuse_variables_print_a_warning` (patch `setup_tracing` to `None`; stderr contains "LANGFUSE").
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `redact` and the stderr lines in `main`. README: one sentence saying errors are listed on stderr and `--runs` must be >= 1.
- [ ] **Step 4: Run** → PASS.

### Task 7: Full verification and live confirmation

**Files:** none (fixes only if something fails).

- [ ] **Step 1:** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` → all pass; report every result.
- [ ] **Step 2 (two paid calls):** `uv run --env-file .env mermia-eval --models openai:gpt-5.6-luna,google:gemini-3.5-flash-lite`. Expected: both rows print as they finish; Gemini's `usd` is now higher than the earlier `0.00216` when it used thinking tokens; print `reasoning_tokens` from a one-off script run to confirm the premise that Gemini reports them.
- [ ] **Step 3:** `uv run --env-file .env mermia-eval` (all six). Expected: Claude rows show `err=1` and the cause on stderr; `ANTHROPIC_API_KEY` value never appears.
- [ ] **Step 4:** `uv run mermia-eval --mock-url http://127.0.0.1:1 --models openai:gpt-5.6-luna` → the run is `err` with "tool backend failed", not a 0 score (one paid call, only if the model reaches the tool).
