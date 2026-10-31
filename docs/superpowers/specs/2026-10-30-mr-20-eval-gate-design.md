# MR-20: run the LLM eval and decide the model (design)

Ticket: MR-20 (issue 20). Plan of record: `docs/kickoff/13-llm-and-token-strategy.md` §H3 (thresholds) and §H4 (routing). Harness: MR-18 (`apps/eval`). Exam: MR-19 (the 40 cases in `apps/eval/cases/`). Unlocks MR-26 (router and templates) and MR-27 (broker loop and number validator).

## Intent
No agent code is merged until we know which model answers which question. This ticket builds the gate (report and tone judge), runs a **cheap preliminary** exam on the low-cost models, and writes a **provisional** decision so MR-26 and MR-27 can start. The final decision comes later from a larger run (more runs, all six models) with the same tooling (D5).

## Goals
- Preliminary run: 4 low-cost models x 40 cases x 1 run: `openai:gpt-5.6-luna`, `anthropic:claude-haiku-5-5`, `google:gemini-3.8-flash`, `google:gemini-3.5-flash-lite`. Budget under US$1 including the judge.
- `openai:gpt-6.1-sol` and `anthropic:claude-sonnet-5-5` are paused: kept in `config.py` but not runnable until moved back (D5).
- A gate report per model, overall and per category: tool, args, numbers, tone, latency p50 and p95, mean cost per question, error count.
- A tone judge (LLM as judge) plus a human check of 10 sampled replies.
- A provisional routing table (§H4) and decision memo `docs/decisions/llm.md`, with the command for the final run.

## Non-goals
- New eval cases or changing existing ones (MR-19). A case found wrong is reported in the memo, not silently fixed.
- A Mock RPC that computes answers from arguments (follow-up from MR-19 D1).
- Changing the `app.llm_route` enum (see D4).
- The router, templates, broker loop or runtime number validator (MR-26, MR-27).
- CSV output, parallel execution, a composite weighted score.

## Anti-goals
- Picking a model on a single run or on the overall mean only: routing needs per-category results.
- A judge that grades its own vendor's replies with no cross-check.
- Loosening a threshold after seeing the results without writing it down as a decision in the memo.

## Constraints
- Thresholds (primary model, §H3): tool >= 95 %; args >= 95 %; numeric fidelity **100 %** (no invented number in 40 x 3 runs); tone mean >= 4.0 / 5 and no run below 3; LLM latency p50 <= 3 s and p95 <= 8 s; mean cost <= US$0.003 per question.
- Errored runs (provider error, backend failure) are never scored; they are counted and reported. A model whose error rate is high is not eligible as primary.
- Only 11 of 40 cases have `must_contain` figures (fixed mock, MR-19 D1). The numbers score still requires every figure in every reply to come from a tool result or the question, so the 100 % gate applies to all 40; the memo states the limitation.
- Same prompt and tools for every model (`SYSTEM_PROMPT`, `tool_definitions()`); record `tools_sha256` and the git commit in the report.
- Paid calls: run with `--env-file .env`; never print key values.

## Decisions taken (with the human partner, 2026-10-30)
- **D1 Anthropic.** The human partner adds a funded `ANTHROPIC_API_KEY` to `.env` for Haiku 5.5 only. Without it, Haiku's rows show `err` and the other three models still run. Claude was never run end to end in MR-18, so a smoke run on Haiku comes first.
- **D2 Tone judge (cheap for now).** Gemini 3.8 Flash judges every reply against a fixed rubric (Mexican register, consistent tú / usted, concise, no anglicisms, at most one emoji) and returns a 1-5 score with a one-line reason. When the judged model is from the judge's vendor (Google), GPT-5.6 Luna re-judges it and the gate uses the lower score. The judge and cross judge are two constants, so the final run can switch to Sonnet 5.5 / GPT-6.1 Sol in one line each. A human reviews 10 sampled replies (spread across models and categories) and records agreement with the judge.
- **D3 Harness scope: minimal gate report.** Inside `apps/eval`, backward compatible, tests first:
  - per-model summary over all cases, overall and per category (tool, args, numbers, tone, p50, p95, mean cost, errors), marked pass / fail per threshold;
  - a `--judge` flag that adds the tone score (off by default, it costs calls);
  - a JSON dump of every run (question, reply, tool calls, scores, tokens, seconds) for the human review and the memo.
