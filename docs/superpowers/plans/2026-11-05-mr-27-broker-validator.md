# MR-27: LLM broker loop and number validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Messages the router does not take are answered by an LLM that calls the 12 tools.
- No reply goes out with a figure no tool returned: one retry, then the menu.
- Every call is metered in `llm_usage`.
- Follow-ups use the last 4 turns.
- A burst of messages gets one answer.

**Architecture:**
- **Inside `apps/api/src/mermia_api/agent/`:**
  - a pure `validate()`;
  - a provider adapter `llm.py`, moved out of `apps/eval`;
  - a static prompt prefix with a per-request tail;
  - `LlmBroker`, which implements the MR-26 `Broker` protocol;
  - a `UsageStore` protocol with a Postgres implementation, for `llm_usage` and `conversation`;
  - a grouping front door that buffers per chat and calls `answer()` once per group.
- **`apps/eval` imports the validator and the adapter from `mermia-api`,** so the eval and production judge numbers the same way (spec Q2).

**Tech Stack:**
- **Already used:** Python 3.12, Agno 3.1.6 (`Agent`, `RunOutput`, `RunStatus`, `Function`), psycopg 3, pytest, `uv`.
- **Reused code:**
  - `mermia_contracts.agent` (C6), `mermia_contracts.agent_tools.tool_definitions()` (C4) and `mermia_contracts.rpc`;
  - the MR-26 `answer()`, `menu()` and `StubBroker`;
  - the MR-20 scorer, `build_model`, `cost_usd`, `setup_tracing` and the `agent_factory` test pattern (`apps/eval/tests/test_run.py`).

**Spec:** `docs/superpowers/specs/2026-11-05-mr-27-broker-validator-design.md` (approved 2026-11-05, Q1-Q6 proposals accepted). Branch `MR-27-broker-validator`, cut from `main` after MR-26's follow-up branch merges.

## Global Constraints

