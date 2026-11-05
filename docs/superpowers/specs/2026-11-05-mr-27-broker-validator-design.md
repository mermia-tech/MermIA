# MR-27: LLM broker loop and number validator (design)

Ticket: MR-27 (issue 27), branch `MR-27-broker-validator`. Plan of record: `docs/kickoff/09-architecture.md` §4.2 (agent pipeline) and `docs/kickoff/13-llm-and-token-strategy.md` (§H3 validator, §I1 memory, §I4 metering, caps). Needs MR-20 (eval gate, provisional: `docs/decisions/llm.md`), MR-13 (Mock RPC) and MR-26 (router, templates, `Broker` protocol). Unlocks MR-31 (switch to real RPCs) and MR-21 (the WhatsApp webhook calls this ticket's entry point).

Scope agreed with the product owner on 2026-11-05 (interview). Spec status: **approved 2026-11-05**, with the proposal of every open question (Q1-Q6) accepted. Plan: `docs/superpowers/plans/2026-11-05-mr-27-broker-validator.md`.

## Objective
MR-26 answers the top questions with templates; everything else reaches `StubBroker`, which replies "Todavía no sé responder eso" and shows the menu. This ticket replaces the stub with the real broker: an LLM that picks among the 12 C4 tools, reads their results and writes the es-MX reply. A validator then blocks any reply with a figure no tool returned.

**User:** the owner or manager who asks by WhatsApp. **Why:** one invented number kills the owner's trust; the validator is the safety net. **Success:**
- No reply ever reaches the owner with a figure that is not in a tool result, the question or an earlier validated reply.
- Every LLM call is metered in `llm_usage`.
- Short follow-ups ("¿y Norte?") work.
- A burst of messages gets one answer.

## Expected behavior

### Pipeline (changes in bold)
1. **Grouping.** Messages from one chat are buffered until no new message arrives for `GROUP_WINDOW` (2.5 s), then joined into one question (see Grouping).
2. Router and templates (MR-26), unchanged.
3. **Broker** for every message the router does not take. It receives the request's `RpcCall` on each call, built by the caller with the user's identity (09 D8):
   0. **Input gate.** Only a `TextInput` reaches the LLM. A `pc:` action, any other action id and media get the template menu (`route="fallback"`), as `StubBroker` does today, until their handlers exist.
   1. **Cap check.** Over a cap → the template menu (`route="fallback"`), no LLM call.
   2. **Load memory:** the last 4 turns of the conversation, if the last one is younger than `MEMORY_TTL` (2 h); otherwise memory starts empty.
   3. **LLM loop:** static prefix + tail message (tenant context) + memory turns + the question. The model calls tools (at most 4 calls) and writes a reply (at most 400 output tokens). Each tool call:
      - validates its arguments against `RPCS[name].args`; invalid arguments go back to the model as the tool result, and the RPC is not called (the `ToolExecutor` of 09 §4.2);
      - runs through the request's `RpcCall`;
      - an RPC exception (network, timeout) goes back to the model as an error text, as in the eval harness. The validator still checks the final reply.
   4. **Validate** the reply (see Validator).
      - Pass → send it.
      - Empty or incomplete reply → the template menu, as a provider failure. Agno reports neither as a failure (Checkpoint 0): empty means blank `content`; incomplete means the call's output tokens (plus Gemini's thinking tokens) reached the output cap.
      - Fail → one silent retry: a new run whose input is the first run's messages plus a message naming the unsupported figures and asking for a rewrite with tool data only. Validate again.
      - Fail again → the template menu with "No pude confirmar esa cifra. Prueba con una de estas:" (`route="fallback"`).
   5. **Write** one `llm_usage` row per LLM call and append the turn (question + final text sent) to `conversation.last_turns`, keeping the last 4.
4. **Provider failure** (exception, timeout, 429/5xx, run status not completed) → the template menu (`route="fallback"`), `llm_usage.error` set. The owner never gets silence or an error text. Agno turns a provider exception into `RunStatus.error` with the error as `content`; that content is never sent.

