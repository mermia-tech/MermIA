# LLM decision (MR-20): provisional, no model chosen

Status: **provisional, 2026-10-31.** This ticket built the gate and ran a cheap preliminary exam (1 run, 2 models). By decision of the product owner, **no primary model is chosen yet**: the choice comes from the final run below, with the same tooling. Until then the §H4 table in `docs/kickoff/13-llm-and-token-strategy.md` stays a hypothesis, and MR-26 / MR-27 keep the provider behind a thin adapter so the choice is a config change.

## Final run (how to decide)

1. **Keys in `.env`:**
   - `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, all with billing.
   - The current Google key is free tier (15 requests per minute). With it, Gemini runs hit 429 / 503, and the retries' waits inflate Gemini's latency.
   - Anthropic was never run end to end; run the smoke step (3) first.
2. **Unpause and pick the judges:**
   - Move `openai:gpt-6.1-sol` and `anthropic:claude-sonnet-5-5` from `PAUSED` back to `MODELS` in `apps/eval/src/mermia_eval/config.py`.
   - Add a price for Sol, or its cost shows `n/a`.
   - In `apps/eval/src/mermia_eval/judge.py`, set `JUDGE` and `CROSS_JUDGE` to the stronger judges, for example `anthropic:claude-sonnet-5-5` and `openai:gpt-6.1-sol`.
   - Commit these edits before running: the dump records only the git commit, not the judges or models.
3. **Smoke Anthropic:** run Haiku alone once (about US$0.02) and check that it has no errors:
   `uv run --env-file .env mermia-eval --models anthropic:claude-haiku-5-5 --out apps/eval/out/smoke.json`
4. **Run:**
   `uv run --env-file .env mermia-eval --runs 3 --judge --out apps/eval/out/final.json`
   - Scope: 6 models x 40 cases x 3 runs = 720 runs, about US$20 and one to two hours.
   - If a model ends with more than 5 % errors, rerun it alone:
     `... --models <id> --runs 3 --judge --out apps/eval/out/final-<id>.json`
5. **Report:**
   `uv run python -m mermia_eval.gate apps/eval/out/final.json apps/eval/out/final-*.json`
   A model in a later file replaces its runs from an earlier one.
6. **Human tone check:**
   `uv run python -m mermia_eval.sample apps/eval/out/final.json`
   A person scores the 10 replies from 1 to 5, and we record the agreement with the judge.
7. **Hand-check every numbers failure.** The numbers scorer has false positives (see Limitations), so at 120 runs per model it will likely fail every model on noise. List the failures:
   `uv run python -c "import json,sys; [print(r['model'], r['case_id'], '\n', r['reply'], '\n') for r in json.load(open(sys.argv[1]))['runs'] if (r['scores'] or {}).get('numbers') == 0]" apps/eval/out/final.json`
   Write down in this memo each failure you judge a false positive and why. Never pass a model on numbers without that written list.
8. **Decide:** apply the decision rule in `docs/superpowers/specs/2026-10-30-mr-20-eval-gate-design.md`:
   - **Primary:** the cheapest model that passes every threshold; a tie goes to the lower p95.
   - **Escalation:** the best model on the primary's failing categories.
   - **Fallback:** the best eligible model from another vendor.

   Then replace this memo's status and the §H4 table.

## Preliminary evidence (2026-10-31)

- **Run:** 40 cases x 1 run, GPT-5.6 Luna and Gemini 3.5 Flash-Lite, tone judge GPT-5.6 Luna with Gemini 3.5 Flash-Lite as cross judge.
- **Version:** commit `4eba334`, tools_sha256 `dffa2445…`.
- **Grading:** args regraded with the rule in "Harness changes" below.
- **Spend:** about US$0.11 in model calls plus the judge calls; all MR-20 runs together cost under US$0.30.

| Check (§H3) | GPT-5.6 Luna | Gemini 3.5 Flash-Lite | Threshold |
|---|---|---|---|
| tool | 0.95 | 0.90 | >= 0.95 |
| args | 0.95 | 0.88 | >= 0.95 |
| numbers | 0.85 | 0.97 | 1.0 |
| tone mean / min | 4.28 / 2 | 4.10 / 2 | >= 4.0 / >= 3 |
| p50 / p95 (s) | 4.3 / 7.0 | 1.8 / 3.2 | <= 3 / <= 8 |
| mean cost (USD) | 0.00034 | 0.00249 | <= 0.003 |
| errors | 0 / 40 | 0 / 40 | <= 5 % |

**Neither model passes.** What each run showed:

- **Luna:**
  - **Numbers:** 6 failures, and only 2 are real.
    - **Real:** it computed money itself, which §H3 forbids: the gap between locations "$23,399.70" (`locations_this_month_sales`) and a rounding to "$184 mil" (`adversarial_round_sales`).
    - **Scorer false positives:** "30" quoted from "últimos 30 días", the time "9:00" from the tool's `as_of`, a dash range "5–11 de octubre", and a date it worked out ("jueves 15 de octubre").
    - **Missing figure:** one reply left out a `must_contain` figure ($18.40, `tacos_al_pastor`).
  - **Speed:** it is slow (p50 4.3 s).
  - **Ambiguity:** it asks back on all 3 ambiguous questions, and it says when tool data does not match the request.
  - **Cost:** about 7 times cheaper per question.
- **Flash-Lite:**
  - **Numbers:** its only failure (0.97) is a scorer false positive: tool dates written as "28 de sep - 4 de oct".
  - **Ambiguity:** it answers all 3 ambiguous questions instead of asking (tool 0 / 3).
  - **Cost:** it goes over the cost threshold on sales and top-dishes questions.

**Not measured:**
- **Haiku 5.5:** no Anthropic key.
- **Gemini 3.8 Flash:** the free-tier key returned 503 on every call.
- **Sol and Sonnet:** paused to save budget.

**Tone:**
- **Judges:** on Luna's 40 replies, the judge and the cross judge agree exactly on 22 and within one point on 34.
- **Human check:** pending; the product owner scores the 10 sampled replies (`mermia_eval.sample`).

## Harness changes made after the first look (thresholds unchanged)

The §H3 thresholds were not changed. Four grading and robustness changes were made after reading the failures; each has a test.

- **Args, first call only:** only the first call to the expected tool is scored. The Mock RPC answers every call with the same fixture, so a model that checks the data and calls again with other args was failing for reacting to wrong data. 10 of the 17 args failures were this, or the next item; the other 7 were real. `score_tool` still checks every call.
- **Args, all locations:** naming every location in `location_ids` scores the same as naming none (C3: no location means all).
- **Numbers, prompt dates:** the dates in the prompt (today 2026-10-12, data until 2026-10-11) are not counted as invented numbers. Other dates the model works out ("jueves 15 de octubre") still count.
- **Robustness:**
  - Model calls time out after 60 s; a stuck Gemini request hung a whole run.
  - Gemini retries 429 / 503 three times (10, 20, 40 s), and the measured seconds include those waits.

## Limitations

- **Fixed mock:** the mock ignores args, so replies can quote figures for the wrong period, location or dish, and the numbers score cannot see it. The fix is the follow-up below.
- **First-call args rule:** later calls are no longer scored, even when wrong. In this run Flash-Lite asked for the wrong week in a third call (`sales_avg_ticket`) and narrowed to one location in a second call (`ops_sales_by_waiter`), and both still score args 1.0. Go back to scoring every call once the mock answers from its args.
- **Numbers false positives:** the scorer flags figures quoted from the question in words, times, dash ranges and abbreviated months ("sep"). Hence the hand-check in step 7.
- **Figure checks:** only 11 of 40 cases have `must_contain` figures.
- **Dump contents:** the dump keeps the calls, the reply and the scores, not the tool results or tokens. A numbers-scorer fix after the final run can be regraded only by replaying the fixed mock.
- **Judge cost:** the judge calls are not priced in the report.
- **Latency:** it includes the in-process mock, not the real database or WhatsApp.
- **One run:** a single run hides flaky models.

## Routing table

Not decided: the §H4 hypothesis stands until the final run. One routing observation for MR-27: the backend should return precomputed differences (`diferencia`, `cambio_pct`), so that no model needs to subtract money.

## `app.llm_route`

Unchanged (D4). If the final primary is not Haiku / Sonnet, migrate the enum to role names (`primary`, `escalation`) in a follow-up.

## MR-27 smoke run on the real broker (2026-11-05)

`uv run --env-file .env mermia-eval --broker --models openai:gpt-5.6-luna,deepseek:deepseek-flash`, 40 cases, 1 run, no judge. Each case goes through `LlmBroker`: the MR-27 static prefix and tail, 400 output tokens, at most 4 tool calls, the validator and one retry. Dumps: `apps/eval/out/mr27-smoke.json` (first) and `mr27-smoke-2.json` (after the prompt fix). Spend: about US$0.06 for both runs.

| Check | Luna, run 1 | Luna, run 2 | DeepSeek Flash, run 2 | MR-20 Luna | Threshold |
|---|---|---|---|---|---|
| tool | 0.56 | 0.90 | 0.86 | 0.95 | >= 0.95 |
| args | 0.54 | 0.82 | 0.86 | 0.95 | >= 0.95 |
| numbers (sent replies) | 0.90 | 0.97 | 0.97 | 0.85 | 1.0 |
| menu answers | 1 / 40 (provider) | 0 / 40 | 5 / 40 (reject) | - | <= 5 % |
| p50 / p95 (s) | 3.0 / 8.6 | 4.1 / 7.3 | 2.9 / 4.4 | 4.3 / 7.0 | <= 3 / <= 8 |
| mean USD per question | 0.00027 | 0.00037 | 0.00049 | 0.00034 | <= 0.003 |

- **Run 1 found a prompt regression.** The prefix said "si la pregunta es ambigua (sucursal, periodo o platillo), pregunta antes de responder", which the MR-20 prompt did not have. Luna asked "¿de qué sucursal?" on 14 of 40 questions, "¿cuánto vendí ayer?" among them. The rule is now "si no dice sucursal, usa todas las suyas; pregunta solo si falta algo que no se puede suponer". The retry message also leaked: DeepSeek began a reply with "Tienes razón en el señalamiento"; the correction now says it is internal.
- **Validator, run 2:** 63 pass, 17 retry (12 retry_pass, 5 reject). No sent reply carried an unsourced figure. The two numbers failures are the known scorer false positive on "09:00" and "100.0%" (MR-67), on replies the validator passed.
- **Not met: tool and args >= 0.95,** and DeepSeek's menu share (12.5 %). Most of the remaining misses are the fixed-fixture mock (MR-67): the models notice that the data does not match the request ("la herramienta devolvió ventas netas, no ticket promedio", "no encontré tacos de bistec") and say so instead of answering. The other misses: Luna answers "¿cómo van mis sucursales?" without asking for the periods (the new rule lets it assume them), and DeepSeek asks for the price before calling a write tool.
- **Not verified:** why DeepSeek's 5 replies were rejected twice. The dump keeps only the menu; the rejected texts are in the Langfuse traces. Read them before DeepSeek is considered for the primary route.
- **Output cap:** DeepSeek reached the 400-token cap twice in run 1 (menu), none in run 2. Luna never did, so OpenAI's reasoning tokens fit in 400 at low effort.
- This is a smoke run (1 run each, fixed mock), not the model decision: that stays with the final run (MR-68).

## Follow-ups

- **Final LLM eval run (MR-68):** the steps above. It needs paid keys for all three vendors.
- **Mock RPC that answers from the args (MR-67):** this fixes the args and numbers blind spots above. It is a follow-up from MR-19 D1.
- **Numbers scorer false positives (MR-67):** quoted words from the question, times, dash ranges, abbreviated months. Fix before the final run, or hand-check as in step 7.
