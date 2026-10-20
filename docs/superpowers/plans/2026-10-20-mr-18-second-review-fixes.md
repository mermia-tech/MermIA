# MR-18 second review fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the seven findings (H1-H7) of the second code review of `apps/eval`, each with a test that fails first.

**Architecture:** No new modules. The scorer's number extraction, the error plumbing between `run.py` and `cli.py`, the redaction helper and Agno's logger setup change in place.

**Tech Stack:** unchanged (Python 3.12, Agno 3.1.6, pytest, uv).

**Spec:** `docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md` (anti-goal: secrets never in output; provider or backend failures never scored as wrong answers). Earlier plans: `2026-10-20-mr-18-eval-harness.md`, `2026-10-20-mr-18-review-fixes.md`.

## Design (one decision per finding)

| Finding | Decision |
|---|---|
| H1 Agno logs errors to stdout, unredacted | `route_agno_logs(env)` in `cli.py`: one `logging.Logger` writing `LEVEL message` to **stderr** through a filter that applies `redact`; installed with `agno.utils.log.configure_agno_logging(custom_default_logger=..., custom_agent_logger=..., custom_team_logger=..., custom_workflow_logger=...)` at the start of `main`. Silencing was rejected: Agno's warnings (a failed tool call) are useful and cost nothing on stderr. |
| H2 nothing pins `backend.failures.clear()` | A test whose fake `run_case` appends a failure to the list it receives and records the list it saw at the start of each call. |
| H3 secret cut by the 300-character limit | `RunResult.error` keeps the full text (remove the three `[:300]` in `run.py`); `main` truncates after redacting. |
| H4 narrow redaction | `redact` also covers variable names containing PASSWORD, AUTH or CREDENTIAL, and the URL-encoded form (`urllib.parse.quote(value, safe="")`) of every secret value. Values shorter than 8 characters stay untouched. |
| H5 Ctrl-C loses the error summary | The stderr summary moves into the `finally` of `main` (after the tracer flush). |
| H6 number extraction | New pattern: optional sign (`-` or U+2212, only when not glued to a word or digit; `+` counts as no sign, so "+7.2%" equals "7.2%"), thousands groups only when not followed by another digit, leading-dot decimals (`.5`), digits glued to letters (`L1`, uuid pieces) are not numbers. List marker limited to 1-2 digits and to spaces/tabs, so "2026. El costo" keeps its figure. Dates in a reply that the tools did not return still score 0: that is the rule (every number comes from a tool or the question), now pinned by a test. A flipped sign ("+3.1%" vs "-3.1%") now fails. |
| H7 cost source (spec D10) | Decision: the local price table is the cost source; Langfuse's own cost is a cross-check, not read by the harness. Update the spec (D10, section 5, calls list) and the README. No code. |

Out of scope: the review's suggestions (all distinct errors, batch span processor, dependency bounds, final "N models failed" line, README note about real backends with `--mock-url`).

## Global Constraints

- Code, comments, docs in English. ruff line 100, mypy strict. No new dependencies.
- Tests offline. The only live command (Task 6) uses a fake key: no cost, no real secret.
- No commits unless the user asks.
- `redact` keeps the signature `redact(text: str, env: Mapping[str, str]) -> str`.

## Review Focus

- A secret straddling character 300 never prints a prefix (Task 2).
- Agno's own `ERROR` lines never reach stdout and never show a secret (Task 4).
- A run's failures do not leak into the next run or model (Task 3).
- A sign flip in a reply is caught; "+7.2%" still equals "7.2%" (Task 1).
- Existing scorer tests (list markers 1-9, "3,4", case-insensitive args) keep passing (Task 1).

---

### Task 1: Number extraction (H6)

**Files:**
- Modify: `apps/eval/src/mermia_eval/score.py`
- Test: `apps/eval/tests/test_score.py`

**Interfaces:** `score_numbers`, `score_args`, `score_tool` unchanged; `_numbers(text) -> set[Decimal]` keeps its name.

- [ ] **Step 1: Write the failing tests:** `test_numbers_sign_flip_fails` (tool result `"change": "-3.1%"`, reply "bajó +3.1%" → 0.0; reply "bajó -3.1%" and "bajó −3.1%" → 1.0; case with empty `must_contain`); `test_numbers_plus_sign_is_no_sign` (tool "+7.2%", reply "7.2%" → 1.0 and the reverse); `test_numbers_thousands_group_must_end_the_number` (reply "1,2345" read as {1, 2345}, so it fails against a tool result with only 12345); `test_numbers_leading_dot_decimal` (reply ".5" matches tool "0.5"); `test_numbers_ignore_digits_glued_to_letters` (reply "en la sucursal L7" scores 1.0 against tool data without 7); `test_numbers_zero_for_a_date_not_in_tool_data` (reply `+ " Al 2026-10-20."` → 0.0, tool data without that date); `test_numbers_date_from_tool_data_is_fine`; `test_list_marker_keeps_a_year_at_line_start` (reply "2026. El costo es $18.40" against a case whose `must_contain` is `["$18.40"]` and a tool result containing 2026 → 1.0, and with a tool result lacking 2026 → 0.0, proving 2026 was kept).
- [ ] **Step 2: Run** `uv run pytest apps/eval/tests/test_score.py -q` → the sign, glued-letters, thousands and year tests FAIL.
- [ ] **Step 3: Implement** in `score.py`: the pattern of the design table, `_numbers` builds `Decimal(sign + digits.replace(",", ""))` with U+2212 turned into `-`; `_LIST_MARKER = re.compile(r"(?m)^[ \t]*\d{1,2}[.)][ \t]+")`.
- [ ] **Step 4: Run** the whole file → PASS (old tests included).