- **D4 `llm_route` enum.** Not changed here. If the winners are not Haiku / Sonnet, the memo says so and calls for a follow-up migration to role names (for example `primary`, `escalation`).
- **D5 Budget: provisional now, final later (2026-10-30).** The human partner does not want to spend about US$20 yet. Sol and Sonnet move to a `PAUSED` tuple in `config.py` that `--models` rejects, so they cannot be run by accident; re-enabling one is moving its line back to `MODELS`. The preliminary run is 1 run per case. One run cannot show flakiness and makes the 100 % numeric gate weaker, so the memo is marked **provisional** and gives the exact command for the final run (all six models, `--runs 3`, Sonnet / Sol as judges). The final run is a follow-up ticket.

## Amendments (2026-10-31)
- **No model is chosen in MR-20 (product owner).** The deliverable is the tooling, ready for the final run, plus a provisional memo with the preliminary evidence. "Done when" items about a provisional primary no longer apply.
- **D2 judge:** the judge is GPT-5.6 Luna and the cross judge is Gemini 3.5 Flash-Lite, because Gemini 3.8 Flash returned 503 on every call with the free-tier key.
- **Scoring changes:** written down per the anti-goal, with tests, and the thresholds are unchanged:
  - args scores only the first call to the expected tool;
  - all locations listed equals none;
  - the prompt's dates are not counted as numbers;
  - model calls time out after 60 s;
  - Gemini retries 429 / 503.

  `docs/decisions/llm.md` explains why.

## Decision rule (to apply to the results)
1. Eligible as primary: passes every threshold overall.
2. Among eligible models, pick the cheapest; a tie goes to the lower p95.
3. Escalation: the best model on the categories where the primary fails a threshold; those categories route to it. The `propose_change` write flow routes to escalation anyway (§H4 rule 3) unless the primary scores 100 % on the write category.
4. Fallback: the best eligible model from another vendor.
5. If no model passes, the memo says so, names the closest model and the failing categories, and MR-26 / MR-27 stay blocked until a decision with the team.

## Done when
- The provisional decision memo `docs/decisions/llm.md` is merged, with the gate report, the routing table, the judge setup, the human-check agreement, the limitations and the command for the final run.
- The provisional primary model has 100 % numeric fidelity on the 40 questions (1 run).
- A follow-up issue exists for the final run (D5).
- `/check` passes on the harness changes.

## Left to the builder
- The exact judge prompt and how its replies are parsed; where the run dump is written (outside git, for example `apps/eval/out/`, ignored).
- Whether the gate report prints after the per-case table or replaces it.
- How the 10 human samples are chosen (seeded random, stratified by model and category).

## Risks
- Haiku 5.5 is new and the Agno payload to Anthropic differs slightly from C4 (MR-18 handoff §5); the smoke run may show tool-format problems that need a harness fix first.
- A flaky provider can leave a model short of runs. Rerun that model only, not the whole matrix (the final run of 720 takes one to two hours).
- One run per case hides flaky models; a provisional primary may fail the final run. MR-26 / MR-27 should keep the provider behind the thin adapter so the switch is a config change.
- The weak figure coverage (11 of 40 cases) means a model can pass numeric fidelity on the mock and still miscopy figures on real data; MR-27's runtime number validator is the real guard.
- Judge bias: an LLM judge tends to reward longer replies; the rubric scores concision explicitly and the human check measures agreement.
