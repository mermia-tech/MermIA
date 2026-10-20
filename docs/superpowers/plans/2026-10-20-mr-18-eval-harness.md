# MR-18 LLM eval harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `uv run mermia-eval` asks one Mexican-Spanish question to every configured model through Agno, scores tool / args / numbers, and records each run in Langfuse.

**Architecture:** A new uv workspace member `apps/eval`. Small modules, no framework of our own: config (models, prices, prompt), case loader, pure scorer, Agno tool builder, one-run function, Langfuse tracing, CLI. The 12 C4 tools reach Agno unchanged and run against the Mock RPC in-process.

**Tech Stack:** Python 3.12, Agno 3.1.6 (pinned), OpenInference + OpenTelemetry (Langfuse via OTLP), pydantic, `mermia-contracts`, `mermia-mock-rpc`, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md` (decisions D1-D10, calls 1-7, Agno facts in §4).

## Global Constraints

- Agno pinned to `agno==3.1.6`. Tools: `Function(parameters=<C4 input_schema>, skip_entrypoint_processing=True)`, never `strict=True`.
- Models (D2): `openai:gpt-5.6-luna`, `openai:gpt-6.1-sol`, `anthropic:claude-haiku-5-5`, `anthropic:claude-sonnet-5-5`, `google:gemini-3.8-flash`, `google:gemini-3.5-flash-lite`.
- Same low reasoning for all, temperature unset (D7): OpenAI `reasoning_effort="low"`, Gemini `thinking_level="low"`, Claude default.
- Scores are separate, no composite, no thresholds, no tone (D3, D4). Runs default 1 (`--runs`, D9).
- Prices USD per million tokens (input / cached / output): Haiku 0.10/0.01/0.50; Sonnet 2.00/0.10/10.00; GPT-5.6 Luna 0.20/0.02/1.20; Gemini 3.8 Flash 0.75/0.075/3.75; Gemini 3.5 Flash-Lite 0.30/0.03/2.50; `gpt-6.1-sol` unknown (`None`, printed `n/a`).
- Langfuse env: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`. Provider keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`. Never print or log values.
- Code, comments, docs in English; the question and the system prompt in Mexican Spanish. ruff line 100, mypy strict (relax per module only where Agno is untyped).
- Tests run offline. No commits are made by this plan; the user decides when.

## Review Focus

- A provider failure (no credit, bad key, unknown model) is reported as `error`, never scored as a wrong answer, and the other models still run. Pinned in Task 5 and Task 7.
- The model makes no tool call: tool, args and numbers all score 0. Task 3.
- `null` and omitted arguments are the same. Task 3.
- Number formats: `$37.63`, `37.63`, `67.2%`, `67.2 %`, `1,840` compare equal after normalising. Task 3.
- Agno must not alter the tool schemas (the `required` wipe found in the spike). Task 4.
- Langfuse keys missing: the harness runs without tracing and says so. Task 6.
- A model with no price prints `n/a`, not a crash. Task 7.

---

### Task 1: Package skeleton and config

**Files:**
- Create: `apps/eval/pyproject.toml`, `apps/eval/src/mermia_eval/__init__.py`, `apps/eval/src/mermia_eval/config.py`, `apps/eval/tests/test_config.py`
- Modify: `pyproject.toml` (add `apps/eval/src` to `mypy_path`), `uv.lock` (via `uv sync`)

**Interfaces:**
- Produces: `Price(input: float, cached: float, output: float)` and `ModelSpec(id: str, price: Price | None)` frozen dataclasses; `MODELS: Final[tuple[ModelSpec, ...]]`; `SYSTEM_PROMPT: Final[str]`; `build_model(spec_id: str) -> Any` returning the Agno model instance with the low-reasoning options of Global Constraints.

- [ ] **Step 1: Write the failing test** `test_models_are_provider_colon_id` (every `ModelSpec.id` matches `^(openai|anthropic|google):\S+$` and the six ids of Global Constraints are present), `test_only_gpt_6_1_sol_has_no_price`, `test_system_prompt_is_spanish_and_forbids_inventing_numbers` (contains "nunca inventes" and "propose_change"), `test_build_model_options` (`build_model("openai:gpt-5.6-luna").reasoning_effort == "low"`; Gemini `thinking_level == "low"`; Claude has no thinking set; an unknown provider raises `ValueError`).
- [ ] **Step 2: Run** `uv run pytest apps/eval/tests/test_config.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement.** `pyproject.toml` modelled on `apps/mock-rpc/pyproject.toml` (hatchling, `[tool.uv.sources]` workspace entries for `mermia-contracts` and `mermia-mock-rpc`), dependencies `agno==3.1.6`, `openai`, `anthropic`, `google-genai`, `httpx`, `openinference-instrumentation-agno`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, script `mermia-eval = "mermia_eval.cli:main"`. `config.py` holds the prices and the prompt of the spec §5. Run `uv sync --all-packages --all-groups`.
- [ ] **Step 4: Run** the same tests → PASS; `uv run mypy` shows no new errors (add per-module `ignore_missing_imports` overrides in the root `[tool.mypy]` only for modules mypy cannot type).

