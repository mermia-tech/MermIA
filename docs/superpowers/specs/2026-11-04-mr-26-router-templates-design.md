# MR-26: router and zero-token templates (design)

Ticket: MR-26 (issue 26), branch `MR-26-router-templates`. Plan of record: `docs/kickoff/09-architecture.md` §4.2 (agent pipeline) and `docs/kickoff/13-llm-and-token-strategy.md` §I (intent router + templates). Needs MR-13 (Mock RPC, merged) and MR-20 (eval gate, merged, provisional: `docs/decisions/llm.md`). Unlocks MR-31 (switch to real RPCs). The LLM broker loop and the number validator are MR-27.

Revised 2026-11-04 after a senior review (closed vocabulary, real flag codes, complete-period comparisons, exact replies as tests, render keyed by RPC).

## Objective
An owner asks the same few things every day ("¿cuánto vendí ayer?"). Answering those with code instead of an LLM costs zero tokens, answers in milliseconds and cannot invent a number. This ticket adds the deterministic front of the agent: a router that recognizes the top 8 questions, calls the one RPC that answers each, and fills an es-MX template with the figures the RPC already formatted. Everything else goes to a broker interface, which in this ticket is a stub.

**User:** the owner or manager who asks by WhatsApp. **Success:** every message the router takes is answered right, with the right RPC and arguments; when it is not sure, it hands the message on. Precision beats coverage: a smaller template share with zero wrong answers is better than a larger one with a single confident wrong figure (13 targets a share of 30 % or more, unverified until the pilot).

## The 8 intents
Chosen with the product owner from the MR-19 eval cases: single RPC, simple arguments, no dish name to resolve.

| # | Intent | RPC and arguments | Eval cases it must match |
|---|---|---|---|
| 1 | Sales yesterday | `get_sales_summary(period="yesterday")` | `sales_yesterday` |
| 2 | Sales for another named period | `get_sales_summary(period=<named>)` | `sales_last_week` |
| 3 | Last week against the week before | `compare_periods(metric, "last_week", "prev_week")`, metric `net_sales` or `avg_ticket` | none (hand-written tests) |
| 4 | Top or bottom dishes | `get_top_dishes(period, metric, order, limit)` | `top_dishes_top5_month_units`, `top_dishes_top3_revenue_30d` |
| 5 | Food cost | `get_food_cost_pct(period)` | `cost_margin_food_cost_yesterday` |
| 6 | Compare locations | `compare_locations(metric, period)`, metric `net_sales` or `food_cost_pct`, never `location_ids` | `locations_centro_vs_polanco_last_week`, `locations_this_month_sales` |
| 7 | Payment methods | `get_sales_breakdown(period, by="payment_method")` | `ops_payment_split` |
| 8 | Is my data up to date | `get_data_status()` | `out_of_scope_data_status` |

Intents 1 and 2 are one matcher (sales total for a named period), kept as two rows because they are two menu entries. Dish margin, cost alerts, menu engineering, cancellations, discounts and staff or weekday breakdowns are **not** templates: they go to the broker.

On `main`, 4 of the 8 RPCs exist in SQL: `get_sales_summary`, `compare_periods`, `get_top_dishes` and `get_data_status` (`supabase/migrations/20261019200000_read_rpcs_first4.sql`). The other 3 template RPCs (`get_food_cost_pct`, `compare_locations`, `get_sales_breakdown`) are in open PR mermia-tech/MermIA#77 (MR-24). That PR scopes a missing location with `app.scope_locations`, as MR-17 does, and does not change `packages/contracts`. This ticket builds against the mock and the C3 examples. MR-31 checks the real answers.

## Expected behavior

### Pipeline
`answer(request, *, locations, rpc, broker) -> AgentResponse`:

1. `input.type == "text"`: run the router on `input.text`.
   - On a match: call the RPC, render the reply and return `route="template"`.
   - On no match: call the broker and return its response.
2. `input.type == "action"` with an id `tpl:<intent>` means the fallback menu was tapped: run that intent with its fixed arguments (see Fallback). An unknown `tpl:` id, or `tpl:compare_locations` from a user with one location, goes to the broker.
3. Any other input goes to the broker unchanged: `pc:` actions, other action ids, media. Handlers for `pc:` taps are a later ticket.

