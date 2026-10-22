# MR-18 handoff: LLM eval harness

Written 2026-10-20 at the end of a long session, to continue in a fresh Claude Code session. Facts are tagged:

- **[VERIFIED]** checked in this session with a command or by reading the file.
- **[REPORTED]** stated by the user or by a review subagent; not independently re-run.
- **[HYPOTHESIS]** believed, not proven.
- **[PENDING]** work or decision not done.

General project information is in `CLAUDE.md` and `docs/`; it is not repeated here.

## 1. Project

MermIA is restaurant intelligence for Mexico (Phase 1: a WhatsApp agent fed by Soft Restaurant exports). Read `CLAUDE.md` first. What matters for this ticket:

- **Stack** [VERIFIED]: Python 3.12, uv workspace (`apps/*`, `packages/*`), ruff (line 100) and mypy strict, pytest. Agent tools are the C4 contract in `packages/contracts/src/mermia_contracts/agent_tools.py` (12 tools as JSON Schema, derived from the C3 RPC models in `rpc.py`). The Mock RPC (`apps/mock-rpc`) answers each read RPC with ONE fixed JSON per RPC, taken from `packages/contracts/tests/examples/rpc/`; the request values are not used.
- **Conventions** [VERIFIED, `CLAUDE.md`]: code and technical docs in English; anything customers see in Mexican Spanish; two devs; lean agent (backend RPCs do the work, the LLM brokers); DB writes need human approval.
- **Workflow skills** in `.claude/skills/`: `/check` (ruff, mypy, pytest, pgTAP), `/review` (built-in `/code-review`, then the `skeptic-reviewer` agent), `/start-ticket`. Hooks block edits to `.env` and run `ruff format` on edited Python files.

## 2. Current ticket

- **Id:** MR-18 "LLM eval harness", https://github.com/mermia-tech/MermIA/issues/18 (owner Dev B, Week 1 Day 3). Branch `MR-18-eval-harness`.
- **Original requirement** (issue body before this session): create a provider adapter for Anthropic, OpenAI and Google; write a scorer (right tool? right args? right numbers?); log each run in Langfuse; run one example question on all providers. Done when: one command runs a question on every provider and prints a score. Needs MR-13 (done) and MR-9; unlocks MR-20 (the model decision gate).
- **Agreed scope** (the issue body was rewritten on 2026-10-20 to match) [VERIFIED]: runner built on **Agno** instead of hand-written adapters; providers OpenAI and Google active, Anthropic kept in the config but without credit/key; three scores separate (tool, args, numbers) plus tokens, latency, cost; Langfuse trace per run with the scores attached; one example case in Mexican Spanish; command `uv run --env-file .env mermia-eval` in the new workspace member `apps/eval`.
- **Out of scope** (explicit): the 40 questions (MR-19), pass thresholds and the model decision (MR-20), the tone judge (MR-20), any composite score, CSV output, parallel execution, changing the `llm_route` DB enum, rewriting kickoff docs.
- **Other issues edited** [VERIFIED]: MR-9 (Anthropic account now optional; OpenAI, Google AI, Langfuse accounts), MR-20 (six models, thresholds from `docs/kickoff/13` §H3, tone judge as its own step), MR-27 ("cached prompt prefix" reworded to be provider-neutral).

## 3. Implementation state

**Done** [VERIFIED by tests and real runs]:
- `apps/eval` package: config (models, prices, prompt), case loader, pure scorer, Agno tool builder with a failure-tracking backend, one-run function, Langfuse tracing, CLI.
- Two rounds of fixes after two independent code reviews (9 defects A1-A9, then 7 findings H1-H7), each with a test written first.
- Real runs: `gpt-5.6-luna`, `gpt-6.1-sol`, `gemini-3.8-flash`, `gemini-3.5-flash-lite` answered the example case with tool/args/numbers = 1.00 in the successful runs; Langfuse showed the trace (AGENT, GENERATION, TOOL) and the three scores.

