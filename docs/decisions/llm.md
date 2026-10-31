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
7. **Decide:** apply the decision rule in `docs/superpowers/specs/2026-10-30-mr-20-eval-gate-design.md`:
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
  - **Numbers:** it computes money itself ("$15,679.50 abajo", "+$12,415.50"), which §H3 forbids.
  - **Speed:** it is slow (p50 4.3 s).
  - **Ambiguity:** it asks back on all 3 ambiguous questions, and it says when tool data does not match the request.
  - **Cost:** about 7 times cheaper per question.
- **Flash-Lite:**
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

- **Args, first call only:** only the first call to the expected tool is scored. The Mock RPC answers every call with the same fixture, so a model that checks the data and calls again with other args was failing for reacting to wrong data. 11 of the 17 args failures were this, or the next item. `score_tool` still checks every call.
- **Args, all locations:** naming every location in `location_ids` scores the same as naming none (C3: no location means all).
- **Numbers, prompt dates:** the dates in the prompt (today 2026-10-12, data until 2026-10-11) are not counted as invented numbers. Other dates the model works out ("jueves 15 de octubre") still count.
- **Robustness:**
  - Model calls time out after 60 s; a stuck Gemini request hung a whole run.
  - Gemini retries 429 / 503 three times (10, 20, 40 s), and the measured seconds include those waits.

## Limitations

- **Fixed mock:** the mock ignores args, so replies can quote figures for the wrong period, location or dish, and the numbers score cannot see it. The fix is the follow-up below.
- **Figure checks:** only 11 of 40 cases have `must_contain` figures.
- **Latency:** it includes the in-process mock, not the real database or WhatsApp.
- **One run:** a single run hides flaky models.

## Routing table

Not decided: the §H4 hypothesis stands until the final run. One routing observation for MR-27: the backend should return precomputed differences (`diferencia`, `cambio_pct`), so that no model needs to subtract money.

## `app.llm_route`

Unchanged (D4). If the final primary is not Haiku / Sonnet, migrate the enum to role names (`primary`, `escalation`) in a follow-up.

## Follow-ups

- **Final LLM eval run:** the steps above. It needs paid keys for all three vendors.
- **Mock RPC that answers from the args:** this fixes the args and numbers blind spots above. It is a follow-up from MR-19 D1.