### Example (El Güero seed)
Tool result: Centro sales `$18,450.00`, 212 tickets, average ticket `$87.03`; Norte `$12,300.50`; as of 09:00 on 2026-11-04.

| Reply | Result | Why |
|---|---|---|
| "Ayer Centro vendió $18,450 con 212 tickets (promedio $87.03)." | pass | every figure is in the tool result; `$18,450` equals `18450.00` as a value |
| "Entre las dos vendiste $30,750.50." | reject | a sum the LLM computed (09 D6: the LLM never computes money) |
| "Centro vendió como $18 mil." | reject | `18` is not a tool value; rounding that changes the value |
| "Vendiste 15% más que la semana pasada." | reject | invented |
| "Datos al 4 de noviembre, a las 9:00." | pass | tool dates and times are not figures |
| Q: "¿cuánto vendí en los últimos 30 días?" → "En los últimos 30 días…" | pass for `30` | the number is in the question and is not money-shaped |
| Q: "¿vendí $50,000 ayer?" → "Sí, vendiste $50,000." | reject | a money figure from the question is never a source: the agent would confirm the owner's guess |
| Turn 2: "Norte vendió $12,300.50, menos que los $18,450 de Centro." | pass | `$18,450` is in the turn-1 reply, which was validated when sent |

### Validator
A pure function: `validate(reply, *, tool_results, question, memory) -> set[Decimal]` returns the figures with no source (empty = pass).
- **Figures in the reply:** every number, compared as a `Decimal` value (so `$18,450.00` = `18450` = `18,450`), after removing:
  - tool dates in ISO, Spanish ("4 de noviembre", "del 5 al 11 de octubre") and dd/mm/yyyy form;
  - the date in the tail message (today);
  - times written `H:MM`;
  - list markers ("1. ", "2) ").
- **Known figures:**
  - the numbers in tool results (display text and plain values; not the `raw` centavos, UUIDs or dates);
  - the bare numbers in the question: no `$`, no thousands separator, no decimals, and no `%`, "mil", "pesos" or "MXN" after them (so "30 días" and "top 5" count; "$50,000", "50,000", "40 mil" and "15%" do not);
  - the numbers in the agent's replies in the memory turns. The owner's earlier questions are not a source.
- **Known limit:** the validator checks that a figure exists in a source, not that it is attached to the right measure. "Vendiste $212" passes when 212 is the ticket count, and small integers can match by chance. The prompt and the eval's args and tone scores cover attribution; a test documents this limit.
- **Reuse:** this is the MR-20 numbers scorer (`apps/eval/src/mermia_eval/score.py`: `_numbers`, `_tool_numbers`, `_strip_dates`, `_LIST_MARKER`), without the `must_contain` / `must_not_contain` parts. Where it lives is open question Q2.

### Grouping
- **Keyed by** `(tenant_id, user_id, channel)`, the `conversation` unique key.
- **Text inputs** are buffered. Each new text restarts the `GROUP_WINDOW` timer. When it fires, the texts are joined with a newline into one `TextInput` and go through the pipeline once.
- **Action and media inputs** are not grouped: they first flush the chat's buffer (if any text is waiting, it is answered first), then are answered on their own, in arrival order.
- **One in flight per chat:** a message that arrives while that chat's answer is being computed is buffered and starts a new group after the current answer is sent. Two answers for one chat never run at once.
- **Never silent:** the callable the grouper runs (`respond`) catches every exception and returns the menu. The grouper itself has no `locations` to build a menu, so an exception that still reaches it is logged as a bug.
- **Delivery:** the caller hands in a `send(AgentResponse)` callback with each message; the grouped answer is delivered through the callback of the last message in the group. MR-21 provides the WhatsApp `send`.
- **State is in process memory.** `shortcut: grouping state lives in one process, so it works only with a single API instance and a restart drops buffered messages; move it to Postgres (advisory lock + queue table) or Procrastinate before running more than one instance.`