**Not done / pending:**
- **[PENDING] The commit.** Nothing is committed. The user answered "Sí, haz commit" and, in the next message, asked for this handoff with "do NOT commit for now". So the commit is still undone and the user's instruction at that point wins; ask again before committing.
- **[PENDING] Claude models were never run end to end.** `ANTHROPIC_API_KEY` is not in `.env` (the user's choice; the account also had no credit when tried). Claude rows show `err`. The Agno payload sent to Anthropic differs slightly from C4 (see §5) and has not been measured with Claude.
- **[PENDING] Review suggestions** deliberately not built: show all distinct errors, not only the first per model; `BatchSpanProcessor` instead of `SimpleSpanProcessor`; bound the unpinned direct dependencies (`openai`, `anthropic`, `google-genai`, `openinference-*`, `opentelemetry-*`); a final "N models failed" line; a README note that `--mock-url` pointing at a real backend sends real data to Langfuse.
- **[PENDING] Small doc nit:** `docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md` §4 item 7 says the OTLP endpoint is `<base>/api/public/otel`; the code uses `<base>/api/public/otel/v1/traces` (an explicit `endpoint=` needs the full path).
- **[PENDING] Not verified:** the OTLP exporter's own warnings with a wrong `LANGFUSE_BASE_URL` (could they print the URL or credentials?); real provider messages for every provider's bad-key case (OpenAI masks the key; Google does not repeat it; Anthropic untested).

## 4. Relevant files

All paths from the repo root.

| Path | Function |
|---|---|
| `apps/eval/pyproject.toml` | Workspace member `mermia-eval`; `agno==3.1.6` pinned; script `mermia-eval = mermia_eval.cli:main`. |
| `apps/eval/src/mermia_eval/config.py` | `MODELS` (six `provider:id` with `Price` or `None`), `SYSTEM_PROMPT` (Spanish), `build_model` (low reasoning: OpenAI `reasoning_effort="low"`, Gemini `thinking_level="low"`, Claude default). |
| `apps/eval/src/mermia_eval/cases.py` | `Case` (pydantic, `extra="forbid"`) and `load_cases()`. |
| `apps/eval/cases/tacos_al_pastor.json` | The one case: "¿Cuál es el margen de los tacos al pastor?" → `get_dish_margin`, `must_contain` `$18.40 $65.00 $37.63 67.2%`. |
| `apps/eval/src/mermia_eval/score.py` | `score_tool`, `score_args` (null = omitted, case-insensitive, recursive), `score_numbers` (every reply number must come from a tool result or the question; sign-aware; list markers stripped; `must_contain` required). |
| `apps/eval/src/mermia_eval/tools.py` | `Backend` (calls the mock in-process or at `--mock-url`; records network errors and HTTP >= 500 in `failures`), `make_rpc_caller`, `build_tools` (12 Agno `Function`s with `skip_entrypoint_processing=True`; `propose_change` is a stub returning `{"status": "pending_approval"}`). |
| `apps/eval/src/mermia_eval/run.py` | `RunResult`, `run_case` (provider error, exception or backend failure → `error`, never scored), `cost_usd`. |
| `apps/eval/src/mermia_eval/tracing.py` | `setup_tracing` (OpenInference + OTLP to Langfuse; sets the global tracer provider), `post_scores`. |
| `apps/eval/src/mermia_eval/cli.py` | `main`, `summarize`, `format_*`, `redact`, `route_agno_logs`. |
| `apps/eval/tests/` | 101 offline tests (`test_cases, test_cli, test_config, test_run, test_score, test_tools, test_tracing`). |
| `apps/eval/README.md` | Usage, env variables, how to add a model or a case. |
| `packages/contracts/src/mermia_contracts/agent_tools.py` | Only the module docstring changed (no longer says "Anthropic tool format"). |
| `pyproject.toml` (root) | One line added to `mypy_path`: `apps/eval/src`. `uv.lock` regenerated (+1075 lines). |
| `docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md` | The approved design (decisions D1-D10, scoring rules, calls 1-8). Authoritative. |
| `docs/superpowers/plans/2026-10-20-mr-18-eval-harness.md` | First implementation plan (7 tasks). |
| `docs/superpowers/plans/2026-10-20-mr-18-review-fixes.md` | Plan for review findings A1-A9. |
| `docs/superpowers/plans/2026-10-20-mr-18-second-review-fixes.md` | Plan for review findings H1-H7. |
| `docs/kickoff/13-llm-and-token-strategy.md` | Original eval design, prices (§H1), pass thresholds (§H3). Some figures are stale (see §6). |

## 5. Technical decisions

Decisions come from the user unless marked *(my call)*.

- **Framework: Agno 3.1.6, models as `provider:model_id` strings.** Discarded: LiteLLM (no longer needed once Agno was chosen), LangChain (too much abstraction), PydanticAI (the user chose Agno), Inspect AI and Promptfoo (heavier or Node), three hand-written SDK adapters (more code, risk of biased adapters).
- **Models (config):** `openai:gpt-5.6-luna`, `openai:gpt-6.1-sol`, `anthropic:claude-haiku-5-5`, `anthropic:claude-sonnet-5-5`, `google:gemini-3.8-flash`, `google:gemini-3.5-flash-lite`. IDs checked against the three accounts on 2026-10-19/20.
- **Scores separate, no composite, no thresholds, no tone** in MR-18; MR-20 takes thresholds from kickoff 13 §H3.
- **Same low reasoning for every provider, temperature unset** (kickoff 13 said temperature 0; changed because some reasoning models reject it).
- **Tools reach Agno unchanged.** Spike finding: with an `entrypoint(**kwargs)` Agno empties `required` on all 12 tools; `skip_entrypoint_processing=True` keeps them identical to C4. `strict=True` rejected (makes optional parameters required). Agno still adds `"description": ""` per property and `"required": []` for Anthropic (about 620 extra characters over 12 tools): accepted and documented, not measured against the 125-tokens-per-tool budget.
- **Mock runs in-process** (FastAPI `TestClient`), `--mock-url` for a running one *(my call, approved)*. Cases are JSON, not YAML *(approved)*. `propose_change` is a recording stub, not Agno's confirmation flow *(approved)*.
- **Numbers rule** is kickoff 13's: every number in the reply must appear in a tool result or the question, plus the `must_contain` figures. Kickoff 13's 71.7 % margin is stale: the mock serves 67.2 %.
- **Errors are never scores.** A provider failure, an exception, Agno's error-as-answer (`RunStatus.error`) or a backend failure (network, HTTP 5xx) makes the run `error`; a 422 (bad arguments) is the model's fault and is scored. Exit code is 0 unless every run errored.
- **Cost from the local price table** (changed from the original D10 after review). Cached tokens: OpenAI and Gemini input includes them, Anthropic's does not. Google thinking tokens are added to output for `google:` models. `gpt-6.1-sol` has no verified price (`n/a`).
- **Case-insensitive argument comparison** (user decision, review finding A8).
- **Agno's logger is rerouted to stderr with redaction** (silencing was rejected: its warnings are useful). `redact` hides values of variables whose name contains KEY, SECRET, TOKEN, PASSWORD, AUTH or CREDENTIAL (values of 8+ characters, plus URL-encoded form); errors are truncated after redaction.
- **Rows print as each model finishes; the error summary is printed in a `finally`.**

## 6. Research

- **Graphify** [VERIFIED]: it was NOT used in this session. `graphify-out/GRAPH_REPORT.md` is dated 2026-10-18 (940 nodes), before `apps/eval` existed, and has 0 mentions of `apps/eval` or `mermia_eval`. Its god nodes that matter here exist in the code/docs as the graph says: `RowModel` (`packages/contracts/src/mermia_contracts/db/types.py:33`), and the docs `09-architecture.md`, `08-mvp-4-week-plan.md`, `13-llm-and-token-strategy.md`. The graph cannot answer questions about MR-18 until it is rebuilt; ask the user before running it (`/graphify`).
- **Agno 3.1.6** [VERIFIED from its source in a throwaway venv]: `Function(parameters=<schema>, entrypoint=fn)`; entrypoint is called with `**arguments`; `ToolExecution` has `tool_name`, `tool_args`, `result`; `RunMetrics` has input/output/cache-read/reasoning tokens, duration; `metrics.cost` is only filled by `OpenAIChat` when the provider returns it, so it was `None` in all our runs; Gemini conversion resolves `$defs`/`anyOf`; Agno swallows tool exceptions (returns them to the model as text) and returns provider errors as the answer text with zero tokens.
- **Langfuse** [VERIFIED]: US cloud. Traces arrive through OTLP at `<base>/api/public/otel/v1/traces` with Basic auth. Scores post to `/api/public/scores`; reading uses `/api/public/v2/observations` and `/api/public/v3/scores` (the old traces/v2-scores read endpoints return 410). Langfuse prices known models itself.
- **Behaviours seen in real runs** [VERIFIED]: OpenAI sends `location_id: null`, Gemini omits it (handled: null = omitted). `gpt-5.6-luna` is non-deterministic: one run scored numbers = 0 because it omitted `$18.40` and `$65.00` (the case requires them), two others scored 1. Gemini runs took 20-67 s and twice returned Google-side errors (`INTERNAL`, `503 UNAVAILABLE`); this is not caused by `thinking_level="low"` (checked), and Gemini reported 0 thinking tokens on the example, so the thinking-token cost fix (A3) is tested with exact numbers but its real effect was not observed. Gemini input tokens were about 47 % higher than OpenAI's for the same tools.
- **Kickoff 13 vs what was built** [VERIFIED]: kickoff proposes a weighted composite, a tone judge, temperature 0 and `questions.yaml`; we chose separate scores, no tone (MR-20), provider-default temperature and JSON.

## 7. Tests

Commands run at the time of writing (2026-10-20) from the repo root [VERIFIED]:

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 127 files already formatted |
| `uv run mypy` | Success: no issues found in 84 source files |
| `uv run pytest apps/eval -q` | 101 passed |
| `uv run pytest` | 1165 passed, 55 skipped (DB/REST/token tests need services or keys) |
| `uv sync --locked --all-packages --all-groups` | Checked 89 packages (lock consistent) |

- Real runs used `uv run --env-file .env mermia-eval ...`. Fake-key runs (no cost, no real secret) confirmed stdout holds only the table, no `ERROR` lines on stdout, and neither fake key appears in stdout or stderr.
- Mutation checks done once by hand and restored: removing the new truncation order and removing `backend.failures.clear()` each made its test fail.
- **Known errors / limits:** Claude rows are `err` (no key); Gemini intermittently errors or is slow; a single run per model is noise (luna scored 0 and 1 on the same case); dates in a reply that the tools did not return score `numbers = 0` (by the rule). Review items not fixed: the suggestions in §3.
- **No live pytest tests** exist (a plan idea, dropped): verification against real providers is manual.

## 8. Git

State checked 2026-10-20 [VERIFIED]:

- Branch `MR-18-eval-harness`, created from `origin/main` at `f291efa` ("MR-15 Parser for the 'Productos vendidos' report (#58)"). It has **no commits of its own** (0 ahead, 0 behind `origin/main` as of the last `git fetch` in this session), **no upstream**, no stash.
- Modified, tracked: `packages/contracts/src/mermia_contracts/agent_tools.py` (docstring), `pyproject.toml` (+1 line), `uv.lock` (+1075).
- Untracked: `apps/eval/` (whole package), the three plans and the spec listed in §4, and this handoff (`docs/handoffs/`). `.env` is gitignored (`.gitignore:13`).
- Nothing was pushed and no PR exists. The GitHub issues MR-9, 18, 20 and 27 were edited directly on GitHub (not part of git).

## 9. Constraints

- **Secrets:** never print or log values from `.env`; check variable NAMES only (use `grep -c "^NAME=" .env`). A hook blocks edits to `.env`; the user edits it. Names present now: `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`; `ANTHROPIC_API_KEY` is absent. Tool output in the previous session sometimes displayed `LANGFUSE` as `LANGUSAGE`; trust counts and exact checks, not eyeballing.
- **Contracts:** do not change `packages/contracts` (C3/C4) or the Mock RPC for MR-18. The tools must reach models exactly as `tool_definitions()` defines them.
- **No DB writes:** `propose_change` must never call the mock or write anything.
- **Do not alter:** the `llm_route` enum (`haiku`/`sonnet`) in `supabase/migrations/` and `db/models.py` (decided: after MR-20); the kickoff docs (rewrite after MR-20); `apps/mock-rpc`.
- **Conventions:** English code and docs; Spanish only for the question, the prompt and customer-facing text; ruff line 100; mypy strict; offline tests; no commits unless the user asks; `uv.lock` must be committed with the dependency change.
- **Paid calls:** real runs cost cents; run them only on purpose. Anthropic needs credit and a key before it can be tested.

## 10. Next step

Ask the user whether to commit now (they approved it, then paused it). If yes: stage `apps/eval/`, the four spec/plan files, `docs/handoffs/MR-18-handoff.md`, `packages/contracts/src/mermia_contracts/agent_tools.py`, `pyproject.toml`, `uv.lock`; commit on `MR-18-eval-harness`. Then run `/check`, then `/review` (built-in `/code-review`, then the `skeptic-reviewer` agent), then open the PR to `main`.

## 11. Instructions to continue

Verify first:
1. `git status -sb` and `git fetch && git rev-list --left-right --count origin/main...HEAD` (is `origin/main` still `f291efa`? rebase or merge decisions come from the user).
2. `uv sync --locked --all-packages --all-groups && uv run pytest apps/eval -q` (expect 101 passed) and the table in §7.
3. `grep -c "^NAME=" .env` for the six names (never print values).

Do not repeat:
- The Agno spike, the model-ID discovery, the Langfuse setup and the two code reviews; their results are in this document and in the specs/plans. The throwaway venv used for the spike lived in the old session's scratch directory and is gone; use the repo's `.venv` (Agno is a normal dependency now).
- Do not re-litigate the framework, the model list, the scoring design or the cost source (all decided).
- Do not implement the §3 suggestions unless the user asks. If they do: brainstorm, then write a plan, then wait for approval, which is the workflow this session used.

Style: the user asked for short, step-by-step answers (the `/i-have-adhd` skill was active; re-invoke it if wanted) and for Superpowers flow plus Ponytail simplicity for implementation; they review plans before any code is written.