### Task 2: Cases

**Files:**
- Create: `apps/eval/src/mermia_eval/cases.py`, `apps/eval/cases/tacos_al_pastor.json`, `apps/eval/tests/test_cases.py`

**Interfaces:**
- Produces: `Case` (pydantic, `extra="forbid"`): `id: str`, `question: str`, `expected_tool: str`, `expected_args: dict[str, Any]`, `accepted_args: list[dict[str, Any]] = []`, `must_contain: list[str]`; `CASES_DIR: Final[Path]`; `load_cases(directory: Path = CASES_DIR) -> list[Case]` (sorted by file name).
- The case: question "¿Cuál es el margen de los tacos al pastor?", tool `get_dish_margin`, args `{"dish": "tacos al pastor"}`, must_contain `["$18.40", "$65.00", "$37.63", "67.2%"]`.

- [ ] **Step 1: Write the failing tests** `test_load_cases_returns_the_example`, `test_expected_args_validate_against_the_c3_model` (`RPCS[case.expected_tool].args.model_validate(case.expected_args)` for every case and accepted alternative), `test_must_contain_comes_from_the_mock_answer` (every figure appears in `mermia_mock_rpc.rpcs.build(case.expected_tool)` serialised with `json.dumps`), `test_unknown_field_is_rejected`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `cases.py` and the JSON file.
- [ ] **Step 4: Run** → PASS.

### Task 3: Scorer

**Files:**
- Create: `apps/eval/src/mermia_eval/score.py`, `apps/eval/tests/test_score.py`

**Interfaces:**
- Consumes: `Case` from Task 2.
- Produces: `ToolCall(name: str, args: dict[str, Any])` frozen dataclass; `score_tool(case: Case, calls: Sequence[ToolCall]) -> float`; `score_args(case: Case, calls: Sequence[ToolCall]) -> float`; `score_numbers(case: Case, reply: str, tool_results: Sequence[str]) -> float`. All return 0.0 or 1.0.

Rules (spec §5): tool = 1 if at least one call and every call is the expected tool; args = 1 if some call to the expected tool equals `expected_args` or an accepted alternative after dropping `None` values; numbers = 1 only if every number in `reply` appears in the tool results or the question and every `must_contain` figure is in `reply`. Numbers are compared as `Decimal` after removing `$`, `,`, `%` and spaces.