### Caps (constants in code, 09 §4.2, 13 §I4)
| Cap | Value | On hit |
|---|---|---|
| LLM questions per tenant per day | 60 | template menu, no LLM call |
| Output tokens per call | 400 | provider `max_tokens` |
| Tool calls per question | 4 | Agno's `tool_call_limit`: a 5th call is not executed, and the model gets "Tool call limit reached" and must answer. That reply is validated like any other (Checkpoint 0) |
| Answers in flight per chat | 1 | enforced by Grouping |

- **Daily count:** distinct `request_id` of today's `llm_usage` rows for the tenant (a retry is not a second question). "Today" is the America/Mexico_City calendar day (shortcut: one time zone for all pilot locations, as in MR-26).
- **Cap race:** two chats of one tenant can both read 59 and both pass. Accepted: the overshoot is at most the number of concurrent chats.

### Prompt
- **Static prefix:** system instructions plus the 12 tool definitions (`mermia_contracts.agent_tools.tool_definitions()`), byte-identical for every tenant, user and day, so the provider can cache it. A test pins its hash.
- **Tail message (not cached):**
  - today's date (America/Mexico_City);
  - the user's role, passed in by the caller like `locations` (`AgentRequest` has no role; the caller resolves it anyway to mint the user JWT of 09 D8);
  - the location names and ids from `locations`.
- **No data cutoff in the tail:** it would need an extra RPC per question. The model calls `get_data_status` when freshness matters.
- **Never sent to the LLM** (CLAUDE.md): phone numbers, RFCs, full staff names.
- The eval prompt (`mermia_eval.config.SYSTEM_PROMPT`) has the date and the locations inside it. The broker's prefix must not.

### Metering
- **One `llm_usage` row per LLM call**, retries included. Rows of one question share `request_id`.
- **Fields:**
  - `tenant_id`, `location_id` (null: a question can span locations), `user_id`, `route`, `model`;
  - `input_tokens`, `cache_read_tokens`, `cache_write_tokens`, `output_tokens`, from the provider's usage;
  - `cost_usd`, from a price table in code;
  - `latency_ms`, `tool_calls`, `validator_result`, `error`.
- **`validator_result` values:**
  - `pass`: the first reply passed;
  - `retry`: the first reply failed and a retry follows;
  - `retry_pass`: the retry passed;
  - `reject`: the retry failed;
  - null: no reply, because the call failed.
- **`route`:** `haiku` (the primary LLM route, Q1) on every row of an LLM call, including a failed one; the failure is in `error`. A question answered with the menu over the cap has no row, because no call was made.
- **Cost:** reuse the MR-20 rule (`mermia_eval.run.cost_usd`: Anthropic input excludes cache reads; Google bills thinking as output), computed in `Decimal`, not `float` (CLAUDE.md: no floats for money; the column is `numeric(12,6)`).
- **Traces:** Langfuse through OpenInference + OTLP, as `mermia_eval.tracing.setup_tracing`. The API calls it once at startup (`main.py`). Tracing is off when the Langfuse variables are missing, and the API starts normally.
- `AgentResponse.usage_id` carries the id of the last row.

### Memory
- **Stored in** `conversation.last_turns` (jsonb), a list of at most 4 `{"q": text, "a": text, "ts": iso}` entries.
- **What a turn holds:** only the owner's (grouped) question and the final text sent. Tool results are never stored or replayed.
- **What goes into memory:**
  - template answers: yes, so "¿y Norte?" after a template answer works;
  - the fallback menu: no.
- **Expiry:** if the newest turn is older than `MEMORY_TTL` (2 h), the broker ignores the stored turns, and the next write replaces them.
- **Untouched:** `conversation.summary` is not read or written in this ticket.

## Requirements