- **No change to `packages/contracts`, migrations or `apps/eval/cases/`.** Route label for LLM answers is `"haiku"` meaning "primary LLM route", with the real model in `llm_usage.model` (Q1).
- **Dependencies:**
  - New for `apps/api`: `agno==3.1.6`, `openai`, `anthropic`, `google-genai`, `openinference-instrumentation-agno`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`. These are exactly the eval's versions; nothing else.
  - `apps/eval` gains `mermia-api`.
- **The template path still imports no LLM SDK.** MR-26's subprocess test must stay green.
  - `LlmBroker` lives in `llm_broker.py`.
  - `broker.py` (imported by `agent/__init__.py`) keeps only the protocol and the stub.
  - Nothing under `agent/__init__.py` imports `llm.py` or `llm_broker.py`.
- **Tool calls run as the user (09 D8).** The `RpcCall` arrives with each call, never at construction, and tool arguments are validated against `RPCS[name].args` before the RPC.
- **Money is `Decimal`,** including `cost_usd` (CLAUDE.md: no floats).
- **Every figure in a sent reply passes `validate()`.** The broker never formats, sums or rounds money.
- **Any failure sends the template menu** (`menu(locations)`, as `StubBroker` builds it), never silence or an exception.
- **Tests:**
  - No test calls a real model or network. The model is faked through an `agent_factory`, as `run_case` does.
  - Helpers are pytest fixtures (`--import-mode=importlib`).
  - Each task starts with failing tests.
- **Language:** customer text is es-MX; code, comments, test names and logs are English.
- **Commits:** `MR-27: <what changed>`.

## Review Focus

- **A sent reply containing a figure with no source:** the one failure that matters.
- **Validator false positives** that would push correct answers to the menu: dates, times, list markers, value-equal formats.
- **A path that ends in an exception or silence** instead of the menu.
- **Tenant data or a date leaking into the static prefix** (it breaks caching and the cross-tenant rule).
- **An `llm_usage` row missing for a call,** or a retry counted as a second question.
- **Grouping:**
  - two answers for one chat in flight;
  - a message dropped between groups;
  - an action answered before the text buffered ahead of it.

---

### Checkpoint 0: Agno behavior spike (first: Tasks 2 and 4 depend on it)
Three facts the broker design leans on, checked in a scratch script against Agno 3.1.6 with a fake model, not in production code. Record the findings in this plan.
- [ ] **`tool_call_limit=4` when the model asks for a 5th call.** Does Agno raise, return a non-completed status, or feed the model an error and let it answer?
  - The spec says "tool cap hit → menu".
  - If Agno lets the model answer, keep the reply. It still goes through the validator, so it is safe. Update the spec line instead of fighting the library.
- [ ] **The 400-token output cap per provider:**
  - `max_output_tokens` on `OpenAIResponses` and `Gemini`, `max_tokens` on `Claude`.
  - Confirm what a truncated reply looks like in `RunOutput`: its status, and whether the content is empty or cut. The broker must detect both and send the menu.
  - OpenAI counts reasoning tokens inside `max_output_tokens`. Check that 400 still leaves room for a reply at `reasoning_effort="low"`, or raise the cap for reasoning models only and record why.
- [ ] **The retry:** how to start a second run whose input is the first run's messages plus one correction message. Does Agno re-run tools in that run? The retry should not need new tool calls.
- [ ] **What Agno puts in the system message.**
  - Confirm that `instructions=STATIC_PREFIX` with `add_datetime_to_context` off and no `description` or `additional_context` sends the prefix byte for byte.
  - Confirm that memory turns can be passed as a `List[Message]` input (user/assistant pairs, then the tail and the question).
- [ ] **DeepSeek usage mapping** (`agno.models.deepseek.DeepSeek`, OpenAI-compatible):
  - DeepSeek reports cache hits as `prompt_cache_hit_tokens`, but Agno's OpenAI chat code only reads `prompt_tokens_details.cached_tokens`. Does `RunMetrics.cache_read_tokens` get filled? If not, read the raw usage in `llm.py`.
  - Where do thinking tokens land when `use_thinking` is on?
  - Check against a recorded or faked response; no paid call needed.

**Done when:** each fact has a one-line answer here, and the spec is updated if the tool-cap behavior differs.

**Findings (2026-11-05).** Scratch scripts against Agno 3.1.6 with each model's `invoke` or `response` faked; no paid calls.
- **Tool cap. Verified.**
  - Calls past `tool_call_limit` are not executed; Agno appends a tool message "Tool call limit reached… Don't try to execute it again." and keeps looping until the model answers. The run ends `completed`, and `RunOutput.tools` lists only the executed calls.
  - The spec changed: the reply after the cap is validated, not replaced by the menu.
  - Agno has no limit on model round trips after the cap. A model that keeps asking costs one call per ask (risk table).
- **Output cap. Verified from code, not with real calls.**
  - The parameters are `max_output_tokens` (`OpenAIResponses`, `Gemini`), `max_tokens` (`Claude`) and `max_tokens` (`DeepSeek`, via `OpenAIChat`).
  - Agno does not surface truncation: there is no finish reason in `RunOutput`, and OpenAI's `incomplete` status is read only in background mode. A cut reply comes back `completed` with partial text.
  - Rule adopted: incomplete means `output_tokens` (plus `reasoning_tokens` for Google) ≥ the cap.
- **OpenAI reasoning inside the 400 cap. Not verified** (needs paid calls). Task 9 shows it: if Luna's menu share from "incomplete" is high, raise the cap for reasoning models only.
- **System message. Verified** for the 12 real tools and `tool_call_limit=4`:
  - OpenAI, Gemini and DeepSeek send `instructions` byte for byte.
  - Claude appends a fixed English suffix ("Do not reflect on the quality of the returned search results…"). It is the same for every tenant, so caching and the cross-tenant rule still hold.
- **Memory as input. Verified.** A `List[Message]` input (user and assistant turns, then the tail, then the question) reaches the model in order after the system message. Without a DB, nothing carries over between runs.
- **Retry. Verified.**
  - A new `Agent.run` whose input is the first run's `messages` (without the system message) plus one user correction re-sends the earlier tool calls and results.
  - No tool is executed again.
- **Empty reply. Verified:** `status=completed`, `content=''`. The broker checks it itself.
- **Provider exception. Verified:** `run()` does not raise; it returns `RunStatus.error` with the error text as `content`.
- **DeepSeek usage. Verified from code:** Agno reads only `prompt_tokens_details.cached_tokens` and ignores DeepSeek's `prompt_cache_hit_tokens`. Whether DeepSeek also fills the standard field is not verified. Task 2 reads `prompt_cache_hit_tokens` when present.

### Task 1: Validator in `apps/api`, eval scorer on top of it

**Goal:** the pure `validate()` exists in the API, with every spec example as a test, and the eval's numbers score uses the same extraction.

**Files:**
- Create: `apps/api/src/mermia_api/agent/validator.py`
- Create: `apps/api/tests/agent/test_validator.py`
- Modify: `apps/eval/src/mermia_eval/score.py`. It keeps `score_numbers`, `must_contain` and `must_not_contain`, and imports `numbers`, `tool_numbers`, `strip_dates` and `LIST_MARKER` from the validator.
- Modify: `apps/eval/pyproject.toml` (adds `mermia-api` as a workspace source).

**Interfaces:**
- Produces: `validate(reply: str, *, tool_results: Sequence[str], question: str, memory: Sequence[Turn], dates: Iterable[str] = ()) -> set[Decimal]`. It returns the unsourced figures; empty means pass. `dates` carries the tail's today.
- Produces: a frozen `Turn(q: str, a: str, ts: datetime)`. It lives here so the validator has no import of the store.
- Adds: `H:MM` times are stripped before extraction. This is new: the eval treated "9:00" as a false positive.
- Changes from the eval scorer (production only; the eval's `score_numbers` keeps its own rule for question numbers so MR-20 scores stay comparable):
  - numbers from the question count only when not money-shaped (no `$`, no "mil", no decimals);
  - from memory, only the replies (`Turn.a`) count, never the questions (`Turn.q`).

**Steps:**
- [ ] **Step 1: Failing tests.**
  - One per row of the spec's Example table.
  - The MR-20 false positives: "últimos 30 días" with 30 in the question, "9:00", "5–11 de octubre", "28 de sep - 4 de oct".
  - The two real MR-20 failures, which must be rejected: the computed gap between locations and "$184 mil".
  - Value equality: `$18,450` against `"18450.00"`.
  - A figure from a memory reply passes; the same figure only in a memory question is rejected.
  - "¿vendí $50,000 ayer?" → "Sí, vendiste $50,000." is rejected; "top 5" and "30 días" from the question pass.
  - Known limits, documented as tests of current behavior: the ticket count quoted as pesos passes (attribution); "dieciocho mil" is not extracted.
- [ ] **Step 2: Run** `uv run pytest apps/api/tests/agent/test_validator.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** by moving the helpers, not rewriting them. Then point `score.py` at them.
- [ ] **Step 4: Run** the validator tests, then `uv run pytest apps/eval -q` (eval scores unchanged) and `uv run mypy`. Expected: PASS.
- [ ] **Step 5: Commit** `MR-27: number validator in the API, eval scorer reuses it`.

