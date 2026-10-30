# MR-19: the 40 eval questions (design)

Ticket: MR-19 (issue 19). Plan of record: `docs/kickoff/13-llm-and-token-strategy.md` §H3. Harness: MR-18 (`apps/eval`). Gate that consumes this: MR-20.

## Intent
MR-20 picks the LLM from an exam. Today the exam has one case. This ticket writes the other 39 so that the model choice rests on realistic owner questions with known right answers.

## Goals
- 40 case files in `apps/eval/cases/`, questions in Mexican Spanish as a real owner types them (informal, short, sometimes vague).
- Each case states the expected tool (or none), the expected arguments and, where the mock can back it, the figures the reply must show.
- Expected figures are computed from the El Güero fixtures by a script that does not read the Mock RPC's answers, and a human (Dev A) reviews script and table.

## Non-goals
- Running the eval or choosing a model (MR-20), pass thresholds, the tone judge.
- Making the Mock RPC compute answers from arguments (separate ticket, see D1).
- Questions for tools that do not exist yet (price suggestions, CFDI capture).

## Anti-goals
- A question set so clean that every model passes it.
- Expected numbers copied from the mock: the exam would grade itself.
- Cases that only fit one model's phrasing of the arguments (use `accepted_args` for legitimate equivalents).

## Constraints
- "Today" is Monday 2026-10-12, data ends 2026-10-11 (`fixtures/el_guero/expected.json`). Avoid `this_week`: on a Monday it has no data.
- Only the 12 tools of `tool_definitions()`. Record `tools_sha256` with the set so a later tool change shows the exam is stale.
- Money is exact; only percentages may carry a per-case tolerance. A rounded "$184 mil" is wrong.
- Figures are the ones a tool already returns; the model copies, it does not compute.
- Food cost for yesterday is **37.5 %** (not 31.4 %) and the pastor margin is **67.2 %** (not 71.7 %); see `fixtures/README.md`.
- Code and docs in English; questions in Mexican Spanish.

## Decisions taken (with the human partner)
- **D1 Fixed mock.** The Mock RPC returns one canonical answer per RPC whatever the arguments, and `test_cases.py` requires every `must_contain` figure to be in that answer. So `must_contain` is filled only where the question matches the RPC's canonical query (Centro, last week; top 2 by units 2026-10-01..11; margin of tacos al pastor; food cost of yesterday; the 2026-10-10 cancellations; etc.). The other cases are scored on tool and arguments, and their seed-derived figures are kept in the review table as pending until a mock that computes exists. A follow-up ticket for that mock is to be opened.
- **D2 Categories.** The nine of §H3: sales totals and comparisons 7, top and bottom dishes 6, dish cost and margin and food cost 6, staff/payments/discounts/cancellations 4, multi-location 3, ambiguous 3, write proposals 4, out of scope or data missing or error 4, adversarial 3. Within them, at least one case for each of `get_menu_engineering`, `get_cost_alerts` and `get_data_status`, which §H3 does not name. Every `propose_change` kind (ingredient price, menu item price, recipe) appears once at least.
- **D3 Harness change, inside this ticket, minimal and backward compatible.** `expected_tool` may be null (the model must call nothing; used for out-of-scope, underspecified and refused cases, one category for both "reject" and "ask back"). A `must_not_contain` list (default empty) for phrases such as claiming a change was applied. Tests for both. Multi-tool expectations are added only if a case truly needs them; prefer writing questions that need one tool.
- **D4 Branch.** `MR-19-eval-questions`, cut from `MR-18-eval-harness` (the harness is not in `main`). The PR depends on MR-18.
- **D5 Reviewer.** Not decided. Dev A is not identified in the ticket; the PR author asks the team who it is. My guess is the author of MR-12 (the seed), unconfirmed.

## Review process
Dev A reviews the generating script and the full table (question, tool, args, figure and where it comes from in `expected.json`), by approving the PR. Ask for it in two rounds: at about 20 cases and at the end. The PR description lists `tools_sha256`, the fixed date and the command that regenerates the table.

## Left to the builder
- Exact wording and split of the 40 questions inside each category.
- Where the script and the generated table live, and whether `must_not_contain` is folded into the numbers score or reported on its own.
- Case ids and file naming.
- Whether the null-tool case needs changes in `score_args` and `score_numbers` (a case with no calls must not score 0 on tool, and its numbers may come only from the question).

## Risks
- MR-18 may change the case format before it closes; re-check before opening the PR.
- Few figure-checked cases (D1) make the numeric-fidelity gate (100 %) weak until the mock computes.
- Ambiguous cases need one defensible expected behaviour; write only those where a required argument is missing.