### Functional
- F1. Every text message the router does not take goes to the LLM broker unless a cap is hit. Other inputs get the menu.
- F1b. Tool calls run as the user (per-request `RpcCall`, 09 D8) with arguments validated against `RPCS[name].args`.
- F2. No reply is sent with a figure that the validator cannot source (tool results, question, memory).
- F3. A failed validation gets exactly one retry; a second failure sends the menu.
- F4. Provider failures and empty or incomplete replies send the menu, never an error or silence. A reply written after the tool-call cap is validated like any other.
- F5. One `llm_usage` row per LLM call, with the fields above.
- F6. Over the daily cap, the menu is sent and no LLM call is made.
- F7. Follow-ups use the last 4 turns, which expire after 2 h without messages.
- F8. A text burst within the grouping window gets one answer.
- F9. Replies are es-MX; code, comments and logs are English.

### Non-functional
- N1. The provider and model come from configuration (one `provider:model_id` string, as in the eval). Changing the model needs no code change.
- N2. The static prefix is byte-identical across tenants (hash test).
- N3. The validator is a pure function with no I/O.
- N4. The template path still loads no LLM SDK (MR-26 N1 test keeps passing). The LLM broker lives in its own module (`llm_broker.py`); `broker.py`, which `agent/__init__.py` imports, keeps only the protocol and the stub.
- N5. ruff, ruff format and mypy strict pass (`/check`).
- N6. The added latency is grouping's 2.5 s; no extra LLM call besides the one retry on a validation failure.

## Acceptance criteria
- [ ] The validator rejects a reply with an invented figure (test; issue "done when").
- [ ] The validator rejects a sum, a value-changing rounding and a money figure that only the question contains, and accepts:
  - a value written with a different format;
  - tool dates in ISO, Spanish and range form;
  - a time;
  - a non-money number from the question;
  - a number from an earlier reply in memory (but not from an earlier question).
