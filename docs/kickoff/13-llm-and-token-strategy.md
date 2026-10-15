# 13 - LLM selection and token strategy (sections H and I)

Research date: 2026-10-15. Prices are USD per 1M tokens (MTok) from official pages fetched today. Labels: **verified** = read on an official page today; **likely** = from a secondary source or inferred; **unverified** = not found, must be checked.

## Key findings & recommendation

- **Primary: Claude Haiku 5.5** ($0.10 in / $0.50 out, cache read $0.01, batch $0.05/$0.25). Released 2026-10-07 (8 days old), so independent tool-calling and Spanish evidence is thin. **Verified** price; quality **unverified until the eval (below) is run**.
- **Escalation: Claude Sonnet 5.5** ($2 / $10, cache read $0.10) for multi-step or ambiguous questions, DB-change proposals, and anything Haiku fails in the eval. About 20x Haiku per token, so route only about 15% of LLM calls to it.
- **Fallback (different vendor, same price class): GPT-6 Luna** ($0.10 / $0.50, cached $0.01) or **Gemini 3.5 Flash-Lite** ($0.30 / $2.50, cached $0.03). Keep a thin provider adapter so a switch is a config change. Open-weight (gpt-oss-120b at $0.15/$0.60, Qwen3.8 Flash, DeepSeek V4 Flash on Together) is a cost-floor challenger, not a launch choice.
- **The model is not the main cost lever; architecture is.** Templates with zero LLM calls, tool results that are small and pre-formatted, and a cached static prefix take typical cost to about **US$0.66 (about MXN 11.5) per restaurant per month**. Naive design (full history, no cache, no routing, Sonnet) is about 20x more (table in I).
- **Numbers never come from the model.** The tool result carries pre-formatted strings; the reply is built with placeholders filled by code, and a post-check rejects any number not present in the tool output. This is the main answer to owner trust risk.
- **Caching works for us only if the prefix is identical across tenants** (system prompt + tool defs, no restaurant name, no timestamp). Minimum cacheable size on Haiku 5.5 / Sonnet 5.5 is only 512 tokens (**verified**), so our prefix qualifies. Put tenant and date in a tail message (ProjectDiscovery moved dynamic content to the tail and got hit rate 7.6% to 73.7%, **verified**).
- **Target budget:** typical restaurant at or below US$1.00 (MXN 18) per month, heavy at or below US$3.00 (MXN 53), enforced by per-tenant daily caps and metered from day one.
- **Must be confirmed by running the eval before the agent is built:** Haiku 5.5 tool-selection and argument accuracy, Spanish tone, latency p95 on WhatsApp, and Haiku vs Luna vs Flash-Lite on the same 40 questions.

---

## H. LLM selection

### H1. Candidate comparison

Prices **verified** from the sources in H6 unless noted. "Cached" = cache-read / cached-input price. Batch = 50% for Anthropic, OpenAI and Google (**verified**).

