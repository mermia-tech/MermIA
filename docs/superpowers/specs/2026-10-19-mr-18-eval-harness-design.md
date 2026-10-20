# MR-18: LLM eval harness (design)

Status: draft for approval, 2026-10-19. Issue: https://github.com/mermia-tech/MermIA/issues/18. Branch: `MR-18-eval-harness`. Owner: Dev B.
Context: `docs/kickoff/13-llm-and-token-strategy.md` §H3 (eval plan), MR-19 (the 40 questions), MR-20 (the model gate).

## 1. Intent

MR-20 must choose the production LLM from data. MR-18 builds the instrument: one command that asks the same question to several models through the same tools, scores what each model did, and records every run in Langfuse. It does not choose the model and does not hold the full question set.

Why it matters: one wrong number kills the owner's trust. The harness exists so that decision rests on measured tool choice, arguments and numbers, and on cost and latency, and not on vendor claims.

## 2. Goals, non-goals, anti-goals

**Goals**
- `uv run mermia-eval` runs the example case on every configured model and prints, per model: tool score, args score, numbers score, tokens in/out, latency, cost, and the number of errored runs.
- The tools the models see are exactly the C4 definitions (`tool_definitions()`), executed against the Mock RPC.
- Each run is a Langfuse trace, with the three scores attached.
- Adding a model or a provider is a config change, not new code.

**Non-goals (left to MR-19 / MR-20)**
- The 40 questions, pass thresholds, the tone judge (LLM as judge), the routing decision, CSV output, parallel execution.
- Running the Claude models now (the Anthropic account has no credit). They stay in the config and are reported as errors until it does.
- Changing `llm_route` (database enum) or rewriting the kickoff docs.

**Anti-goals (a failure even if it "works")**
- A provider outage, a missing credit or a bad API key scored as a wrong answer. Agno does not raise on provider errors: it returns the error text as the answer with 0 tokens. The harness must detect that.
- A schema that reaches the model different from C4 (see §4.2). The eval would measure a different tool set than production.
- Secrets in logs, traces or committed files.
- Treating one run per model as a decision. It is a smoke test.

## 3. Decisions made by the team

| # | Decision |
|---|---|
| D1 | Framework: **Agno** (pinned to the installed version, 3.1.6). Models are `provider:model_id` strings; no hand-written provider adapters. |
| D2 | Candidate models (config): `openai:gpt-5.6-luna`, `openai:gpt-6.1-sol`, `anthropic:claude-haiku-5-5`, `anthropic:claude-sonnet-5-5`, `google:gemini-3.8-flash`, `google:gemini-3.5-flash-lite`. IDs verified against the three accounts on 2026-10-19. |
| D3 | Scores are reported separately (tool, args, numbers), with tokens, latency and cost beside them. **No composite score and no pass thresholds in MR-18**; MR-20 takes the thresholds from kickoff 13 §H3. |
| D4 | Tone is not scored in MR-18 (MR-20). |
| D5 | Location: new uv workspace member `apps/eval`, command `uv run mermia-eval`. |
| D6 | One case file per case, JSON, in `apps/eval/cases/`. MR-18 ships one case; the question is in Mexican Spanish. |
| D7 | Same low reasoning level for all models; temperature is not set (some reasoning models reject it). Kickoff 13 says temperature 0; this is a deliberate change so the comparison is fair across providers. |
| D8 | One shared system prompt in Spanish for all models (draft in §5). |
| D9 | Runs per model: `--runs N`, default 1 in MR-18; MR-20 uses 3. |
| D10 | Langfuse project exists and `.env` has `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` (US cloud). Cost comes from our own price table; the cost Langfuse computes per trace is a cross-check that the harness does not read (changed after the second code review). |

## 4. Verified facts about Agno (spike on 2026-10-19, Agno 3.1.6)

These were measured against the real C4 tools; the tests in the plan lock them in.

1. **Tools from a schema.** `Function(name, description, parameters=<C4 input_schema>, entrypoint=fn)`. The entrypoint is called with keyword arguments (`entrypoint(**arguments)`).
2. **Agno rewrites schemas unless told not to.** With an `entrypoint(**kwargs)` and default processing, Agno empties `required` on all 12 tools. `skip_entrypoint_processing=True` keeps them identical to C4. Do not use `strict=True` (it makes every parameter required, including optional `location_id`).
3. **What reaches Anthropic** differs slightly from C4: Agno adds `"description": ""` to every property and `"required": []` to tools with no required argument (about 620 extra characters over 12 tools). **Accepted and documented**: the eval measures a payload slightly larger than C4's token budget (125 tokens per tool). OpenAI and Gemini payloads were not byte-compared.
4. **Gemini** converts `$defs` / `anyOf` itself (`compare_periods` came out correct). Real calls to OpenAI and Gemini with `get_dish_margin` worked end to end.
5. **Run output** exposes each call as `tool_name` and `tool_args` (a dict), plus `metrics` (input, output, cached and total tokens, `duration`). `metrics.cost` is **always `None`** for these providers.
6. **Argument shape differs by provider:** OpenAI sent `location_id: null`; Gemini omitted it. The scorer treats `null` as omitted.
7. **Langfuse via OpenInference** (`AgnoInstrumentor`, OTLP with Basic auth of the two keys, endpoint `<base>/api/public/otel/v1/traces`) delivered an AGENT, GENERATION and TOOL observation per run, with model, tokens and cost already computed for `gpt-5.4-nano`. Reading traces back uses `/api/public/v2/observations` (the old traces endpoint returns 410). The exporter must be flushed before the process exits.
8. **Model IDs are not validated** by Agno; a wrong ID fails on the first request.