`locations` must hold exactly the ids in `request.location_ids`. If it does not, `answer()` raises: the caller has a bug, and a wrong scope must not be answered.

### Router rules (precision first)
- **Words, not substrings.** Normalize the text with `mermia_contracts.keys.normalize_name` (lower case, no accents), drop punctuation and split it into words. Every rule matches whole words or whole phrases: "mes" never matches inside "meseros", "pon" never inside "responde". No fuzzy or typo matching.
- **Closed vocabulary.** The router recognizes and removes, in this order:
  1. The user's location names, longest first ("Centro Histórico" before "Centro").
  2. The period phrase.
  3. The intent's trigger phrases.
  4. The intent's measure and order words.
  5. A top-N count.
  6. A fixed list of filler words (cuánto, me, mi, mis, de, la, el, en, y, por, fue, dime, dame, oye, porfa, number words…).
  
  **Any word left over means no match.** The rule is the same as for digits. So "¿cuánto vendí ayer *de tacos al pastor*?", "¿cuánto vendió *Pepe* ayer?" and "¿cuánto vendí ayer *en Centro*?" asked by a Polanco-only user all fall through, because the router does not know "tacos", "pepe" or a location the user cannot see. The word lists live in `router.py` as data, next to their tests.
- **Leftover digits.** After the steps above, any digit left means no match. This drops explicit dates ("del 5 al 11 de octubre"), figures in adversarial messages ("vendí $200,000…, ¿cierto?", "a 185 mil") and price changes ("bájale… a $110"). Location names are removed first, so a name with a digit does not trip the rule.
- **Write verbs.** Imperative and infinitive forms mean no match: cambia, cámbialo, sube, súbele, baja, bájale, pon, ponle, actualiza, redondea, manda, registra. Past tense is not a write ("¿subió o bajó?").
- **Period.** It must be explicit and named. The phrases map to `PeriodName`:

  | Phrase | `PeriodName` |
  |---|---|
  | hoy | `today` |
  | ayer | `yesterday` |
  | esta semana | `this_week` |
  | la semana pasada | `last_week` |
  | la semana antepasada | `prev_week` |
  | este mes, en lo que va del mes | `this_month` |
  | el mes pasado | `last_month` |
  | los últimos 7 días | `last_7d` |
  | los últimos 30 días | `last_30d` |

  Two periods in an intent that takes one is no match. No period is no match, except for intent 8.
- **Triggers and priority.** Each intent has its own trigger phrases:

  | Intent | Triggers |
  |---|---|
  | Sales total | vendí, vendió, se vendió, ventas, entró |
  | Payment methods | tarjeta, efectivo, transferencia, forma(s) de pago, método(s) de pago |
  | Compare locations | cada local, cada sucursal, por sucursal, por local, cuál de mis (dos) locales/sucursales, en cuál sucursal |
  | Compare periods | contra, vs, comparado con, que la semana anterior/antepasada |
  | Top dishes | platillo(s) |
  | Food cost | food cost, costo de alimentos |
  | Data status | al día, actualizados, último reporte (with "datos") |

  The specific intents (payment, compare locations, compare periods, top dishes, food cost, data status) win over the generic sales total. If two specific intents fire ("ventas y food cost de ayer"), there is no match. An intent that its own rules reject (for example, two locations named) gives no match: the router never falls back to another intent.
- **Location.**
  - A visible location name sets `location_id`.
  - Two names in a single-location intent is no match.
  - With no name, `location_id` is left out and the reply says "en tus N sucursales". With one location, the reply names it.
  - Intent 6 accepts the names it compares in the text ("Centro y Polanco"), but never sends `location_ids`: the RPC compares every location the user can see, as the eval case expects.