- [ ] A test documents the attribution limit (a tool's ticket count quoted as pesos passes).
- [ ] A `pc:` action, an unknown action and media reaching the broker get the menu with no model call.
- [ ] A tool call with invalid arguments returns the validation error to the model and does not call the RPC.
- [ ] Two requests from different tenants run their tool calls through their own `RpcCall`, never one shared at construction.
- [ ] An empty reply and an incomplete reply each give the menu.
- [ ] Every row of the Example table gives its result (one test per row).
- [ ] A broker test with a fake model:
  - first reply invented, retry clean → the clean reply is sent, with two `llm_usage` rows (`retry`, `retry_pass`);
  - both invented → the menu, with rows `retry`, `reject`.
- [ ] Every LLM call writes one `llm_usage` row (issue "done when"), checked against Postgres in a `-m db` test.
- [ ] A provider exception and a non-completed run each give the menu with `error` set.
- [ ] A 5th tool call is not executed, and the reply that follows is validated and sent when it passes.
- [ ] The 61st question of the day for a tenant gets the menu with no model call.
- [ ] Three texts sent 1 s apart produce one pipeline call with the joined text and one `send`.
- [ ] An action during a buffered text answers the text first, then the action.
- [ ] A message during an in-flight answer starts a new group after it.
- [ ] An exception inside `respond` still sends the menu.
- [ ] "¿y Norte?" after a turn about Centro's sales reaches the model with that turn in its input; after 2 h it does not.
- [ ] The static prefix hash is the same for two tenants with different locations, dates and roles.
- [ ] A smoke eval with 1-2 models on the real broker is recorded in `docs/decisions/llm.md`. It runs by hand (paid calls) with the clock fixed at 2026-10-12, the date the mock data assumes. Pass means:
  - tool and args at or above 0.95;
  - every numbers failure on a sent reply is listed as a written false positive;
  - menu answers (reject, cap, failure) are counted apart and are at most 5 % of cases, with each reject listed.
- [ ] With the Langfuse variables unset, the API starts and answers; with them set, a broker call produces a trace (checked by hand once).
- [ ] `.claude/skills/check/check.sh` passes.

## Constraints and existing behavior to keep
- **Router and templates:** `answer()`'s routing, the 8 intents, their exact replies and the `tpl:` taps stay as MR-26 left them. `answer()` keeps its signature; grouping wraps it.
- **`Broker` protocol changes** to `__call__(request, locations, rpc) -> AgentResponse`, and `answer()` passes its `rpc` through. The RPC caller carries the user's identity, so it cannot be fixed when the broker is built (09 D8). This is an `apps/api` interface, not a contract. The real broker gets its model and store when it is built.
- **Backend connection:** `llm_usage` and `conversation` are backend-only tables (`app.finish_table(..., 'backend')` revokes every client privilege), so the store uses a privileged connection. That connection is never handed to the tool path.
- **`packages/contracts`:** not changed unless Q1 is decided that way (both devs approve contract changes).
- **Writes:** the LLM never calls `apply_*`. `propose_change` is offered as a tool, and a call returns `{"status": "pending_approval"}` without writing, as in the eval harness. The real write path is the confirmation flow (09 §5), not this ticket.
- **No service role in the tool path.** Tools go through the injected `RpcCall` (the Mock RPC until MR-31). `llm_usage` and `conversation` writes use the backend connection.
- **Migrations** are append-only; this ticket needs none (`llm_usage` and `conversation` exist in `20261018185214_control.sql`).
- **Eval cases** in `apps/eval/cases/` are read, never edited.

## Scope

### In scope
- `apps/api/src/mermia_api/agent/`: the LLM broker, validator, grouping, caps, memory, metering and the provider adapter.
- Adding Agno and the provider SDKs to `apps/api` (planned stack, 09 §7; see Boundaries).
- Langfuse tracing of broker calls.
- Tests in `apps/api/tests/agent/` and a `-m db` test for `llm_usage` and `conversation`.
- A smoke eval run (1-2 models) and its note in `docs/decisions/llm.md`.

### Out of scope
- **Model choice:** the final eval run (about US$20) and choosing the primary model. That is a product-owner gate (`docs/decisions/llm.md`).
- **Conversation summary:** `conversation.summary`, refreshed by a second model.
- **Per-tenant caps:** in `tenant_settings`, plus the monthly token cap.
- **Preference memory:** "cuando digo la sucursal es Centro".
- **Alerts:** cost spikes, 80 %/100 % of cap, cache hit rate, validator reject rate.
- **Escalation and fallback models:** escalation to a stronger model (`route="sonnet"`) and automatic switch to a fallback provider.
- **The WhatsApp webhook, HTTP endpoint and sending** (MR-21).
- **The confirmation service and `pc:` handlers.**
- **Real RPCs** (MR-31).
- **Multi-instance grouping** (see the shortcut).

## Project structure
```
apps/api/src/mermia_api/agent/
  __init__.py   answer(...) unchanged; grouping entry point exported
  broker.py     Broker protocol, StubBroker (no LLM import)
  llm_broker.py LlmBroker (imports Agno; never imported by agent/__init__.py)
  validator.py  validate(reply, *, tool_results, question, memory) -> set[Decimal]
  prompt.py     STATIC_PREFIX, tail(tenant context) -> str
  llm.py        build_model("provider:id"), prices, cost_usd, tracing setup
  grouping.py   per-chat buffer, window timer, one-in-flight, send callback
  usage.py      llm_usage insert, daily count, conversation turns read/write
apps/api/tests/agent/
  test_validator.py  example table, dates, times, formats, memory figures
  test_broker.py     fake model: pass, retry, reject, provider failure, caps, memory
  test_grouping.py   bursts, actions flush, in-flight, delivery
  test_prompt.py     prefix hash across tenants
  test_usage_db.py   -m db: llm_usage rows, daily count, conversation turns
```
File names are a proposal; the plan fixes them.

## Code style
Follow `apps/api/src/mermia_api/agent/`, as MR-26 does: small modules, a module docstring stating the why, frozen dataclasses, `Literal` for closed sets, and dependencies injected at construction. A sketch of the boundary, not final code:

```python
ValidatorResult = Literal["pass", "retry", "retry_pass", "reject"]


@dataclass(frozen=True)
class LlmBroker:
    """The LLM answers what the router did not take (09 section 4.2); a reply with a figure no
    tool returned is retried once, then replaced by the template menu."""

    model: str  # "provider:model_id"
    store: UsageStore

    def __call__(
        self, request: AgentRequest, locations: Mapping[UUID, str], rpc: RpcCall
    ) -> AgentResponse: ...
```

## Commands
- Install: `uv sync --all-packages --all-groups`
- Tests: `uv run pytest apps/api/tests/agent`
- DB tests: `MERMIA_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run pytest -m db apps/api/tests/agent`
- All checks: `.claude/skills/check/check.sh`
- Smoke eval (paid): `uv run --env-file .env mermia-eval --models <provider:id> --out apps/eval/out/mr27-smoke.json`

## Testing strategy
Tests come first (TDD), with pytest. No test calls a real model or the network; the paid smoke eval runs by hand.
- **Validator (unit, pure).**
  - One test per row of the Example table.
  - Plus every MR-20 false positive listed in `docs/decisions/llm.md`: "30" from "últimos 30 días", "9:00", "5–11 de octubre", "28 de sep - 4 de oct".
  - Plus the two real MR-20 failures, which must be rejected: the computed gap between locations and the rounding to "$184 mil".
- **Broker (unit).** A fake model built with Agno's test doubles or a scripted `agent_factory`, as `run_case` takes one, returning:
  - set replies and tool calls;
  - a raised exception;
  - a non-completed status;
  - usage metrics.

  It covers pass, retry pass, reject, provider failure, tool cap, daily cap, memory in and out of the TTL, and the tail message content. `llm_usage` and `conversation` access go through an injected fake in these tests.
- **Grouping (unit).** An injected clock and a manual timer; no real sleeps.
- **Prompt (unit).** A hash of the static prefix for two different tenant contexts.
- **DB (`-m db`).** Rows land in `llm_usage` with the right fields; the daily count uses distinct `request_id` and the Mexico City day; `conversation.last_turns` keeps 4 and is upserted on the `(tenant_id, user_id, channel)` key.
- **MR-26 tests stay green,** including the no-LLM-import check on the template path.
- **Smoke eval:** see Open questions Q4.

## Boundaries
- **Always:**
  - tests before logic;
  - every figure in a sent reply passes the validator;
  - the menu, never silence, on any failure;
  - one `llm_usage` row per call.
- **Ask first:**
  - any change to `packages/contracts` (Q1, Q2);
  - adding a dependency to `apps/api` beyond Agno and the provider SDKs the eval already uses;
  - any migration;
  - raising a cap;
  - sending any new user data to the LLM.
- **Never:**
  - let the LLM compute or round money;
  - call `apply_*`;
  - replay old tool results;
  - put tenant data in the static prefix;
  - send phone numbers, RFCs or full staff names to the LLM;
  - use the service role in the tool path.

## Decisions taken (product owner, 2026-11-05)
- **Model:** configurable behind a thin adapter. MR-27 runs only a 1-2 model smoke eval; the final run and the choice are a separate gate.
- **DeepSeek is a candidate provider** (added 2026-11-05). The adapter supports `deepseek:<id>` with thinking off, and the smoke eval includes it when a key exists. Whether its data residency (China) is acceptable for real customers is a product decision outside this ticket.
- **Agno stays.** It is contained in `llm.py` and `LlmBroker` behind `agent_factory`. Reconsider only if Checkpoint 0 shows it changes the system message with no way to turn that off.
- **Validator failure:** one silent retry, then the menu with "No pude confirmar esa cifra".
- **Validator exceptions:** it accepts dates, times, numbers from the question and numbers from earlier replies in memory.
- **Memory:** last 4 turns, no summary, 2 h expiry.
- **Caps:** constants in code.
- **Grouping:** in this ticket, option A: wait for 2.5 s of quiet, then one question.
- **Two additions:** provider failure → menu; Langfuse traces.
- **Explicitly not added:** alerts and automatic model fallback.
- **Estimate:** the larger scope is accepted, even if the 3-day estimate grows.

## Open questions (resolved 2026-11-05: each proposal accepted)
- **Q1. `route` for the LLM path.**
  - `AgentRoute` and `app.llm_route` only have `haiku` and `sonnet` for LLM answers, but the primary model is not chosen and may not be Haiku (Luna led the preliminary run).
  - **Proposal:** write `haiku` as "the primary LLM route" and keep the real model id in `llm_usage.model`.
  - **Alternative:** a contract and enum change to a neutral `llm` route, which needs both devs and a migration.
- **Q2. Where the number extraction lives.**
  - The MR-20 scorer is in `apps/eval`, which `apps/api` must not depend on (it pulls the Mock RPC and test tooling).
  - **Proposal:** move the extraction into `mermia_api.agent.validator`, and have `apps/eval` import it (eval gains a dependency on `mermia-api`), so the eval and production check numbers the same way.
  - **Alternative:** put it in `packages/contracts` (needs both devs).
  - The same question applies to `build_model`, prices and `cost_usd`.
- **Q3. Retry wording.** The retry message names the unsupported figures to the model. Is it acceptable that the model then sees which numbers were flagged? (It cannot leak them to the owner: the retry reply is validated again.)
- **Q4. What the smoke eval runs.**
  - The harness builds its own Agno agent with its own prompt.
  - To test this ticket, it should run the real broker: static prefix + tail, validator and retry.
  - **Proposal:** a `--broker` flag in `mermia-eval` that calls `LlmBroker` with the Mock RPC.
  - **Which models:** Luna, plus Haiku if the Anthropic key is ready.
- **Q5. Template answers in memory.** Proposed: yes (store the template's text as the reply). Confirm.
- **Q6. MR-26 follow-up "LLM picks, template answers".**
  - MR-26 left for MR-27 the idea that one LLM call to one of the 8 template RPCs gets its reply from `render()`.
  - The interview did not cover it. **Proposal:** out of scope; the validator already gives the safety, and the idea needs a "call covers the whole question" signal that does not exist.

## Known limits
- **Attribution:** see the Validator's known limit.
- **Numbers written in words** ("dieciocho mil") are not extracted. The prompt forbids them; a test documents the gap.
- **Prompt injection through tool data** (dish names come from SR exports): the LLM can only read through RLS-scoped tools and propose changes that a human must approve, so the blast radius is a wrong reply, which the validator limits.

## Review applied (2026-11-05)
A senior review of this spec and its plan led to these changes, approved by the product owner:
- the per-request `RpcCall` (09 D8);
- argument validation;
- the input gate;
- `llm_broker.py`;
- no money figures from the question;
- no memory questions as a source;
- the attribution limit;
- the role passed in and no cutoff in the tail;
- empty or incomplete replies → menu;
- the retry as a new run;
- `Decimal` cost;
- tracing at startup;
- `respond` never raises;
- the explicit smoke-eval pass rule;
- the failure-row `route`;
- the backend connection.

## Assumptions not confirmed
- Grouping waits 2.5 s (the interview said 2-3 s).
- Joined burst texts are separated by a newline.
- An action or media input flushes buffered text first.
- The daily cap counts questions (distinct `request_id`), not calls.
- The day is the Mexico City calendar day.
- `llm_usage.location_id` is left null for broker questions.
- The caller (MR-21) resolves the user's role and builds the per-request `RpcCall`. Until MR-31, tests and the eval use the Mock RPC caller.
- `validator_result` gets the extra value `retry` on the first row of a retried question.
- `propose_change` is offered to the model and answered with `pending_approval` without writing, as in the eval.
- The broker runs synchronously (Agno `run`) inside the grouping worker; switching to `arun` is a plan decision.
- Location names may go to the LLM (they are not phone numbers, RFCs or staff names).