**Acceptance:**
- Every Example row and every listed MR-20 case gives the expected result.
- `apps/eval` tests are green with no scorer behavior change other than times.

**Result (2026-11-05), commit `bcfb1fb`:**
- **Red:** collection failed (`mermia_api.agent.validator` did not exist).
- **Green:** 21 validator tests pass. `uv run pytest apps/api apps/eval` gives 829 passed and 63 skipped (`db`); `uv run mypy` and `ruff` are clean.
- **Deviations from the plan:**
  - The eval scorer does not strip times. It stays exactly as MR-20 scored, so its numbers are comparable.
  - The one shared change is that Spanish month abbreviations ("4 de oct", "28 de sept") are now dates in both. This fixes the MR-20 false positive "28 de sep - 4 de oct" for the eval too.
  - "Money-shaped" in the question also covers thousands separators, `%`, "pesos" and "MXN" (spec updated).
- **Files:**
  - `apps/api/src/mermia_api/agent/validator.py` (new);
  - `apps/api/tests/agent/test_validator.py` (new);
  - `apps/eval/src/mermia_eval/score.py`, which imports the helpers;
  - `apps/eval/pyproject.toml` (`mermia-api`);
  - `uv.lock`.

**Dependencies:** none. **Scope:** M (4 files).

### Task 2: Provider adapter in `apps/api`

**Goal:** the API can build any `provider:model_id` model with the 400-token cap and price a call; the eval uses the same code.

**Files:**
- Create: `apps/api/src/mermia_api/agent/llm.py`. It holds `Price`, `PRICES` (from `mermia_eval.config.MODELS` and `PAUSED`), `TIMEOUT`, `build_model(spec_id, *, max_output_tokens=400)`, `cost_usd(model, input, cached, output, reasoning)` and `setup_tracing(env)`.
- Create: `apps/api/tests/agent/test_llm.py`, moving the relevant cases from `apps/eval/tests/test_run.py` and `test_tracing.py`.
- Modify: `apps/api/pyproject.toml` (dependencies, see Global Constraints).
- Modify: `apps/eval/src/mermia_eval/config.py`, `run.py` and `tracing.py`, which import from `mermia_api.agent.llm`. Eval keeps `SYSTEM_PROMPT` and `MODELS` as its own list of what to run.
- Modify: `apps/api/src/mermia_api/main.py` (tracing at startup) and `apps/api/tests/test_health.py` (the app starts with no Langfuse variables).

**Interfaces:**
- `cost_usd` takes token counts, not `RunResult`, so both callers can use it, and returns `Decimal`. `Price` holds `Decimal` values. The eval converts to `float` only where it prints or averages.
- `main.py` calls `setup_tracing(os.environ)` once at startup.
- `build_model` keeps the eval's per-provider settings (low reasoning, Gemini retries) and adds the output cap that Checkpoint 0 confirmed.
- **New provider `deepseek`:**
  - `DeepSeek(id=..., use_thinking=False, max_tokens=400, timeout=TIMEOUT)`. Thinking is off, as the other providers run with low reasoning.
  - Its price goes into `PRICES`, from DeepSeek's pricing page on the day of the task, with the date in a comment.
  - Its cost rule follows the Checkpoint 0 finding.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - The Anthropic, OpenAI, Gemini and DeepSeek cost rules.
  - `build_model("deepseek:deepseek-flash")` turns thinking off.
  - `build_model` per provider sets the output cap.
  - An unknown provider raises.
  - Tracing is off when a Langfuse variable is missing, and `/health` answers.
  - `cost_usd` returns a `Decimal`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Move the code and re-point the eval.