| Model | Tier | Input | Cached | Output | Batch (in/out) | Context | Notes |
|---|---|---|---|---|---|---|---|
| Claude Haiku 5.5 | cheap | 0.10 | 0.01 | 0.50 | 0.05 / 0.25 | not stated on pages read (**unverified**); price steps up above 100k-token prompts | Cache write 5m 1.25x (0.125), 1h 2x (0.20). Min cache 512 tok. |
| Claude Sonnet 5.5 | mid | 2.00 | 0.10 | 10.00 | 1 / 5 | 1M at flat price (**verified**) | Cache min 512 tok. |
| Claude Opus 5.5 | top | 4.00 | 0.20 | 20.00 | 2 / 10 | 1M | Not needed for Phase 1. |
| GPT-6 Luna | cheap | 0.10 | 0.01 | 0.50 | 0.05 / 0.25 | short tier up to 272K | Same price as Haiku 5.5. |
| GPT-5.6 Luna | cheap | 0.20 | 0.02 | 1.20 | 0.10 / 0.60 | 272K short tier | Superseded by GPT-6 Luna on price. |
| GPT-5.4 nano / mini | cheap/mid | 0.20 / 0.75 | 0.02 / 0.075 | 1.25 / 4.50 | 50% | 272K short tier | Older generation. |
| GPT-6 Sol | mid | 2.00 | 0.10-0.20 | 10.00 | 1 / 5 | 272K short tier | Comparable to Sonnet 5.5. |
| Gemini 3.5 Flash-Lite | cheap | 0.30 | 0.03 | 2.50 | 0.15 / 1.25 | not on page | Storage fee $1.00/MTok/h for explicit cache. |
| Gemini 3.1 Flash-Lite | cheap | 0.25 | 0.025 | 1.50 | 0.125 / 0.75 | not on page | |
| Gemini 3.6 / 3.8 Flash | mid | 0.75 | 0.075 | 3.75 | 0.375 / 1.875 | not on page | Prices rise 2026-12-01 / 2027-01-01 per page. |
| gpt-oss-120b (Together; Fireworks same per secondary source) | open | 0.15 | n/a | 0.60 | not shown | 128K likely | **Verified** Together; Fireworks **likely**. |
| Qwen3.8 Flash (Together) | open | 0.15 | n/a | 0.47 | not shown | not shown | Verified price. |
| DeepSeek V4 Flash 0731 (Together) | open | 0.14 | n/a | 0.28 | not shown | not shown | Use a US/EU host, not DeepSeek's own API (data location). |

Not found: Groq and Fireworks/DeepInfra official price pages (Groq page had no prices; DeepInfra figures only from aggregators). OpenRouter listing did not show these families.

### H2. Qualitative criteria