- **Intent 3 (compare periods), complete periods only.** The pair must be `last_week` against `prev_week`, either named ("la semana pasada contra la antepasada") or implicit ("la semana pasada contra la anterior"). Any other pair, "este mes contra el mes pasado" included, goes to the broker. The SQL resolves `last_month` to the whole month and `this_month` up to today (`resolve_period`, lines 59-62), so the reply would compare part of a month against a full month as if it were a fact. The metric is ventas → `net_sales` or ticket promedio → `avg_ticket`; any other metric is no match.
- **Intent 4 (top dishes).**
  - The trigger is "platillo(s)" plus exactly one measure:
    - vendido(s) → `units`;
    - dinero, me venden más → `revenue`;
    - ganancia en pesos, me deja más → `margin`;
    - porcentaje de ganancia → `margin_pct`.
  - Two measures ("me deja el menor porcentaje de ganancia") is no match.
  - Order: más, mayor → `desc`; menos, menor → `asc`.
  - N is a digit or a number word placed right before "platillo(s)", from 1 to 10. Without N, a plural gives 5 and a singular ("el platillo que más…") gives 1.
  - Estrella, caballo, rentable and the other menu-engineering words are not in the vocabulary, so they fall through.
- **Intent 8 (data status).** It takes no period and no location: `get_data_status()`.

### Rendering
- `render(rpc, args, envelope, locations) -> TextMsg` is keyed by RPC name and arguments, not by router intent, so MR-27 can reuse it (see Follow-ups). The reply is one `text` message in Mexican Spanish, short, in the tone of `docs/kickoff/12-*`.
- **Where a number may come from:**
  - the `text` fields and `name`s of the RPC data;
  - integer `Count` values shown as they are (`tickets`, `stale_costs`);
  - dates from the data (`last_batch_at`, `missing_business_days`), all formatted by one helper in America/Mexico_City;
  - list numbering;
  - the location count;
  - N from the arguments;
  - flag messages, which our own SQL writes (see below).
  
  No arithmetic and no reformatting of money or percentages.