- [ ] **Step 1: Write the failing tests:** `test_tool_ok`, `test_tool_zero_when_no_call`, `test_tool_zero_when_other_tool_called`, `test_tool_repeated_expected_call_is_fine`, `test_args_null_equals_omitted` (`{"dish": "tacos al pastor", "location_id": None}` scores 1), `test_args_wrong_dish_is_zero`, `test_args_accepts_alternative`, `test_numbers_ok` (reply "El margen es $37.63 (67.2%), costo $18.40 y precio $65.00." with a tool result containing those figures), `test_numbers_zero_on_invented_figure` ("unos $40"), `test_numbers_zero_when_must_contain_missing`, `test_numbers_formats_are_equal` ("67.2 %" vs "67.2%", "37.63" vs "$37.63"), `test_numbers_zero_when_no_calls_and_figures_present`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** with one regex for numbers and `Decimal`. **Step 4: Run** → PASS.

### Task 4: Tools

**Files:**
- Create: `apps/eval/src/mermia_eval/tools.py`, `apps/eval/tests/test_tools.py`

**Interfaces:**
- Produces: `RpcCaller = Callable[[str, dict[str, Any]], str]`; `make_rpc_caller(base_url: str | None = None) -> RpcCaller` (None → in-process `fastapi.testclient.TestClient(mermia_mock_rpc.app.app)`, otherwise `httpx.Client(base_url=...)`; returns the response text); `build_tools(call: RpcCaller) -> list[Function]` (the 12 C4 tools in `tool_definitions()` order).

Each tool: `Function(name, description, parameters=<deep copy of input_schema>, entrypoint=<closure calling call(name, kwargs)>, skip_entrypoint_processing=True)`. `propose_change`'s entrypoint does not call the mock and returns `'{"status": "pending_approval"}'`.

- [ ] **Step 1: Write the failing tests:** `test_twelve_tools_in_c4_order`, `test_schemas_reach_agno_unchanged` (for each tool, after `process_entrypoint()`, `fn.parameters == tool_definitions()[i]["input_schema"]`; guards the `required` wipe), `test_required_is_kept` (`get_dish_margin` requires `["dish"]`), `test_read_tool_calls_the_mock` (`build_tools(make_rpc_caller())` entrypoint of `get_dish_margin` called with `dish="tacos al pastor"` returns text containing `$37.63`), `test_bad_arguments_return_the_mock_422_text` (an unknown argument does not raise), `test_propose_change_never_calls_the_mock` (a caller that raises is not invoked; result is the pending JSON).
- [ ] **Step 2-4:** run FAIL, implement, run PASS.

### Task 5: Run one case

**Files:**
- Create: `apps/eval/src/mermia_eval/run.py`, `apps/eval/tests/test_run.py`

**Interfaces:**
- Consumes: `Case`, `ToolCall`, `build_model`, `SYSTEM_PROMPT`, `Price`.
- Produces: `RunResult` dataclass (`model: str`, `calls: list[ToolCall]`, `tool_results: list[str]`, `text: str`, `input_tokens: int`, `output_tokens: int`, `cached_tokens: int`, `seconds: float`, `error: str | None`, `trace_id: str | None`); `run_case(model: str, case: Case, tools: list[Function], agent_factory: Callable[..., Any] = Agent) -> RunResult`; `cost_usd(result: RunResult, price: Price | None) -> float | None`.

`run_case` creates the agent with `build_model(model)`, `tools`, `instructions=SYSTEM_PROMPT`, `telemetry=False`; times the call with `time.perf_counter`; wraps it in an OpenTelemetry span `eval.run` and stores its trace id (None when tracing is off); maps `run_output.tools` to `calls`/`tool_results`; `error` is set when `run_output.status == RunStatus.error` or when the call raises (the exception text, truncated to 300 chars).

- [ ] **Step 1: Write the failing tests** with a fake agent factory returning a stub run output: `test_success_maps_calls_tokens_and_text`, `test_provider_error_status_sets_error` (status `RunStatus.error`, content = error text, 0 tokens → `error` set, `calls == []`), `test_exception_sets_error_and_does_not_raise`, `test_cost_uses_price_and_cached_split` (input 1000 with 400 cached at 0.20/0.02/1.20 and output 100 → exact value), `test_cost_none_without_price`.
- [ ] **Step 2-4:** FAIL, implement, PASS.