- [ ] **Step 4: Run** `uv sync --all-packages --all-groups`, `uv run pytest apps/api apps/eval -q` (including MR-26's no-LLM import test) and `uv run mypy`. Expected: PASS.
- [ ] **Step 5: Commit** `MR-27: provider adapter and prices in the API`.

**Acceptance:**
- The eval runs unchanged on top of the moved code.
- `import mermia_api.agent` still loads no LLM SDK.

**Result (2026-11-05), commit `211785d`:**
- **Red:** collection failed (no `mermia_api.agent.llm`); the startup test failed (no call to `setup_tracing`).
- **Green:** 14 adapter tests and the startup test pass. `uv run pytest apps/api apps/eval` gives 844 passed and 63 skipped (`db`). `mypy` and `ruff` are clean. A fresh `import mermia_api.agent` loads no `agno`, `openai`, `anthropic` or `google` module.
- **Deviations from the plan:**
  - `build_model(..., max_output_tokens=None)` defaults to no cap. The eval and its LLM judge keep measuring as MR-20 did, and only the broker passes 400.
  - **DeepSeek prices** (from the pricing page the product owner shared, 2026-11-05) are in `PRICES` for `deepseek:deepseek-flash` (0.3 / 0.006 / 1.2 USD per million tokens) and `deepseek:deepseek-v4-pro` (1.32 / 0.044 / 3.96).
    - DeepSeek has peak and off-peak bands, with off-peak at half price. `PRICES` uses the peak rate, so metered cost is an upper bound (a `shortcut:` comment in `llm.py`).
    - DeepSeek's `prompt_tokens` include the cache hits, so the OpenAI cost rule applies.
  - The eval keeps its own `ModelSpec` list but takes prices from `PRICES`. `post_scores` stays in the eval.
- **Files:**
  - `apps/api/src/mermia_api/agent/llm.py` and `apps/api/tests/agent/test_llm.py` (new);
  - `apps/api/pyproject.toml`, `apps/api/src/mermia_api/main.py`, `apps/api/tests/test_health.py`;
  - `apps/eval/src/mermia_eval/config.py`, `run.py`, `tracing.py`;
  - `apps/eval/tests/test_run.py`, `test_cli.py`, `test_config.py` (`Decimal` prices; "deepseek" is now a known provider);
  - `uv.lock`.

**Dependencies:** Checkpoint 0 (output-cap parameter names). It can go before Task 1, but both touch `apps/eval/pyproject.toml`, so do them in order. **Scope:** M (7 files, mostly moves).

### Task 3: Static prefix and tail

**Goal:** the prompt is split so the cached part never changes across tenants or days.

**Files:**
- Create: `apps/api/src/mermia_api/agent/prompt.py`, with `STATIC_PREFIX` and `tail(*, today, role, locations) -> str`. `role` is passed in by the caller; there is no data cutoff (the model calls `get_data_status`).
- Create: `apps/api/tests/agent/test_prompt.py`.

**Interfaces:**
- The instructions are the eval's rules with the date and the locations removed:
  - es-MX, brief;
  - figures only from tools, never computed;
  - say when no tool fits;
  - ask back when the question is ambiguous;
  - `propose_change` only proposes.
- The tail lists location names with their ids, today (Spanish, America/Mexico_City) and the role.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - A fixed `sha256` of `STATIC_PREFIX`, pinned.
  - The prefix contains no digit sequence that looks like a date and no location name.
  - `tail()` for two tenants differs, while the prefix used by both is the same object.
  - No phone, RFC or staff-name field is in `tail()`'s signature.
- [ ] **Step 2-4: Red, implement, green** (`uv run pytest apps/api/tests/agent/test_prompt.py -q`, `uv run mypy`).
- [ ] **Step 5: Commit** `MR-27: static prompt prefix and per-request tail`.

**Acceptance:**
- The prefix hash is pinned.
- Tenant context goes only into the tail.

**Result (2026-11-05), commit `75ba5c3`:**
- **Red:** collection failed (no module). Then the pinned-hash test failed on its placeholder, by design.
- **Green:** 6 prompt tests pass. The agent package has 286 tests passing; `mypy` and `ruff` are clean.
- **What was built:**
  - `role` is a `MemberRole` (from `mermia_contracts.db.models`), shown in Spanish (dueño, gerente, administrador, soporte).
  - The tail writes today as "jueves 5 de noviembre de 2026 (2026-11-05)"; the validator gets the ISO form as a date.
  - The prefix adds two rules beyond the eval prompt: "cópiala tal como la devuelven; nunca … sumes, restes, redondees ni calcules" and "cifras con dígitos, nunca con letras".
- **Files:** `apps/api/src/mermia_api/agent/prompt.py` and `apps/api/tests/agent/test_prompt.py` (new).

**Dependencies:** none. **Scope:** S (2 files).

### Task 3b: `Broker` gets the RPC caller per call

**Goal:** the broker can run tools as the user of each request (09 D8), and the LLM broker has its own module, so the template path stays free of LLM imports.

**Files:**
- Modify: `apps/api/src/mermia_api/agent/broker.py`. The protocol becomes `__call__(request, locations, rpc) -> AgentResponse`; `StubBroker` takes and ignores `rpc`. Update its docstring (it said the caller is fixed at build time).
- Modify: `apps/api/src/mermia_api/agent/__init__.py`. `answer()` passes its `rpc` to the broker.
- Modify: `apps/api/tests/agent/conftest.py` (`counting_broker`) and `apps/api/tests/agent/test_answer.py`.

**Steps:**
- [ ] **Step 1: Failing test:** an unmatched text reaches the broker with the same `rpc` object that `answer()` received.
- [ ] **Step 2-4: Red, implement, green** (`uv run pytest apps/api/tests/agent -q`, including the no-LLM import test).
- [ ] **Step 5: Commit** `MR-27: broker receives the RPC caller per call`.

**Acceptance:**
- The `rpc` passes through unchanged.
- All MR-26 tests are green.

**Result (2026-11-05), commit `f40f426`:**
- **Red:** 8 tests failed once `CountingBroker` and the `StubBroker` tests expected the third argument.
- **Green:** `uv run pytest apps/api apps/eval` gives 850 passed and 63 skipped; `mypy` is clean; the no-LLM import check passes.
- `RpcCall` moved from `agent/__init__.py` to `broker.py` (so the protocol can name it without a circular import) and is re-imported by `__init__`.
- **Files:** `apps/api/src/mermia_api/agent/broker.py`, `apps/api/src/mermia_api/agent/__init__.py`, `apps/api/tests/agent/conftest.py`, `apps/api/tests/agent/test_answer.py`.

**Dependencies:** none. **Scope:** S (4 small edits).

### Checkpoint A: after Tasks 1-3b
- [x] `.claude/skills/check/check.sh` green (2026-11-05: ruff, format, mypy, pytest and pgTAP all PASS). Each of the four commits was also checked alone (pytest, mypy, ruff) with the rest of the work stashed.
- [ ] Show the human the `STATIC_PREFIX` wording and the validator's test table. Both are cheap to change now and expensive after the broker is built on them.
- [ ] **Open PR 1** (Tasks 1-3b: validator, adapter move, prompt, broker signature). It is mostly moves and pure code, so it is reviewable on its own. Run `/review` first.

### Task 4: `LlmBroker` happy path and provider failure

**Goal:** an unmatched message gets an LLM reply that passes the validator; any provider failure gets the menu. Each call is recorded through a store interface.

**Files:**
- Create: `apps/api/src/mermia_api/agent/llm_broker.py`, with `LlmBroker`.
- Create: `apps/api/src/mermia_api/agent/usage.py`, with:
  - a `UsageRow` frozen dataclass mirroring the spec's `llm_usage` fields;
  - a `UsageStore` protocol: `add(row) -> UUID`, `questions_today(tenant_id, day) -> int`, `turns(tenant_id, user_id, channel) -> list[Turn]` and `save_turns(...)`;
  - an in-memory `MemoryStore` for tests and the eval.
- Create: `apps/api/tests/agent/test_broker.py`.
- Modify: `apps/api/tests/agent/conftest.py` (fixtures for the fake agent factory and the memory store).

**Interfaces:**
- `LlmBroker(model: str, store: UsageStore, agent_factory=Agent, clock=…)`, called as `(request, locations, rpc)`. It also needs the user's role for the tail; the caller passes it (as a constructor-time resolver or an extra argument; choose the smaller change and note it).
- **Input gate:** anything but a `TextInput` gets the menu, with no model call and no row.
- **Tools** are built per call from `tool_definitions()`, wrapped as the eval does (`build_tools`), closing over that call's `rpc`. Each tool:
  - validates its arguments with `RPCS[name].args.model_validate`; a `ValidationError` goes back to the model as text and the RPC is not called;
  - serializes the `RpcEnvelope` to JSON text for the model and keeps it for the validator;
  - returns an RPC exception to the model as an error text.
  - `propose_change` returns `{"status": "pending_approval"}` and writes nothing.
- **An empty or incomplete reply** (per Checkpoint 0) gets the menu with `error` set.
- **Routes:** the response gets `route="haiku"` on success and `route="fallback"` on the menu. Every `llm_usage` row of a call gets `route="haiku"`, failures included.
- `usage_id` is the id of the last row.

**Steps:**
- [ ] **Step 1: Failing tests** with a scripted factory:
  - a clean reply is sent as a `TextMsg` with one `pass` row (tokens, cost, latency and tool count from `RunMetrics`);
  - a raised exception gives the menu with `error` set and a null `validator_result`;
  - a non-completed status gives the same;
  - the tool cap behaves as Checkpoint 0 found;
  - the tail and the question reach the model input;
  - `pc:<uuid>:approve`, an unknown action and media get the menu, and the factory is never called;
  - a tool call with invalid arguments returns the validation error and the fake RPC records no call;
  - two requests from two tenants, each with its own fake `rpc`, record their tool calls on their own `rpc` only;
  - an RPC that raises inside a tool returns an error text to the model, and the run continues;
  - an empty reply and an incomplete reply each give the menu with `error` set.
- [ ] **Step 2-4: Red, implement, green.**
- [ ] **Step 5: Commit** `MR-27: LLM broker with metering and menu on provider failure`.

**Acceptance:**
- Pass and failure paths match the spec, with one row per call.
- No exception escapes `LlmBroker.__call__`.
- Tools run only through the `rpc` of the call, with validated arguments.

**Dependencies:** Checkpoint 0, Tasks 1-3b. **Scope:** M (4 files).

### Task 5: Retry and reject

**Goal:** an invented figure gets one silent retry, then the menu with "No pude confirmar esa cifra. Prueba con una de estas:".

**Files:**
- Modify: `apps/api/src/mermia_api/agent/llm_broker.py`.
- Modify: `apps/api/tests/agent/test_broker.py`.

**Interfaces:**
- The retry is a new run whose input is the first run's messages plus one user message naming the unsupported figures (Q3), built as Checkpoint 0 found.
- The validator for the retry also counts the first run's tool results as sources.
- Row values: `retry` on the first row, then `retry_pass` or `reject`. Both rows share a `request_id`.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - Invented, then clean: the clean reply is sent, with rows `retry` and `retry_pass`.
  - Invented twice: the menu with the fixed text, with rows `retry` and `reject`.
  - A provider failure during the retry: the menu, with the second row's `error` set.
  - The retry message names the flagged figures.
- [ ] **Step 2-4: Red, implement, green.**
- [ ] **Step 5: Commit** `MR-27: one retry, then the menu, on an unsourced figure`.

**Acceptance:** spec acceptance criteria 4 and 1 (invented figure) pass at the broker level.

**Dependencies:** Task 4. **Scope:** S (2 files).

### Task 6: Postgres store

**Goal:** `llm_usage` rows and conversation turns land in Postgres, and the daily question count reads them back.

**Files:**
- Modify: `apps/api/src/mermia_api/agent/usage.py`. It adds `PgStore(conn_factory)`, following `ingestion/recipes.py`'s psycopg style.
- Create: `apps/api/tests/agent/test_usage_db.py`, marked `db`. It uses the `conn` fixture pattern from `tests/ingestion/test_loader.py` and rolls back.

**Interfaces:**
- `PgStore` takes a privileged (backend) connection factory. `llm_usage` and `conversation` are backend-only tables. This connection is never handed to the tool path.
- `add` inserts one row and returns its id.
- `questions_today` counts distinct `request_id` where `ts` falls on the Mexico City day.
- `save_turns` upserts `conversation` on `(tenant_id, user_id, channel)` and keeps the last 4.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - A row round-trips with every field.
  - Two rows with one `request_id` count once.
  - A row at 23:30 Mexico City counts on that day, not the UTC day.
  - Saving 5 turns keeps the last 4.
  - A second save updates rather than duplicating.
- [ ] **Step 2: Run** `MERMIA_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run pytest -m db apps/api/tests/agent -q`. Expected: FAIL.
- [ ] **Step 3-4: Implement, green.** Also run the suite without `MERMIA_DB_URL`: these tests skip.
- [ ] **Step 5: Commit** `MR-27: llm_usage and conversation in Postgres`.

**Acceptance:** spec acceptance criterion 5 (one row per call, against Postgres).

**Dependencies:** Task 4 (the protocol). It can run in parallel with Task 5: different files. **Scope:** S (2 files).

### Task 7: Daily cap and memory

**Goal:**
- The 61st question of the day gets the menu without a model call.
- Follow-ups see the last 4 turns, which expire after 2 h.
- Every answered message, template answers included, becomes a turn.

**Files:**
- Modify: `apps/api/src/mermia_api/agent/llm_broker.py`, for the cap check and memory into the model input and the validator.
- Modify: `apps/api/src/mermia_api/agent/__init__.py`. It adds `respond(request, *, locations, rpc, broker, store, clock) -> AgentResponse`, which:
  - calls `answer()`;
  - saves the turn when the response is not the menu;
  - catches any exception and returns the menu, so it never raises.

  `answer()` keeps its routing (spec constraint).
- Modify: `apps/api/tests/agent/test_broker.py` and `apps/api/tests/agent/test_answer.py`.

**Interfaces:**
- Constants in `llm_broker.py`: `DAILY_QUESTIONS = 60`, `MAX_TOOL_CALLS = 4`, `MEMORY_TURNS = 4`, `MEMORY_TTL = timedelta(hours=2)`. `MAX_OUTPUT_TOKENS = 400` lives in `llm.py`.
- A turn's `a` is the text of the reply's first `TextMsg`.

**Steps:**
- [ ] **Step 1: Failing tests.**
  - Cap:
    - with 60 questions today, the factory is never called and the menu is sent;
    - with 59, the 60th goes through.
  - Memory into the model:
    - "¿y Norte?" after a Centro turn has that turn in the model input;
    - a turn 2 h 1 min old is not in the input.
  - Memory into the validator: a figure from a memory reply passes it.
  - Memory written by `respond()`:
    - a template answer is saved as a turn;
    - the menu is not saved.
  - A broker that raises inside `respond()` gives the menu.
- [ ] **Step 2-4: Red, implement, green.**
- [ ] **Step 5: Commit** `MR-27: daily cap and short memory`.

**Acceptance:** spec acceptance criteria 7 (cap) and 11 (memory and TTL).

**Dependencies:** Task 5. It needs only the store protocol from Task 4; tests use `MemoryStore`, so Task 6 is not a prerequisite. **Scope:** M (4 files).

### Checkpoint B: after Tasks 4-7
- [ ] `.claude/skills/check/check.sh` green, including `-m db` with local Supabase.
- [ ] Walk the spec's Example table through `LlmBroker` with the fake model in one test file, and show the human the sent texts (pass, menu after reject, menu over cap).

### Task 8: Grouping front door

**Goal:** a burst of texts in one chat becomes one question and one `send`; actions and media keep their order; one answer in flight per chat.

**Files:**
- Create: `apps/api/src/mermia_api/agent/grouping.py`.
- Create: `apps/api/tests/agent/test_grouping.py`.

**Interfaces:**
- `Grouper(respond: Callable[[AgentRequest], AgentResponse], *, window=2.5, timer=threading.Timer, executor=…)`.
- `submit(request, send: Callable[[AgentResponse], None]) -> None`.
- The key is `(tenant_id, user_id, channel)`.
- The joined text is the texts in arrival order, separated by `\n`, in a new `TextInput`. Other request fields come from the last message.
- An action or media input flushes the buffer first.
- One worker per key at a time: messages that arrive while it runs start the next group.
- `shortcut:` comment as written in the spec (single instance; a restart drops the buffer).

**Steps:**
- [ ] **Step 1: Failing tests,** with a fake timer fired by hand and a synchronous executor, so there are no real sleeps:
  - three texts 1 s apart give one `respond` call with the joined text and one `send`, on the last message's callback;
  - a text then an action gives two calls, text first;
  - a text arriving during an in-flight answer is answered after it, as its own group;
  - two chats do not block each other;
  - a `respond` that raises anyway (a bug, since Task 7 makes it catch everything) is logged, and the chat's next group still runs.
- [ ] **Step 2-4: Red, implement, green.**
- [ ] **Step 5: Commit** `MR-27: group message bursts per chat`.

**Acceptance:** spec acceptance criteria 8, 9 and 10.

**Dependencies:** Task 7 (`respond`). Logically it only needs a callable, so it can be built in parallel with Tasks 4-7 against a fake `respond`. **Scope:** S (2 files).

### Task 9: Smoke eval on the real broker

**Goal:** check, with paid calls, that the real prompt, validator and retry do not regress against MR-20's preliminary numbers (Q4).

**Files:**
- Modify: `apps/eval/src/mermia_eval/cli.py` (a `--broker` flag) and `apps/eval/src/mermia_eval/run.py`.
  - With `--broker`, each case runs `LlmBroker` with the Mock RPC caller, a `MemoryStore` and the clock fixed at 2026-10-12 (the date the mock data and `SYSTEM_PROMPT` assume).
  - Menu answers (reject, provider failure) are counted apart and not scored as replies.
  - `RunResult` is filled from the broker's recorded tool results and usage rows.
  - The `validator_result` counts are reported.
- Modify: `apps/eval/tests/test_run.py` (the broker path with a fake factory).
- Modify: `docs/decisions/llm.md` (a "MR-27 smoke run" section).

**Steps:**
- [ ] **Step 1: Failing test:** `--broker` builds an `LlmBroker` and maps its output into a `RunResult`.
- [ ] **Step 2-4: Red, implement, green** (`uv run pytest apps/eval -q`).
- [ ] **Step 5: Paid run, by hand,** after the human's go-ahead:
  `uv run --env-file .env mermia-eval --broker --models openai:gpt-5.6-luna --out apps/eval/out/mr27-smoke.json`
  - Add `anthropic:claude-haiku-5-5` if its key works (smoke it alone first, as `llm.md` step 3 says).
  - Add `deepseek:deepseek-flash` if `DEEPSEEK_API_KEY` is set (smoke it alone first, too). `deepseek-flash` is DeepSeek's current name; `deepseek-v4-flash` is a legacy alias.
  - Add DeepSeek to `MODELS` in `apps/eval/src/mermia_eval/config.py`, so later full runs include it.
- [ ] **Step 6: Record** the gate table, the reject and retry counts, the cost and any validator false positive in `docs/decisions/llm.md`.
- [ ] **Step 7: Commit** `MR-27: smoke eval on the real broker`.

**Acceptance** (the spec's pass rule):
- Tool and args are at or above 0.95.
- Every numbers failure on a sent reply is a written false positive.
- Menu answers are at most 5 % of cases, each listed.
- The result is recorded.

**Dependencies:** Tasks 5 and 7. **Scope:** M (4 files plus a paid run).

### Checkpoint C: complete
- [ ] `.claude/skills/check/check.sh` green, with `-m db`.
- [ ] Every spec acceptance criterion is ticked (see Self-review).
- [ ] Tracing: with the Langfuse variables set, one local broker call shows a trace. Without them, nothing breaks.

### Task 10: PR 2 (no new code)
- [ ] In the PR description, write:
  - the route-label decision (Q1);
  - the grouping shortcut;
  - the Checkpoint 0 findings;
  - the note for MR-21 that the webhook calls `Grouper.submit(request, send)` and loads `locations`.
- [ ] Run `/review` (the built-in `/code-review`, then the `skeptic-reviewer` agent), fix the findings and open the PR.

**Dependencies:** Checkpoint C.

## Parallelization

- **Tasks 1, 3 and 3b are independent;** 3 and 3b can run alongside Task 1. Task 2 shares `apps/eval/pyproject.toml` with Task 1, so it goes after it.
- **Tasks 5 and 6 are independent** once Task 4 defines the store protocol.
- **Task 8 needs only a `respond` callable** and can be built against a fake at any point after Task 3.

One developer owns this ticket (Dev B), so the order above is the default.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| After the tool cap, Agno lets the model keep asking; each ask is a paid model round trip | Low | Seen in Checkpoint 0. Models stop after the "limit reached" message in practice; the HTTP timeout bounds each call. Task 9 checks it, and a run-level deadline is a follow-up if it appears |
| Agno adds text (a date, its own instructions) to the system message, so the prefix is not byte-identical | High for cost | Checkpoint 0 inspects the real system message. The prefix test hashes what is sent, not only the constant. The cache hit rate shows up in `cache_read_tokens` |
| Validator false positives push correct answers to the menu | High for usefulness | MR-20 false positives as tests (Task 1); smoke eval counts rejects (Task 9); `validator_result` is metered for the pilot |
| A missed figure pattern lets an invented number through (for example "dieciocho mil" in words) | High for trust | Written-out numbers are not covered. The prompt forbids them; record it as a known gap in the PR and add a test that documents the current behavior |
| A figure attached to the wrong measure passes ("$212" from the ticket count) | Medium | Known limit in the spec, documented by a test; the eval's args and tone scores watch it |
| The output cap cuts replies of reasoning models (OpenAI counts reasoning inside `max_output_tokens`) | Medium | Checkpoint 0 measures it; an empty or cut reply gets the menu, never a half answer |
| A tool call runs with someone else's identity | High | `rpc` per call (Task 3b), a two-tenant test (Task 4); the real JWT is minted by the caller (MR-21, MR-31) |
| Prompt injection through tool data (dish names from SR exports) | Low | Read-only RLS-scoped tools; `propose_change` needs human approval; the validator limits what a hijacked reply can claim |
| Moving code from `apps/eval` breaks the eval | Medium | Tasks 1-2 run the eval tests on every step; moves, not rewrites |
| `apps/eval` → `apps/api` dependency pulls FastAPI and psycopg into eval | Low | Same workspace; already installed by `uv sync --all-packages` |
| Grouping threads plus synchronous Agno calls under FastAPI | Medium | One worker per chat; a bounded executor; a fake timer in tests. The single-instance limit is a documented shortcut |
| The daily-cap race across chats of one tenant | Low | Accepted in the spec (overshoot at most the number of concurrent chats) |
| `"haiku"` route label is misleading if the model is Luna | Low | Decided (Q1); `llm_usage.model` has the truth |
| Paid smoke run blocked by keys (Anthropic not set up, Google free tier) | Low | Luna alone is enough to pass Task 9 |
| DeepSeek cache hits not mapped by Agno, so `cache_read_tokens` is 0 and cost is overstated | Medium | Checkpoint 0 checks the mapping; `llm.py` reads the raw usage if needed |
| DeepSeek processes data on servers in China. No PII is sent, but sales, costs and location names of each restaurant are | Product decision | Not a technical blocker for MR-27. The product owner decides before DeepSeek serves a real pilot customer |
| Estimate grows past 3 days | Accepted | The product owner accepted it; two PRs keep reviews small |

## Self-review: spec coverage

| Spec item | Task |
|---|---|
| Validator rules, Example table, MR-20 cases, memory figures | 1, 7 |
| No money figure from the question; memory replies only; attribution limit documented | 1 |
| Per-request `RpcCall` (09 D8); `Broker` signature change | 3b, 4 |
| Tool argument validation; RPC exception back to the model | 4 |
| Input gate: `pc:`, other actions and media → menu | 4 |
| Empty or incomplete reply → menu | Checkpoint 0, 4 |
| `respond` never raises | 7, 8 |
| `Decimal` cost; tracing at API startup | 2 |
| Backend connection for the store | 6 |
| One retry, then the menu with the fixed text | 5 |
| Provider failure and the tool cap → menu, `error` set | Checkpoint 0, 4 |
| Static prefix byte-identical; tail with date, role (passed in), locations; no cutoff; no PII | 3, Checkpoint 0 |
| Model from configuration; 400 output tokens; prices and cost rule | 2 |
| One `llm_usage` row per call; fields; `validator_result` values; `request_id` | 4, 5, 6 |
| Daily cap of 60 questions, Mexico City day, distinct `request_id` | 6, 7 |
| Memory: 4 turns, 2 h TTL, template answers in, menu out, no tool results | 6, 7 |
| Grouping: window, join, actions flush, one in flight, `send` callback, shortcut | 8 |
| Langfuse traces | 2, Checkpoint C |
| `propose_change` without writing; no `apply_*`; no service role in tools | 4 |
| Router, templates and `answer()` unchanged; MR-26 no-LLM import | 2, 7, every checkpoint |
| Smoke eval recorded in `llm.md`, fixed clock, explicit pass rule | 9 |
| Q1-Q6 decisions | Global Constraints (Q1), 1-2 (Q2), 5 (Q3), 9 (Q4), 7 (Q5), not built (Q6) |

Not covered, by design (out of scope in the spec):
- model choice;
- the conversation summary;
- per-tenant caps;
- preference memory;
- alerts;
- escalation and fallback models;
- the webhook;
- `pc:` handlers;
- real RPCs;
- multi-instance grouping.

## Open items

- **Checkpoint 0 findings** may change one spec line (tool cap behavior).
- **Checkpoint A:** the human reviews the prompt wording and the validator's table.
- **Task 9:** the go-ahead for the paid run.
- **DeepSeek data residency:** a product decision, needed before DeepSeek answers a real pilot customer.