| Criterion | Evidence | Label |
|---|---|---|
| Tool-calling reliability | tau2-bench Retail (aggregator): Sonnet 4.6 91.7%, Opus 4.6 91.9%, Haiku 4.5 83.2% ([anotherwrapper](https://anotherwrapper.com/tools/llm-pricing/evals/tau2-retail)). Older tau-bench retail: Gemini 2.5 Flash 61.5% vs Sonnet 4.5 67.3% ([requesty](https://requesty.ai/models/compare/anthropic--claude-sonnet-4-5/google--gemini-2-5-flash)). BFCL v4, Mar 2026 snapshot: Opus 4.6 77.0, GLM-5 70.8, MiniMax M2.7 70.6, Kimi K2.5 68.3 ([benchlm](https://benchlm.ai/benchmarks/bfcl-v4)); official board last updated 2026-04-12 ([Berkeley](https://gorilla.cs.berkeley.edu/leaderboard.html)), scores not readable via fetch. | **likely** for older models; **unverified** for Haiku 5.5, Luna, Flash-Lite, gpt-oss. Anthropic's Haiku 5.5 launch post lists no tool-use benchmark ([post](https://www.anthropic.com/news/claude-haiku-5-5)). Run the eval. |
| Spanish quality | No Spanish-specific scores found for any candidate. MMLU-ProX (29 languages) reports strong results in high-resource languages, with large drops only in low-resource ones ([paper](https://arxiv.org/abs/2503.10497)). Spanish is high-resource. No evidence on Mexican register. | **unverified** for Mexican tone. Eval rubric covers it. |
| Numeric fidelity | Not benchmarked for tool-fed answers; mitigated by design (numbers injected by code). | design control |
| Latency | Anthropic calls Haiku 5.5 its fastest model; partners report about 2x faster per turn vs Haiku 4.5 ([post](https://www.anthropic.com/news/claude-haiku-5-5)). No time-to-first-token or tokens/sec figures for any candidate. | **likely** (vendor claim); measure p50/p95 in eval |
| Rate limits | Anthropic Start tier: Haiku 5.5 and Sonnet 5.5 1,000 RPM, 2M ITPM, 400k OTPM; Build 5,000 RPM / 5M / 1M; **cache reads do not count toward ITPM** ([docs](https://platform.claude.com/docs/en/api/rate-limits)). Start tier spend cap $500/month. OpenAI, Google: not checked. | Anthropic **verified**; others **unverified** |
| Training on data | Anthropic: retained data never used for training without permission ([docs](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)). OpenAI: API data not used for training unless opted in ([docs](https://developers.openai.com/api/docs/guides/your-data)). Gemini paid tier: not used to improve products; free tier is ([terms](https://ai.google.dev/gemini-api/terms)). Open-weight hosts: not checked, host-specific. | verified for the first three |
| Retention / ZDR | Anthropic: ZDR by arrangement; standard commercial retention period not read (**unverified**, check [policy](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)). OpenAI: abuse logs up to 30 days, ZDR / modified abuse monitoring on approval, +10% for regional processing. Google paid: logged "for a limited period" (length unstated), ZDR not mentioned. | verified as stated |

Data-sensitivity note: sales aggregates are business data, not personal data. Customer phone numbers and employee names should not be sent to the LLM; tools return IDs or first names only. Confirm LFPDPPP transfer wording with counsel (see risk doc).

### H3. Evaluation plan

**Set:** 40 questions, run 3 times each at temperature 0 (flakiness), against a **mock tool backend** returning fixed JSON from a fixture restaurant (so numbers are known). Two devs can build it in about 1 day.

**Categories (count):**

| # | Category | n |
|---|---|---|
| 1 | Sales totals and comparisons (day, week, month, WoW, vs same weekday) | 7 |
| 2 | Top and bottom dishes (by units, revenue, margin) | 6 |
| 3 | Dish cost and margin, food-cost % | 6 |
| 4 | Staff, shifts, payment types, discounts, cancellations | 4 |
| 5 | Multi-location comparison | 3 |
| 6 | Ambiguous or underspecified ("¿cómo vamos?") - should ask or default sensibly | 3 |
| 7 | Write proposals (change cost, price, recipe) - must call `propose_change`, never claim it applied | 4 |
| 8 | Out-of-scope / data missing / tool returns empty or error - must not invent | 4 |
| 9 | Adversarial: user states a wrong number, asks to "redondear", asks for a forecast the tools cannot give | 3 |

**10 concrete examples** (fixture: "Taquería El Güero", location `L1`; "última semana" = 2026-10-05..11, previous = 09-28..10-04; tool names and arguments follow the RPC list in 09 §4.1):

| # | User (Mexican Spanish) | Expected tool call | Expected answer must contain |
|---|---|---|---|
| 1 | ¿Cuánto vendí la semana pasada? | `get_sales_summary(period="last_week", location_id="L1")` | `$184,320.50` |
| 2 | ¿Subió o bajó contra la semana anterior? | `compare_periods(metric="net_sales", period_a="last_week", period_b="prev_week")` | `+7.2%` (`$184,320.50` vs `$171,905.00`) |
| 3 | ¿Cuáles son mis 5 platillos más vendidos este mes? | `get_top_dishes(period="this_month", metric="units", limit=5)` | the 5 names and unit counts in tool order |
| 4 | ¿Cuál es el margen de los tacos al pastor? | `get_dish_margin(dish="tacos al pastor")` | cost `$18.40`, price `$65.00`, margin `71.7%` |
| 5 | ¿Qué platillo me deja menos ganancia? | `get_top_dishes(period="this_month", metric="margin_pct", order="asc", limit=1)` | dish name and its margin as returned |
| 6 | ¿Cuánto fue mi food cost de ayer? | `get_food_cost_pct(period="yesterday")` | `31.4%` and a note if cost data is incomplete (tool flag) |
| 7 | ¿Cuántas cancelaciones hubo el sábado y de quién? | `get_cancellations(period={from:"2026-10-10", to:"2026-10-10"}, kind="cancellations")` | count and waiter first names from tool; no invented reasons |
| 8 | Compárame Centro contra Polanco este mes | `compare_locations(metric="net_sales", period="this_month", location_ids=["L1","L2"])` | both totals and the difference as returned |
| 9 | El pastor ya me cuesta $220 el kilo de carne, cámbialo | `propose_change(kind="ingredient_price.set", target="carne al pastor", values={unit_price: 220.00, unit: "kg"})` | states it is a **proposal**, shows old vs new, asks confirmation; no "listo, actualizado" |
| 10 | Dime cuánto voy a vender en diciembre | no sales tool; may call `get_sales_summary` for context | says it cannot forecast; gives no invented figure |

**Scoring rubric (per run, 0/1 unless noted):**

| Dimension | Check | Weight |
|---|---|---|
| Tool selection | Correct tool(s), no extra calls, no call when none needed | 25% |
| Args correctness | Exact enum/period values, location, limit; schema-valid | 20% |
| Numeric fidelity | Every number in reply appears in tool output (after format normalisation); no number without a tool source. **Any violation fails the run** | 30% |
| Tone / Spanish | 1-5 by LLM judge (a stronger model, rubric: Mexican register, "tú/usted" consistency, concise, no anglicisms, emoji at most 1) plus human review of 10 samples | 10% |
| Latency | End-to-end LLM time (all calls) p50 and p95 | 10% (pass/fail) |
| Cost | Tokens x price per question, from API `usage` | 5% (pass/fail) |

**Pass thresholds (primary model):** tool selection >= 95%; args >= 95%; numeric fidelity **100%** (zero hallucinated numbers in the 40x3 runs); tone mean >= 4.0/5 and no run below 3; p50 <= 3 s and p95 <= 8 s for the LLM portion; average cost <= US$0.003 per Haiku-routed question. Route to Sonnet any category scoring below threshold on Haiku.

**How to run:** a single script `evals/run_eval.py`:
1. Load `questions.yaml` (id, text, category, expected_tools, expected_args, must_contain, must_not_contain).
2. Provider adapter `call(model, system, tools, messages) -> {tool_calls, text, usage, latency}` for Anthropic, OpenAI, Google and an OpenAI-compatible host (Together).
3. Loop: send question, execute tool calls against the mock backend, feed results, get final text (cap 4 calls).
4. Score: compare tool names/args to expected (JSON equality on whitelisted keys); extract numbers from the reply with a regex (`\$?\d[\d,]*\.?\d*%?`), normalise (strip `$` and `,`), assert each is in the set of numbers in tool outputs or in the user message; check `must_contain` / `must_not_contain`.
5. Tone: LLM judge with fixed rubric, temperature 0, human spot check.
6. Output a CSV (model x category x metric) and a summary; run with `~/.claude-shared/bin/quiet`-style one-line pass/fail.

Run Haiku 5.5, Sonnet 5.5, GPT-6 Luna, Gemini 3.5 Flash-Lite, gpt-oss-120b, Qwen3.8 Flash. Estimated eval cost: 40 x 3 x 6 models x about US$0.005 = about US$4.

### H4. Recommendation and routing

| Role | Model | Why | Confirm by eval |
|---|---|---|---|
| Primary (80-90% of LLM calls) | Claude Haiku 5.5 | Lowest verified price among major closed models tied with GPT-6 Luna; cache read $0.01; Anthropic cache-aware ITPM; same vendor as escalation so prompts and tool schemas are portable | tool accuracy, Spanish, latency |
| Escalation | Claude Sonnet 5.5 | Strong tool-use lineage (Sonnet 4.6 91.7% tau2 retail, likely); $2/$10 is acceptable for 10-15% of calls | whether Haiku is enough alone |
| Fallback (outage / quality) | GPT-6 Luna, else Gemini 3.5 Flash-Lite | Same price class, different vendor; avoids single-vendor outage | parity with Haiku |
| Challenger | gpt-oss-120b / Qwen3.8 Flash on Together | About same input price, no cache discount shown, retention terms unchecked; only worth it if it matches Haiku and removes vendor risk | all dimensions |

**Routing rules (deterministic, no LLM classifier at first):**
1. Intent router (keywords, button payloads, regex) -> templated answer, zero LLM (see I).
2. Everything else -> Haiku 5.5 with the full tool set.
3. Escalate to Sonnet 5.5 when: Haiku returns no valid tool call twice, the question needs more than 2 tool calls, any `propose_change` write flow, or the user says the answer is wrong.
4. Fallback provider on 5xx / 429 after one retry.

Rationale for routing: RouteLLM reports 85% (MT-Bench), 45% (MMLU) and 35% (GSM8K) cost reduction at 95% of GPT-4 quality ([LMSYS](https://www.lmsys.org/blog/2024-07-01-routellm/), **verified**; general chat benchmarks, not ours).

### H5. Risks specific to the choice

- Haiku 5.5 is 8 days old; third-party tool-use results do not exist yet (**unverified**). The eval is the gate.
- Haiku 5.5 is priced by prompt length (higher above 100k tokens): irrelevant at our 3-6k prompts, but never feed raw data.
- Claude 4.7+ tokenizer yields about 30% more tokens for the same text ([pricing page](https://platform.claude.com/docs/en/about-claude/pricing)); Spanish already tokenizes longer than English. Measure real token counts with the API `usage` field, not estimates.
- Gemini prices are scheduled to rise on 2026-12-01 and 2027-01-01 (page note); re-check any fallback price before committing.

### H6. Sources

[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) | [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | [Anthropic rate limits](https://platform.claude.com/docs/en/api/rate-limits) | [Haiku 5.5 launch](https://www.anthropic.com/news/claude-haiku-5-5) | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) | [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) | [Gemini terms](https://ai.google.dev/gemini-api/terms) | [Together pricing](https://www.together.ai/pricing) | [Anthropic data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)

---

## I. Token cost and a lean agent

### I1. Techniques and fit

| Technique | How it works / evidence | Fit for MermIA |
|---|---|---|
| **Thin broker agent** | Keep raw data and intermediate results out of the context. Anthropic reports code execution cut a workflow from 150,000 to 2,000 tokens (98.7%), because tool definitions and intermediate results otherwise flow through the model ([Anthropic](https://www.anthropic.com/engineering/code-execution-with-mcp), **verified**). | Validated in principle. **Challenge:** add a validator layer: server checks tool args against schema and the user's role before running; reply post-check rejects numbers not in tool output. Broker alone is not enough for trust. |
| **Small tool schemas** | Tool defs are sent every call. Target 10-14 tools, one-line descriptions, enums for periods/metrics, no free-text SQL. Budget about 125 tokens per tool (08 C4). | Yes. Define in the contract doc; measure with `count_tokens`. |
| **Prompt caching** | Cached prefix (tools, then system, then messages) read at 0.1x base (0.05x on Sonnet 5.5 / Opus 5.5, 0.025x on Fable 5.1); 5-min write 1.25x, 1-hour 2x; exact byte match; lookback 20 blocks ([Anthropic](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), **verified**). Real result: ProjectDiscovery hit rate 7% to 84%, cost -59%, by three breakpoints and moving dynamic content to the tail ([blog](https://projectdiscovery.io/blog/how-we-cut-llm-cost-with-prompt-caching), **verified**). | Yes, biggest per-call lever. Same prefix for all tenants so any tenant's traffic keeps it warm; use 1-hour TTL for the static prefix if traffic is sparse. |
| **Cache minimums by provider** | Anthropic: 512 tokens for Haiku 5.5 / Sonnet 5.5 / Opus 5.5 / Fable 5.x; 1,024 for Sonnet 5 / 4.x; 2,048 for Opus 4.7 / Haiku 3.5; 4,096 for Haiku 4.5 / Opus 4.5-4.6 (**verified**). OpenAI: cached-input price exists; minimum not re-checked (**unverified**; historically 1,024). Google: implicit caching; minimum not on page (**unverified**). | Our prefix of 2.5-3k tokens clears all of them. |
| **Short memory** | Keep last 3-4 turns verbatim plus a rolling summary (about 150-300 tokens) refreshed by Haiku every 8-10 turns or on topic change. Never replay tool results from earlier turns; store only the final answer. | Yes. Uncached history is the second biggest cost after the prefix. |
| **Intent router + templates** | Top questions (ventas de ayer / semana, top platillos, food cost, comparar semana) are matched by buttons, list messages and regex; tool called directly; reply is a Spanish template filled by code. Zero LLM tokens, lowest latency, no hallucination. | Yes. Expect 30-45% of traffic (**unverified, measure in pilot**). WhatsApp interactive buttons make this easy. |
| **Proactive reports in code** | Daily/weekly summary is built by code from metric RPCs into a template. LLM optional for one-sentence "insight" wording, via Batch API. | Yes. Default: no LLM; optional Haiku batch at about US$0.0002 per report. |
| **Batch API** | 50% off input and output for async jobs ([Anthropic](https://platform.claude.com/docs/en/about-claude/pricing), **verified**); same discount at OpenAI and Google. Stacks with caching. Not for interactive replies. | Yes for scheduled wording, weekly insights, summary refresh. |
| **Model routing** | See H4; RouteLLM 35-85% savings at 95% quality on general benchmarks ([LMSYS](https://www.lmsys.org/blog/2024-07-01-routellm/)). | Yes, rule-based. |
| **Per-restaurant budgets** | Daily LLM-question cap, monthly token cap, per-message output cap (`max_tokens` 400), tool-loop cap (4 calls). Over cap: fall back to menu of templated questions, never silence. Workspaces/keys: Anthropic allows per-workspace spend and rate limits ([docs](https://platform.claude.com/docs/en/api/rate-limits)). | Yes. Enforce in our gateway, per tenant. |
| **Structured outputs / compact results** | Tools return small JSON with pre-rounded, pre-formatted strings (`"ventas":"$184,320.50"`, `"cambio_pct":"+7.2%"`), max about 400 tokens, top-N only. Force `tool_choice` where the router already knows the tool. | Yes. Note: changing `tool_choice` invalidates system and tool cache (**verified**), so keep it constant per route. |
| **Numbers never generated by LLM** | The prompt tells the model to copy values verbatim; code validates reply digits against tool output; on mismatch, retry once, else send the template version. | Mandatory. |

Other write-ups found but not verified (vendor/SEO guides, no methodology): [Unblocked](https://getunblocked.com/blog/reduce-ai-token-costs/), [Maxim](https://www.getmaxim.ai/articles/reducing-llm-costs-in-production-the-complete-guide.md), [Redis](https://redis.io/blog/token-budget-aware-llm-reasoning/) (**unverified**).

### I2. Token estimates per interaction

Assumptions (Claude tokens, Spanish; all **our design targets**, to be measured with `usage`):

| Item | Tokens |
|---|---|
| System prompt (role, rules, tone, number policy) | 1,200 |
| Tool definitions (12 tools x about 125) | 1,500 |
| Cached prefix (system + tools) | 2,700 |
| Memory summary + last turns | 300 |
| User message | 40 |
| Tool result (compact) | 400 |
| Call 1 output (tool call) | 60 |
| Call 2 output (answer) | 150 |

**Typical question on Haiku (2 calls):** cache reads 2 x 2,700 = 5,400; uncached input 340 (call 1) + 800 (call 2) = about 1,140; output about 210.
**Complex question on Sonnet (3 calls):** cache reads 8,100; uncached input about 2,500; output about 500.

| Scenario | Calc (USD per question) | Cost |
|---|---|---|
| Haiku 5.5, warm cache | 5,400 x 0.01 + 1,140 x 0.10 + 210 x 0.50 (per MTok) | **$0.00027** |
| Haiku 5.5, cold cache (write 2,700 x 0.125) | + $0.00034 | $0.0006 |
| Sonnet 5.5, 2 calls | 5,400 x 0.10 + 1,140 x 2 + 210 x 10 | $0.0049 |
| Sonnet 5.5 complex, 3 calls | 8,100 x 0.10 + 2,500 x 2 + 500 x 10 | $0.0108 |
| Gemini 3.5 Flash-Lite | 5,400 x 0.03 + 1,140 x 0.30 + 210 x 2.50 | $0.0010 (excl. thinking tokens) |
| Naive: Sonnet 5.5, 8k uncached input x 2 calls, full history | 16,000 x 2 + 210 x 10 | $0.034 |

### I3. Monthly LLM cost per restaurant

Assumptions: 35% of questions answered by router/templates (zero LLM); of LLM questions 85% Haiku ($0.00027), 15% Sonnet complex ($0.0108) giving a blended $0.00185; cold-cache and summary-refresh overhead +15%; proactive reports in code, optional Haiku batch wording about $0.0002 each (1 daily + 1 weekly insight, about $0.01-0.10/month). FX: **1 USD = 17.5 MXN** (**likely**: sources showed 17.4-17.5 in late July 2026; no reliable quote for 2026-10-15 found; x-rates fetch returned a stale January value; [pluang](https://pluang.com/en/tools/currency-converter/usd-mxn)). Re-check before pricing the product.

| Usage | Questions/month | LLM-handled | LLM cost | + proactive, +15% | USD/month | MXN/month |
|---|---|---|---|---|---|---|
| Low (about 5/day) | 150 | 98 | $0.18 | $0.22 | **0.22** | **3.9** |
| Typical (about 15/day) | 450 | 293 | $0.54 | $0.66 | **0.66** | **11.5** |
| Heavy (about 40/day, multi-location) | 1,200 | 780 | $1.44 | $1.77 | **1.77** | **31.0** |
| Typical, all-Sonnet, no templates, cached | 450 | 450 | $2.2 | about $2.6 | 2.6 | 46 |
| Typical, naive (no cache, full history, Sonnet) | 450 | 450 | $15.3 | about $15.5 | 15.5 | 271 |

Sensitivity: if Sonnet share doubles to 30% of LLM calls, typical becomes about US$1.1 (MXN 19); if Haiku-only passes the eval, typical is about US$0.25. Image/PDF report reading (OCR of photos) is not included; price separately. Voice notes are not included either.

### I4. Target budget and production measurement

**Targets:** typical <= US$1.00 (MXN 18)/restaurant/month; heavy <= US$3.00 (MXN 53); blended LLM cost < 5% of subscription price (price not set; see pricing doc); cache hit rate >= 80% of input tokens; templated share >= 30%; Sonnet share <= 15% of LLM calls.

**Metering (build in week 1):**
- Gateway wrapper around every LLM call writes one row to `llm_usage`: `tenant_id, location_id, user_id, ts, request_id, route (template/haiku/sonnet/fallback), model, input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, cost_usd (computed from a versioned price table), latency_ms, tool_calls, validator_result, error`. Token fields come straight from the API `usage` object.
- Daily rollup per tenant: questions, LLM share, cost, p95 latency, cache hit rate, validator rejects.
- Dashboard (Metabase or Grafana on the same Postgres): cost per tenant per day/month, cost per question, route mix, cache hit rate, top 10 tenants by cost, p50/p95 latency, escalation rate, number-mismatch rate.
- **Alerts:** tenant > 3x its 7-day average daily cost; tenant at 80% and 100% of monthly cap; cache hit rate < 60% over 1 hour (prefix drift, probably a deploy that changed the prompt); validator reject rate > 2%; provider 429/5xx > 2% (switch to fallback); Anthropic spend vs cap (Start tier $500/month, [docs](https://platform.claude.com/docs/en/api/rate-limits)).
- Cross-check monthly: our computed cost vs the provider invoice/Console usage page; difference > 5% means the price table or token fields are wrong.
- Limits per tenant (configurable): 60 LLM questions/day, 400 output tokens/answer, 4 tool calls/question, 1 request in flight per chat; on cap show the template menu.
- Re-run the eval on every prompt/tool-schema change and on every model version change (CI job, about US$1 per run).

### I5. Open items to confirm

1. Run the eval (H3) and fix the final routing table.
2. Measure real token counts of the Spanish system prompt and tool schemas (Claude 4.7+ tokenizer inflation).
3. Confirm the Anthropic standard commercial retention period and whether to request ZDR for the pilot.
4. Get OpenAI/Google rate limits and cache minimums if the fallback is activated.
5. Re-check USD/MXN on the day the price list is fixed.