- **Labels.** The code may add fixed Spanish labels: `card` → Tarjeta, `cash` → Efectivo, `transfer` → Transferencia (an unknown key is shown as is), and the Spanish name of the named period.
- The food cost reply always shows the coverage figure (08: a confidence tag on every cost figure).
- A null figure (in `SalesSummaryData`, or `pct_change`) is left out, never shown as 0.
- Empty `rows` (top dishes, breakdown, locations) give "No hay ventas registradas en {periodo}."
- **Flags.** Every flag that has a `message` adds that message as its own line after the figures, in the order the RPC sent them. A flag without a message is ignored. Every message is a caveat our own SQL writes in Spanish, so there is no list of codes to keep in sync. These are the flags of the 8 template RPCs, from MR-17 on `main` and MR-24 in PR #77:

  | Code | Meaning | RPCs |
  |---|---|---|
  | `missing_days` | the period is only partly reported | all except `get_data_status` |
  | `previous_partial` | the comparison base is incomplete | `get_sales_summary` |
  | `partial_data` | some figures, or the per-payment detail, are not reported for every day | `get_sales_summary`, `get_sales_breakdown` |
  | `uncosted_sales` | dishes without a cost are left out of a margin ranking | `get_top_dishes` |
  | `cost_confirmed` / `cost_estimated` | how far the cost figures can be trusted (08's confidence tag) | `get_food_cost_pct`, `compare_locations` |
  | `missing_locations` | locations with no data in the period | `compare_locations` |

### RPC failures
- **Shape check.** `answer()` validates `envelope.data` against `RPCS[rpc].data` before rendering. A payload that does not fit is handled like `internal`.
- **`ok=false` with `no_data`.** The reply is a fixed one per RPC, with `route="template"`:
  - In general: "No tengo datos de {periodo} todavía."
  - For `compare_periods`: "No tengo datos completos para comparar esas semanas."
- **Any other error code, or a call that raises.** The fixed reply is "No pude consultar eso ahora, inténtalo en un momento.", with `route="fallback"`, and the error is logged. The message is not sent to the broker, which would call the same RPCs.

### Fallback (broker stub)
- **`Broker`.** It is a protocol: `(request: AgentRequest, locations: Mapping[UUID, str]) -> AgentResponse`. The broker gets its RPC caller when it is built, not on each call. MR-27 provides the real one; its owner agrees to this signature before Task 2 of the plan.
- **The stub.** It returns `route="fallback"` with one `choices` message: a fixed text ("Todavía no sé responder eso. Prueba con una de estas:") and the menu. Ids are `tpl:<intent>` and labels have at most 24 characters (the contract limit). With more than 3 options, WhatsApp shows a list (09 §4.3).
- **The menu and its fixed arguments:**
  - sales yesterday;
  - sales last week;
  - last week against the week before ("Semana vs anterior", `net_sales`);
  - top 5 dishes this month by units;
  - food cost yesterday;
  - locations last week (`net_sales`), only offered to a user with two or more locations;
  - payment methods yesterday;
  - data status.

## Requirements

### Functional
- F1. The 8 intents are answered without any LLM call.
- F2. Every message the router does not match goes to the broker unchanged.
- F3. The router never produces a call that differs from the eval case's `expected_args` or one of its `accepted_args`. Both sides are compared after `RPCS[tool].args.model_validate(x).model_dump(mode="json", exclude_defaults=True)`.
- F4. `tpl:<intent>` taps run that intent.
- F5. Replies are es-MX; code, comments and logs are English.

### Non-functional
- N1. The template path makes one RPC call and no other network call, and loads no LLM SDK. A test checks this, because Agno is installed in the shared workspace environment.
- N2. The router is a pure function, `text + locations -> Match | None`, testable without I/O.
- N3. ruff, ruff format and mypy strict pass (`/check`).
- N4. No new third-party dependency.

## Acceptance criteria
- [ ] For all 40 eval cases, the router either returns no match or returns the case's `expected_tool` with arguments equal to `expected_args` or to one of `accepted_args` (F3 comparison).
- [ ] MUST_MATCH (9) returns a match:
  - `sales_yesterday`
  - `sales_last_week`
  - `top_dishes_top5_month_units`
  - `top_dishes_top3_revenue_30d`
  - `cost_margin_food_cost_yesterday`
  - `locations_centro_vs_polanco_last_week`
  - `locations_this_month_sales`
  - `ops_payment_split`
  - `out_of_scope_data_status`
- [ ] MUST_NOT_MATCH (25) returns no match:
  - all of `adversarial_*` (3), `ambiguous_*` (3) and `writes_*` (4);
  - `out_of_scope_employee_count`, `out_of_scope_whatsapp_supplier`, `out_of_scope_wine_pairing`;
  - `cost_margin_bistec_margin`, `cost_margin_cost_alerts_30d`, `cost_margin_food_cost_range`, `cost_margin_menu_engineering_30d`, `tacos_al_pastor`;
  - `ops_discounts`, `ops_sales_by_waiter`, `ops_saturday_cancellations`;
  - `sales_explicit_range`, `sales_by_weekday`, `sales_month_vs_last`;
  - `top_dishes_top2_units_1_11_oct`.
- [ ] The other 6 may match or not, and F3 holds for them:
  - `sales_avg_ticket`
  - `sales_vs_previous_week`
  - `top_dishes_top_margin`
  - `top_dishes_worst_seller`
  - `top_dishes_least_profitable`
  - `locations_worst_food_cost`
- [ ] Each hand-written negative in the plan gives no match. At least:
  - a dish, a staff name or a payment filter on a sales question;
  - a location the user cannot see;
  - two intents, two periods, two measures;
  - a leftover digit, a write verb;
  - "este mes contra el mes pasado".
- [ ] For each of the 8 intents, the reply rendered from its RPC example in `packages/contracts/tests/examples/rpc/` equals an exact expected string kept in the tests.
- [ ] `answer()` on a matched text returns `route="template"` and does not call the broker. On an unmatched text, it calls the broker once and returns its response.
- [ ] Each `tpl:<intent>` id in the stub menu runs its intent, and every label fits in 24 characters.
- [ ] `no_data`, another RPC error, a raised exception and data that does not fit the RPC model each give their fixed reply and route.
- [ ] Null sales figures and an empty `rows` list render without a 0 and without a crash.
- [ ] Each flag with a message adds that message as its own line, in order; a flag without a message changes nothing. Food cost with `cost_estimated` shows the estimate caveat next to the coverage figure.
- [ ] Importing the router and templates in a fresh interpreter loads no `agno`, `openai`, `anthropic` or `google` module.
- [ ] `.claude/skills/check/check.sh` passes.

## Constraints and existing behavior to keep
- `packages/contracts` is not changed. `AgentRequest`, `AgentResponse`, `ActionId`, `parse_pending_action`, `RPCS` and the argument models are used as they are. A contract change needs both devs and is not planned.
- The agent never computes money; templates copy `text` fields (CLAUDE.md, 09 D6).
- `pc:` action ids keep their meaning (confirmation flow, 09 §5), and the router does not touch them.
- The eval cases in `apps/eval/cases/` are read, never edited (MR-20 non-goal).
- Ingestion code in `apps/api` is untouched.

## Scope

### In scope
- `apps/api/src/mermia_api/agent/`: router, rendering, `answer()`, the `Broker` protocol and its stub.
- Tests in `apps/api/tests/agent/`.

### Out of scope
- The LLM broker loop, tool executor and number validator (MR-27), including the template rendering of LLM tool calls (see Follow-ups).
- WhatsApp webhook, HTTP endpoint, sending (channels ticket).
- `pc:` handlers (confirm, reject, detail), undo.
- Memory, per-tenant caps, `llm_usage` rows, logging the template share.
- The real RPC client and the switch from mock to real data (MR-31).
- Loading location names from the database: the caller passes them (D1).
- Explicit date ranges, fuzzy or typo matching, dish names.
- Comparing incomplete periods ("este mes contra el mes pasado").
- The business-day cutoff (a sale at 1 a.m. that belongs to the previous night).

## Project structure
```
apps/api/src/mermia_api/agent/
  __init__.py      answer(request, *, locations, rpc, broker) -> AgentResponse
  router.py        route(text, locations) -> Match | None; word lists; menu args per intent
  templates.py     render(rpc, args, envelope, locations) -> TextMsg; Spanish labels, date helper
  broker.py        Broker protocol, StubBroker (fallback menu)
apps/api/tests/agent/
  conftest.py        fixtures: fake_rpc (RPC examples), counting_broker, El Güero locations
  test_router.py     eval sweep (F3, MUST_MATCH, MUST_NOT_MATCH) + hand-written phrases
  test_templates.py  exact reply per intent, nulls, empty rows, flags
  test_answer.py     pipeline: template vs broker, tpl: taps, failures, no-LLM import
```

## Code style
Follow `apps/api/src/mermia_api/ingestion/`: small modules, a module docstring stating the why, frozen data, and `Literal` over enums for closed sets. A sketch of the boundary, not final code:

```python
RpcCall = Callable[[str, dict[str, Any]], RpcEnvelope[Any]]


@dataclass(frozen=True)
class Match:
    intent: Intent  # Literal of the 8
    rpc: str  # a key of mermia_contracts.rpc.RPCS
    args: dict[str, Any]  # validated against RPCS[rpc].args before the call


def route(text: str, locations: Mapping[UUID, str]) -> Match | None:
    """The one intent `text` asks for, or None when any word is not understood."""
```

## Commands
- Install: `uv sync --all-packages --all-groups`
- Tests: `uv run pytest apps/api/tests/agent`
- All checks: `.claude/skills/check/check.sh`

## Testing strategy
Tests come first (TDD), with pytest, no network and no LLM. Helpers are pytest fixtures, because `--import-mode=importlib` does not let tests import from `conftest.py`.
- **Router (unit).**
  - Parametrized over all 40 files in `apps/eval/cases/`, read as JSON by path (no dependency on `mermia-eval`).
  - Locations: El Güero's Centro and Polanco, from the eval system prompt.
  - Checks: F3 with the normalized comparison, MUST_MATCH, MUST_NOT_MATCH.
  - Plus hand-written phrases:
    - accent and case variants;
    - every period phrase;
    - number words;
    - each acceptance-criteria negative;
    - "meseros" not read as "mes";
    - longest location name first;
    - a one-location user.
- **Rendering (unit).**
  - A `fake_rpc` fixture returns the envelopes in `packages/contracts/tests/examples/rpc/` (the data the Mock RPC serves), plus variants built from them: nulls, empty rows, `no_data`, `internal`, data that does not fit the model, flags with a message (one test per code in the flags table), a flag without a message.
  - One exact expected reply per intent. The PR shows these same replies for the product owner to approve the wording.
- **Pipeline.**
  - `answer()` with a counting broker: a matched text does not call it; an unmatched text calls it once.
  - `tpl:` taps, including `tpl:compare_locations` from a one-location user.
  - `pc:` actions and media go to the broker.
  - `locations` must agree with `request.location_ids`.
  - A subprocess import check for N1.
- No `-m db` tests: nothing touches Postgres.

## Boundaries
- **Always:** tests before logic; copy figures from the RPC data; when unsure, no match.
- **Ask first:**
  - any change to `packages/contracts`;
  - adding a dependency;
  - a 9th intent;
  - parsing explicit dates;
  - comparing incomplete periods.
- **Never:** call an LLM on the template path; compute or reformat money; edit eval cases; call `apply_*`.

## Decisions taken (product owner)
- **The 8 intents** in the table above. Intent 3 is restricted to complete weeks after review.
- **Precision over coverage:** when not certain, hand the message on.
- **Only the broker interface** and a stub; the real broker is MR-27.
- **No location named means the user's locations.** `location_id` is left out and the reply says so. In SQL, a missing `location_id` already means the locations in the user's membership, never the whole tenant (`supabase/tests/70_rpcs.test.sql:265`, `get_sales_summary`).
- **Reference date.** The router sends named periods and the RPC resolves them (`resolve_period`), so the router needs no date. Dates shown in replies use America/Mexico_City (shortcut: one time zone for all pilot locations; use `location.timezone` once a tenant spans time zones).
- **Flags.** Every flag message is shown as is (see Rendering).
  - This replaces two earlier decisions. The `partial_period` code does not exist. A list of three codes was also dropped: PR #77 adds cost-confidence and missing-location flags, and its `partial_data` on the payment breakdown ("Solo 3 de 7 días con ventas tienen este detalle.") changes what the figures mean.
  - All the messages are Spanish caveats from our own SQL, so showing them all is both simpler and safer than choosing.
- **Template wording.** The product owner approves the exact replies in the PR.
- **D1 Location names are a parameter.** `answer()` and `Broker` take `locations: Mapping[UUID, str]`; the channel layer loads it from `location`. Adding names to C6 was rejected.
- **D2 Tests read the RPC examples**, not the Mock RPC app. It is the same data, and it needs no new dev dependency.
- **D3 Explicit dates fall through to the LLM.**
- **D4 Errors.** `no_data` gets a template reply; other errors and bad shapes get a fixed fallback reply and are not sent to the broker.
- **D5 The stub shows the menu** on every unmatched message. Once MR-27 exists, the menu shows only when the LLM is unavailable or over its cap (09 §4.2).
- **D6 Closed vocabulary.** Any word the router does not know means no match. This covers filters it cannot apply (dish, staff, payment method on a sales total) and locations the user cannot see.
- **D7 Exact replies replace the digit-source check.** One golden reply per intent tests the rendering, and the number-source rule is enforced by code review.
- **D8 `render` is keyed by RPC**, not by intent, so MR-27 can reuse it.

## Follow-ups for other tickets
- **MR-27: LLM picks, template answers.**
  - When the LLM makes exactly one call to one of these 8 RPCs and the question has no part the call leaves out, the reply is built with `render()` instead of being written by the LLM.
  - This gives the template's number safety to paraphrases the regex router rejects.
  - It needs a signal that the call covers the whole question (for example a structured field). Without it, "ventas de ayer de tacos" would get the total.
  - The same `render()` is the fallback of the number validator (09 §4.2).
- **MR-24 (PR #77).**
  - `get_food_cost_pct`, `compare_locations` and `get_sales_breakdown` already use `app.scope_locations`.
  - `supabase/tests/75_rpcs_rest7.test.sql` already has Polanco-manager isolation tests for the three, so the scope concern is covered once it merges.
  - What remains is a review note: flag messages must stay Spanish owner-facing caveats, since templates show them as is.
- **MR-31.** Run the 8 exact replies against the real RPCs and check that their messages read well together.
- **Pilot / MR-31:** decide whether "ayer" after midnight means the business night that just closed.
- **Pilot:** measure which unmatched messages are frequent. They are candidates for new words in the vocabulary, or for intents if they need a new RPC.