### Task 6: Langfuse tracing

**Files:**
- Create: `apps/eval/src/mermia_eval/tracing.py`, `apps/eval/tests/test_tracing.py`

**Interfaces:**
- Produces: `setup_tracing(env: Mapping[str, str]) -> TracerProvider | None` (None when any of the three Langfuse variables is missing; otherwise sets `OTEL_EXPORTER_OTLP_ENDPOINT=<base>/api/public/otel` and Basic auth header, installs `TracerProvider` with `SimpleSpanProcessor(OTLPSpanExporter())`, calls `AgnoInstrumentor().instrument(tracer_provider=...)`); `post_scores(env: Mapping[str, str], trace_id: str | None, scores: Mapping[str, float]) -> None` (REST `POST <base>/api/public/scores`, one request per score, Basic auth; no-op when `trace_id` is None; a failed post prints a warning and never raises).

- [ ] **Step 1: Write the failing tests:** `test_setup_returns_none_without_keys`, `test_endpoint_and_auth_header` (build helpers `_otlp_endpoint(base) == "https://x/api/public/otel"` and `_auth_header(pub, sec)` equals the base64 of `pub:sec`; assert no secret appears in `repr` of anything printed), `test_post_scores_noop_without_trace_id`, `test_post_scores_payload` (monkeypatch `httpx.post`; payload has `traceId`, `name`, `value`), `test_post_scores_swallows_http_errors`.
- [ ] **Step 2-4:** FAIL, implement, PASS. How scores are tagged on the trace (tags: run id, model, case id) is the builder's call; verify in Task 8 that they show in Langfuse.

### Task 7: CLI

**Files:**
- Create: `apps/eval/src/mermia_eval/cli.py`, `apps/eval/README.md`, `apps/eval/tests/test_cli.py`
- Modify: `pyproject.toml` (marker `eval` in `[tool.pytest.ini_options]`)

**Interfaces:**
- Consumes: everything above.
- Produces: `summarize(results: Sequence[RunResult], case: Case, prices: Mapping[str, Price | None]) -> list[dict[str, Any]]` (one row per model: `model`, `tool`, `args`, `numbers` as means over non-errored runs or `None`, `tokens_in`, `tokens_out`, `seconds`, `cost`, `runs`, `errors`); `format_table(rows) -> str` (cost `n/a` when None, scores `-` when every run errored); `main(argv: Sequence[str] | None = None) -> int`.

CLI: `mermia-eval [--runs N] [--models id,id] [--mock-url URL]`; loads the cases, runs every selected model `runs` times per case sequentially, scores non-errored runs, calls `post_scores`, prints the table, flushes the tracer provider before exit. Exit code 0 unless every run of every model errored (then 1). The "tracing off" warning is printed once.

- [ ] **Step 1: Write the failing tests:** `test_summarize_means_and_counts_errors`, `test_summarize_all_errors_has_no_scores`, `test_format_table_shows_na_cost`, `test_exit_code_is_zero_with_low_scores`, `test_exit_code_is_one_when_every_run_errors` (monkeypatch `run_case`), `test_models_filter_rejects_unknown_id`.
- [ ] **Step 2-4:** FAIL, implement, PASS. README: how to run, the env variables, how to add a model or a case.

### Task 8: Real run and full checks

**Files:** none new (fixes only).

- [ ] **Step 1:** `set -a; source .env; set +a; uv run mermia-eval --models openai:gpt-5.6-luna,google:gemini-3.5-flash-lite` → table with three scores, tokens, latency, cost; confirm in Langfuse (v2 observations, `fields=core,basic,usage,model`) that each run has a trace.
- [ ] **Step 2:** `uv run mermia-eval` with all six models → Claude rows show `errors=1` (no credit) and the other models still print; exit code 0.
- [ ] **Step 3:** if a model rejects the low-reasoning option, fix `build_model` for that provider only and add a test.
- [ ] **Step 4:** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` → all pass. Report every command and result.