## 5. Behaviour

**Flow of one run.** Load the case; build the agent for `provider:model_id` with the 12 tools and the shared prompt; send the question; the model calls tools, which hit the Mock RPC (in-process, no server to start; `--mock-url` points to a running one); read the tool calls and the final text; score; send the scores to Langfuse; add to the printed table.

**Tools.** The 11 read tools call `POST /rpc/{name}` on the mock with the arguments as given. `propose_change` has no RPC: its entrypoint only records the call and returns `{"status": "pending_approval"}`, so nothing is ever written.

**Case file** (fields): `id`, `question`, `expected_tool`, `expected_args` (optional `accepted_args` alternatives, e.g. a period given as a preset or as `{from,to}`), `must_contain` (figures the reply must show). `must_contain` values are checked in a test against the mock's own answer, so the case cannot drift from the fixtures.

**Example case.** "¿Cuál es el margen de los tacos al pastor?" → `get_dish_margin(dish="tacos al pastor")`; the mock answers cost `$18.40`, gross price `$65.00`, net price `$56.03`, margin `$37.63`, margin 67.2 %, food cost 32.8 %. Kickoff 13 lists 71.7 %; that figure is stale and is **not** used.

**Scoring** (per run, each in 0..1):
- *Tool:* the expected tool was called, and no other tool. Repeated calls to the expected tool are fine (my call); any other tool name makes the score 0.
- *Args:* the arguments equal the expected (or an accepted alternative) after normalising `null` to omitted and ignoring key order.
- *Numbers:* every number in the reply appears in the tool results or in the question (kickoff 13's rule), and every `must_contain` figure is present. Formats are normalised (`$`, `,`, `%`).
- Across runs: mean per score; report the run count and errored runs. Errored runs are not scored.

**Errors.** A run is `error` when the provider call failed (Agno's error-as-answer, zero tokens, missing key, no credit, unknown model, timeout). A failing model never stops the others. Exit code is 0 unless every model errored.

**Cost.** Local price table (USD per million tokens, input / cached input / output) in the config, `null` when unknown, printed as `n/a`. Prices from kickoff 13 §H1, which covers five of the six models: Haiku 5.5 0.10 / 0.01 / 0.50; Sonnet 5.5 2.00 / 0.10 / 10.00; GPT-5.6 Luna 0.20 / 0.02 / 1.20; Gemini 3.8 Flash 0.75 / 0.075 / 3.75; Gemini 3.5 Flash-Lite 0.30 / 0.03 / 2.50 (Google announces increases from 2026-12-01). **`gpt-6.1-sol` has no verified price** (the kickoff lists only "GPT-6 Sol": 2.00 / 0.10-0.20 / 10.00); it stays `null` (`n/a`) until someone checks. Langfuse prices that model on its side, so its trace cost can be compared by hand; the harness does not read it.

**Draft system prompt (my call, in Spanish, shared by all models):** "Eres el asistente de un restaurante en México. Responde en español de México, breve y claro. Para cualquier cifra usa las herramientas; nunca inventes números. Si no existe una herramienta para lo que piden, dilo. Los cambios solo se proponen con propose_change; nunca digas que ya se aplicaron."

## 6. Constraints

- Python 3.12, uv workspace; ruff (line 100) and mypy strict apply; add `apps/eval/src` to `mypy_path`. Agno and OpenInference may lack complete typing: relax per module, not globally.
- `uv sync --locked` in CI: `uv.lock` must be updated and committed.
- Tests run offline. Anything that calls a provider or Langfuse sits behind a marker (like `tokens` today) that is off by default.
- Code, comments and docs in English; the question, the prompt and any text a customer would see in Mexican Spanish.
- `packages/contracts` stays untouched except for what MR-18 already changed (a docstring).

## 7. Calls I made (please check)

1. Mock runs in-process by default (FastAPI `TestClient`), so "one command" needs no server.
2. Case files are JSON, not YAML (no extra dependency); kickoff 13 mentions `questions.yaml`.
3. The numbers rule is kickoff 13's (every reply number must come from a tool result or the question) plus the `must_contain` figures.
4. `propose_change` is a recording stub, not Agno's confirmation flow.
5. Latency is the wall time of the whole run; percentiles are MR-20.
6. The price table lives in the config file next to the model list.
7. Exit code does not depend on scores.
8. Cost is read from the local price table, not from Langfuse (reviewer finding H7; D10 was changed to say so).

## 8. Left to the builder

- How scores attach to the Langfuse trace (OTel attributes vs the scores API) and the trace tags (run id, model, case id).
- Exact module layout inside `apps/eval`, CLI parsing library (stdlib `argparse` is enough), table formatting.
- How to select the "low reasoning" setting per provider class in Agno.
- Whether `TestClient` (sync) or an async path fits Agno's tool execution without blocking issues.
- Which per-module mypy relaxations Agno needs.

## 9. Risks

- Gemini input tokens were about 47 % higher than OpenAI's for the same tools; cost comparisons must use each provider's own counts.
- `gemini-3.1-pro-preview` and other preview IDs can change; none is in the current list.
- Agno minor releases changed schema handling before; the version is pinned and the schema tests guard it.