### Task 2: Redaction (H3, H4)

**Files:**
- Modify: `apps/eval/src/mermia_eval/run.py`, `apps/eval/src/mermia_eval/cli.py`
- Test: `apps/eval/tests/test_run.py`, `apps/eval/tests/test_cli.py`

- [ ] **Step 1: Write the failing tests:** in `test_run.py` `test_error_is_not_truncated_in_the_result` (a `RuntimeError("x" * 400)` gives `len(result.error) == 400`; same for a `RunStatus.error` content and for a backend failure); in `test_cli.py` `test_secret_straddling_the_limit_is_not_printed` (env key `sk-secret-value-123456`, error `"x" * 295 + key + "tail"`; stderr has no `sk-sec`), `test_redact_covers_password_and_auth_names` (`DB_PASSWORD`, `AUTH_HEADER`, `MY_CREDENTIAL` with 8+ characters), `test_redact_covers_the_url_encoded_form` (value `abc/def+ghi123` and text containing `abc%2Fdef%2Bghi123`), `test_redact_leaves_short_values_and_other_names`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement:** remove the three `[:300]` in `run.py`; in `redact` extend the name list (`KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `AUTH`, `CREDENTIAL`) and replace both `value` and `quote(value, safe="")`; in `main` keep `' '.join(redact(error, env).split())[:300]`.
- [ ] **Step 4: Run** `uv run pytest apps/eval -q` → PASS.

### Task 3: Error summary on interrupt, and the `clear()` test (H5, H2)

**Files:**
- Modify: `apps/eval/src/mermia_eval/cli.py`
- Test: `apps/eval/tests/test_cli.py`

- [ ] **Step 1: Write the failing tests:** `test_failures_do_not_leak_into_the_next_run` (`--runs 2 --models LUNA,HAIKU`; the fake appends `"boom"` to `kw["failures"]` after recording `list(kw["failures"])`; all recorded starts equal `[]`; this fails if `clear()` is removed, check that by temporarily commenting it out and watching it fail, then restoring it); `test_error_summary_survives_ctrl_c` (first model returns `_failing` result, second raises `KeyboardInterrupt`; stderr has the first model's error line).
- [ ] **Step 2: Run** → the Ctrl-C test FAILS; the leak test passes now, so the temporary comment-out is the proof it can fail.
- [ ] **Step 3: Implement:** move the summary loop into the `finally` of `main`, after `provider.force_flush()`.
- [ ] **Step 4: Run** → PASS.

### Task 4: Agno logs to stderr, redacted (H1)

**Files:**
- Modify: `apps/eval/src/mermia_eval/cli.py`
- Test: `apps/eval/tests/test_cli.py`

**Interfaces:**
- Produces: `route_agno_logs(env: Mapping[str, str]) -> None`, called once at the top of `main` (after argument parsing).

- [ ] **Step 1: Write the failing tests** (a fixture saves and restores `agno.utils.log.logger`, `agent_logger`, `team_logger`, `workflow_logger` with `monkeypatch.setattr` so the global state is restored): `test_agno_errors_go_to_stderr_not_stdout` (after `route_agno_logs(env)`, `agno.utils.log.log_error("Error from OpenAI API: boom")`; `capsys`: stdout empty, stderr contains the message); `test_agno_log_lines_are_redacted` (env key `sk-secret-value-123456`; message contains it; stderr has `***` and not the key); `test_main_routes_agno_logs` (monkeypatch `cli.route_agno_logs` to record the env it received; `main` calls it once).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `route_agno_logs`: a `logging.Logger("mermia_eval.agno")` with level INFO, `propagate=False`, one `StreamHandler(sys.stderr)` (format `%(levelname)-7s %(message)s`) and a `logging.Filter` subclass whose `filter` rewrites `record.msg = redact(record.getMessage(), env)` and clears `record.args`; pass it as default, agent, team and workflow logger to `configure_agno_logging`.
- [ ] **Step 4: Run** `uv run pytest apps/eval -q` → PASS.

### Task 5: Cost source decision in the docs (H7)

**Files:**
- Modify: `docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md`, `apps/eval/README.md`

- [ ] **Step 1:** In the spec, rewrite D10's cost sentence to "cost comes from the local price table; Langfuse's own cost is a cross-check, not read by the harness", fix the "Cost" paragraph in section 5 to match, and add call 8 to section 7: "cost is not read from Langfuse (my call, reviewer finding)".
- [ ] **Step 2:** In the README, add one sentence under the cost line: Langfuse also computes a cost per trace and can price models the local table lacks.
- [ ] **Step 3:** `grep -n "Langfuse" docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md` shows no remaining sentence that says the harness reads the cost from Langfuse.

### Task 6: Verification

- [ ] **Step 1:** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv sync --locked --all-packages --all-groups` → all pass; report the counts.
- [ ] **Step 2 (no cost, fake key):** `OPENAI_API_KEY=sk-test-fake-key-123456 uv run mermia-eval --models openai:gpt-5.6-luna > /tmp/out.txt 2> /tmp/err.txt`. Expected: `/tmp/out.txt` holds only the table; `/tmp/err.txt` holds the error line and Agno's log lines; neither file contains `sk-test-fake-key-123456` or any line starting with `ERROR` in stdout. Delete both files afterwards.
- [ ] **Step 3:** repeat Task 4's real concern for Google with `GOOGLE_API_KEY=fake-google-key-123456` and the model `google:gemini-3.5-flash-lite`; same expectations.
