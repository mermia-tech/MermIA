# MR-11 Design: RPC shapes, agent tools and pending changes

Date: 2026-10-18. Ticket: [#11](https://github.com/mermia-tech/MermIA/issues/11). Branch: `MR-11-contracts-rpc-tools`, built on `MR-10-contracts-schema` (which already contains `main`). Status: **PR #50. The corrections of section 7 (post-merge audit, 2026-10-19) are committed locally on the branch and not yet pushed.**

This document records what the contracts decide and what they leave to later tickets, so a builder of MR-13, MR-32 or MR-37 does not have to read the code first. Section 6 lists everything still open.

## 1. Intent, scope and non-goals

### Why
Dev A (data) and Dev B (conversation) agree on shapes before they build. After the freeze a shape changes only with both approvals (see 2, row D12, for how far that is enforced).

### Goals
- C3: the 11 read RPCs with arguments, response data, the common envelope and examples (`rpc.py`).
- C4: the 12 agent tools as JSON Schema, derived from C3 plus `propose_change` (`agent_tools.py`).
- C5: the five `PendingChange` kinds, their payloads, and the call and result of `apply_pending_change` (`pending.py`).
- C6: `AgentRequest` and `AgentResponse` (`agent.py`).
- A script that exports JSON Schema for the Phase 2 frontend types, and `CODEOWNERS`.

### Non-goals (out of MR-11)
- Any migration, SQL or pgTAP. `apply_pending_change` is a contract here; its body and tests are **MR-32**.
- The mock RPC server (MR-13) and the confirmation service (MR-37).
- Kinds `ingredient_alias.confirm` and `settings.update` (`09` section 5.1). Exactly five kinds exist.
- Measuring the 125-token budget (6.2). Typed `propose_change.values` made that schema larger (7, D21).
- Fixing the lint debt that merging `main` into MR-10 exposed (6.5).

### Anti-goals
- A contract that cannot be satisfied by the values the callers really hold (parsed JSON, HTTP responses).
- Authorization written into the contract that MR-10 does not support (for example `auth.uid()` as the identity of every caller).

## 2. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Same conventions as `batch.py`: snake_case JSON, unknown fields are an error, frozen models, money in integer centavos (a float, string or bool is never money), percentages in percent points, instants with a time zone. `batch.Model`, `Period`, `Cents`, `Count`, `Text` are reused. | Existing convention |
| D2 | Envelope `{ok, data, error, flags[], meta}`. `ok=true` requires `data` and forbids `error`; `ok=false` requires `error` and forbids `data`. `error.code` is a closed list. `Flag` carries a code and a message; its code list is open. | `09` names `ok`, `data`, `flags`, `meta`; the `error` field and the lists are the author's |
| D3 | Numbers travel as `{raw, text}`: raw for code and charts, text pre-formatted by the metric layer. | `09` section 4.1 |
| D4 | An ambiguous dish name in `get_dish_margin` is a successful answer (`match = "ambiguous"` with candidates). | Author's; `09` says "returns candidates when ambiguous" |
| D5 | The 12 tools are the 11 RPCs plus `propose_change`. Read tools use the RPC argument models as they are. `propose_change` keeps a flat schema (`kind`, `target`, `values`, `reason`) and `values` is typed per kind (D15). `target` is what the user said; the confirmation service resolves it to the id that `ChangeProposal.target_id` holds. | Author's; D15 supersedes the open `values` |
| D6 | Exactly five kinds: `ingredient_price.set`, `recipe.upsert`, `menu_item_price.set`, `import_batch.approve`, `import_batch.rollback`. `pending_change.kind` stays `text` in the database. | Owner, 2026-10-18 |
| D7 | `ingredient_price.set` as STORED and applied carries **pesos per base unit** of the ingredient (g, ml or pza), the unit `ingredient_price.unit_price_net` is stored in (MR-10 spec 5.4, D6 there). "$220 per kg" of an ingredient whose base unit is g is `0.22`. The model does not send that figure: it sends the price and unit the user said (D15). Prices per purchase unit exist in `batch.PurchaseLineIn` and are converted by the costing engine (MR-25). `PriceMove.new_unit_price` keeps the per-base-unit number and adds the unit and a text to quote (D15). | Review finding 1; follows MR-10 |
| D8 | `recipe.upsert` has its own `RecipeLine`, a copy of `batch.RecipeLineIn` with the Decimal types of D9. PROVISIONAL like the original. | Author's (batch.py is out of scope) |
| D9 | Decimal inputs: exact or rejected, never silently altered; see section 4. | Review finding 2; owner's precision condition |
| D10 | Action ids: ids starting with `pc:` must be `pc:<canonical lowercase UUID>:approve\|reject\|detail`; every other id (1 to 256 characters) is opaque. | Owner, plan review 2026-10-18 |
| D11 | Schemas are exported to `packages/contracts/schemas/` and a test fails when they are stale. | Plan |
| D12 | `CODEOWNERS` lists `@p0sin` and `@campolloram` for `packages/contracts/`. Owners on one line are alternatives: either one satisfies code-owner review. `main` has no branch protection (checked with the GitHub API), so it only requests reviews and blocks nothing. The ticket's "both must approve" is therefore **not** enforced; it would need two required approvals, which the owner chose not to set. | Owner |
| D13 | The token budget is documented (`TOKEN_LIMIT = 125`) and not measured. It is **deferred to MR-20; MR-11 does not meet it and it is not a closing requirement** (7.3). | Owner, 2026-10-18 |

## 3. `apply_pending_change`

### 3.1 Authorization model assumed (option A, the MR-10 spec)
From MR-10 spec 7.5.7 and 7.2.6. The contract does not implement these; it must not contradict them.

1. `SECURITY DEFINER`, `EXECUTE` granted to `service_role` only. The caller is the trusted backend (confirmation service, dashboard API), never a client or the LLM.
2. `user_id` is the approver's `app_user.id`, resolved by the backend from the channel identity. The contract does **not** assume `auth.uid()` identifies the approver: `app_user.auth_user_id` can be null (WhatsApp-only users) and what `sub` carries in backend-issued tokens is undecided (MR-10 open item O3).
3. The tenant comes from the target row, never from an argument.
4. The function verifies in the database that the user belongs to that tenant (`membership`), that the user's role is allowed by `pending_change.required_role` and `membership.can_approve`, and, for located targets, the location from `membership` and not from a claim.
5. The contract has no role table. Who may approve is data (`required_role`, `can_approve`), so a fixed list of roles in code would contradict it.

### 3.2 Call and result
- `ApplyPendingChangeArgs{id, user_id}`: two UUIDs, nothing else (a `role` or `tenant_id` argument is rejected).
- `ApplyResult{code, pending_change_id, status, message}`. Business outcomes are returned, never raised.

| `code` | Meaning | `status` allowed in the result |
|---|---|---|
| `applied` | The change was applied now | `applied` |
| `already_applied` | Idempotent: it was applied before | `applied` |
| `not_found` | No such change, or the user is not a member of its tenant (both look the same, so other tenants leak nothing) | none; `message` must be empty too |
| `forbidden_role` | `required_role`, `can_approve` or the location check failed (the name is historical; it covers all three) | the row's current status |
| `not_pending` | The status is neither `pending` nor `applied` (`approved`, `rejected`, `expired`, `conflict`, `failed`) | that status |
| `expired` | It expired and was moved to `expired` by this call | `expired` |
| `conflict` | The target changed since the proposal (`version` differs from `base_version`) | `conflict` |
| `failed` | The write failed and was rolled back | `failed` |

`ok` is true only for `applied` and `already_applied`. The validator rejects every other pair of code and status (all 49 pairs are exercised in `test_pending.py`).

### 3.3 Persisted effects the contract expects (the SQL is MR-32)
| Outcome | Status of the change after the call | Audit row | Target tables |
|---|---|---|---|
| `applied` | `applied` | yes, in the same transaction as the write | write committed |
| `expired` | `expired` | yes | unchanged |
| `conflict` | `conflict` | yes | unchanged |
| `failed` | `failed` | yes | unchanged (the write is rolled back) |
| `forbidden_role` | unchanged | MR-32 decides | unchanged |
| `not_found`, `not_pending`, `already_applied` | unchanged | none | unchanged |

Order of checks, approved in the plan review: membership and tenant, then authorization, then status, expiry, version, write. Only an authorized approver can cause a state change, so an unauthorized caller cannot expire, conflict or apply a change. Two ways to see "expired" exist: the code `expired` (this call moved it) and `not_pending` with status `expired` (it was already moved); consumers should treat both as expired.

## 4. Decimal inputs and the precision policy

`batch.py` declares strict `Decimal` fields. In Python mode they accept only `Decimal` instances, so a dict from `json.loads` (LLM tool input, PostgREST) failed on every `220` and `220.5`: 11 of 13 RPC examples and 2 of 5 proposals did not validate. In JSON mode pydantic reads every JSON number through a float64, so `12345678901.123456` was silently read as `...123455`. `decimals.py` puts one conversion in front of the same strict schema (same `max_digits` and `decimal_places`, so the database range is kept) for Python and for JSON input:

| Input | Result |
|---|---|
| `Decimal` | as is |
| `int` | exact (`bool` is rejected) |
| `str` such as `"-12.50"` | exact, full database precision; no exponent, no spaces |
| `float` (any JSON number with a fraction) | accepted only if its shortest repr has at most 15 significant digits **and** its magnitude is below 2^33 (about 8.6 billion); otherwise rejected |
| `None`, lists, bytes, `nan`, `inf` | rejected |

**Why this is safe.** A decimal with at most 15 significant digits survives decimal, float64 and back. Below 2^33 the spacing of float64 values is under 2e-6, so two different values with at most 6 decimals can never share a float: a number whose float reading is longer than 15 digits, or larger than 2^33, is rejected instead of altered. For every value inside the database range that arrives as a JSON number or a Python float, the value read is exactly the value written, or the input is rejected. `test_a_json_number_is_exact_or_rejected_never_altered` checks this with 50 000 random literals (from 1 to 10^14, up to 6 decimals) plus the boundary values, through `model_validate_json` and through `json.loads` then `model_validate`; mutation experiments that remove the 2^33 limit, the 15-digit guard or the shared conversion are caught.

**Exact paths.** A string is always exact. `exact_json(text)` parses JSON with `parse_float=Decimal`, so `Model.model_validate(exact_json(text))` reads values of any length in the database range exactly; use it for PostgREST bodies that can carry large numbers.

**Stated limit (residual).** A JSON number with more decimals than the type allows (`0.1000000000000000001`) can collapse to the nearest float and be accepted as `0.1`; the exact paths reject it. The difference is below 1e-15 and it is outside the database range, so no valid value is affected. Values the policy rejects although valid (for example `1234567890.123456`, 16 digits) must be sent as strings or through `exact_json`: the failure is visible, never silent. `batch.py` keeps pydantic's behaviour; changing it is outside MR-11.

Money (`Cents`) is untouched: floats, strings and bools stay rejected in both modes (`test_decimals.py`).

## 5. Verification

Run on 2026-10-18 on the local branch (no database, no API key):
- `pytest` from the repository root (as the CI runs it): 363 passed, 34 skipped (31 need a database, 2 need the token measurement of 6.2, 1 needs `ANTHROPIC_API_KEY`).
- `export_schemas --check` and `gen_db_models --check`: up to date.
- `ruff` and `mypy` clean on every file MR-11 adds.
- Mutation experiments on a scratch copy (a one-line break of a validation each, 30 in total): 27 are caught by a behaviour test, 3 only by the schema freshness test, none survives. They include the `ok=true` envelope check that the first version of the tests did not catch, the unit tag of the price, and the three parts of the precision policy (2^33 limit, 15-digit guard, shared conversion). The 3 caught only by freshness are limits with no behaviour test: menu-engineering quadrants, `cost_drivers` count, top-dishes rows.

Not run: pgTAP, `-m db`, `-m rest`, the token measurement.

The counts above are those of the first version; section 7 lists what the audit corrections added.

## 6. Open items

### 6.1 For MR-32 (not decided here)
- The SQL body, its `EXECUTE` grants and the pgTAP tests: other tenant's id, a user without membership, role versus `required_role`/`can_approve`, location authorization, concurrent double apply, forced write failure, expiry and conflict transitions only after authorization.
- What the elements of `membership.can_approve` (`text[]`) mean. MR-10 defines the column; no document says whether they are kinds. This decides how `required_role` and `can_approve` combine.
- Audit action names, and whether `forbidden_role` writes an audit row.
- Verifying the unit of an `ingredient_price.set` against `ingredient.base_unit` (6.3 explains what the contract allows and the risk).
- The exact `membership` columns used (verified against the MR-10 migration: `tenant_id`, `user_id`, `role`, `location_ids`, `all_locations`, `can_approve`; there is no "active" flag).

### 6.2 Token budget
Each tool may add at most 125 tokens (`08` C4). **Nobody has measured it.** A rough size estimate (characters divided by 3.5, not a measurement) suggests several tools exceed it. The measurement needs `ANTHROPIC_API_KEY` and is deferred to the LLM eval ticket; the closest in the roadmap is **MR-20** (issue #20, the day-5 gate; milestone M3 in `07-roadmap.md` asks for real `count_tokens` figures). That ticket does not mention it yet, so it needs a line added. **Status: deferred to MR-20; MR-11 does not meet it, and it is no longer a closing requirement of MR-11** (7.3). Commands, metric and requirements are in `packages/contracts/README.md`.

### 6.3 `base_unit`: how the unit can be verified with the current contract
The `ingredient_price.set` payload carries a price per base unit without naming the unit (the owner asked not to add `base_unit` yet). So `apply_pending_change` cannot compare what the proposer meant with `ingredient.base_unit`. With the current contract the unit can be protected in three ways; none is a unit check made by the function alone:
1. **At proposal time.** The confirmation service reads `ingredient.base_unit` through `target_id` (`target_type` is `ingredient`), converts the user's figure ($220/kg becomes 0.22 per g, with the unit conversion of MR-25) and stores before and after, **with the unit**, in `pending_change.diff`, which the human approver sees (`09` section 5.2). The approver confirms the unit; apply trusts the stored payload.
2. **At apply time.** MR-32 reads `ingredient.base_unit` from the same `target_id` and records it in the audit row's `after`, so the unit in force is on record.
3. **Plausibility guard (optional).** Compare the new price with the current `ingredient_price`: a 1000-fold jump is the signature of a kg versus g mix-up. The threshold is a product decision that no document specifies.

**Risk to resolve before MR-32 writes the SQL:** with no unit in the payload, nothing in the database can detect a $/kg figure stored as $/g. The protection is the conversion at proposal time plus the human reading the diff. If that is not enough, the fix is to add `base_unit` to the payload so apply can compare it with `ingredient.base_unit`. That changes an approved contract (the owner's and both devs' approval), so it is deferred, not done.

### 6.3b Other decisions that need the owner
- Whether C5 needs a typed `PendingChangeRecord` (the row plus its typed payload and `diff`). The plan text (D5) mentions it once; no task and no ticket text asks for it. Not added.

### 6.4 Suggestions, not required
- Behaviour tests for the three limits that only the freshness test protects.
- Maximum lengths for user and LLM text (`TextInput.text`, `target`, `dish`, `category`). Percentage bounds for `coverage` and `share` were considered and not added (D16).
- `MetricCardMsg.data` is tied to its rpc (D19); a union per rpc would give Phase 2 precise types.
- Rename `forbidden_role`.

### 6.5 Integration debt (not MR-11's)
Merging `main` into MR-10 makes the root CI fail: 7 `ruff check` errors and 11 files for `ruff format`, all in MR-10 files (`mypy` with the CI configuration passes). MR-11 adds none. Strict `mypy` over `packages` reports 95 errors, all in MR-10 tests, so `packages` is not in `mypy files`. Options: fix them in MR-10, or relax rules for `packages`.

## 7. Corrections after the post-merge audit (2026-10-19)

The 11 findings of the review of #50 were checked against `ad6351b` (nine reproduced in code; the token budget, the pytest marker and CODEOWNERS are configuration facts) and addressed in small commits, one theme each, with tests written first. Decisions of this round (D14 to D21):

| # | Decision | Where |
|---|---|---|
| D14 | **`Figure.raw` has one scale per metric.** `rpc.METRIC_UNIT`: money (`net_sales`, `avg_ticket`, `revenue`, `margin`) is whole centavos, as `Money.raw`; counts (`tickets`, `guests`, `units`) are whole numbers; percentages (`food_cost_pct`, `margin_pct`) are percent points with at most four decimals. `Figure` keeps its shape (no `unit` field): the unit follows from the `metric` beside it. `ComparePeriodsData`, `CompareLocationsData` and `TopDishesData` enforce it; `abs_change` must equal `a - b` within one unit of the scale (a centavo, 0.0001 percent points; counts exactly), because each figure is rounded once from unrounded values. | `rpc.py`, `test_figure_scale.py` |
| D15 | **`propose_change.values` is typed per kind.** One closed variant per payload, and it must be the variant of `kind`: `IngredientPriceInput {unit_price, unit, effective_from}`, `MenuItemPriceSet`, `RecipeUpsert`, `NoPayload`; unknown fields are rejected. `unit` is `g`, `kg`, `ml`, `l` or `pza` (no free text). The model sends the price in the user's unit; it never converts. The STORED proposal (`ChangeProposal`) stays per base unit and has no `unit` (no `base_unit` in the payload either, see 6.3). **The conversion is not implemented in this package**: it belongs to the confirmation service (MR-37) with `unit_conversion` (MR-25). `PriceMove.new_unit_price` is a `BasePrice {raw per base unit, base_unit, text}`: quote `text` ("$220.00/kg"), never convert `raw`. | `pending.py`, `agent_tools.py`, `rpc.py`, `test_propose_change.py`, `test_price_move.py` |
| D16 | **Calculated and persisted percentages are different types.** `ComputedPercent` (14,4) is what `Pct` and `Meta.coverage_pct` use, so +1400 fits. `PercentPoints` (7,4) mirrors `numeric(7,4)` columns and keeps 999.9999. `pct_change` is null when the base period `b` is zero (a value there is an error). `coverage` and `share` are not bounded to 0 to 100: a refund-heavy category can have a negative share and nothing in the documents pins a bound. | `decimals.py`, `rpc.py`, `test_percent_types.py` |
| D17 | **Strictly positive prices, quantities and yields in a change**: `unit_price`, `price_gross`, `qty_base`, `yield_qty`, `yield_override_pct` (Python and JSON mode). `yield_override_pct` is edible portion over purchased in percent (03 C.6, cost = price / yield): greater than zero and limited to the column's 999.9999. It has **no 100 % cap**: the `Recetas` export that fills it is unverified (`RecipeLine` is PROVISIONAL); cap it when MR-23 verifies the export. `batch.py` (MR-10) and the database are untouched. | `decimals.py`, `pending.py`, `test_change_bounds.py` |
| D18 | **`compare_periods` carries `period_a` and `period_b`** (required, inclusive, from not after to). `meta.period_resolved` is null for it, because the envelope holds one range. | `rpc.py`, `test_compare_periods_ranges.py` |
| D19 | **`MetricCardMsg.data` must be the complete data of its `rpc`**, validated with the model registered in `RPCS`. No partial card: that needs a message type of its own (not defined). The exported schema still types `data` as JSON. | `agent.py`, `test_metric_card.py` |
| D20 | **Margin is on the NET price (without IVA).** **Decision of the project owner: margin and food cost are calculated on the net price (without IVA).** The eval 13 H3 #4 and the MR-12 fixtures use the gross price and have to follow this definition (7.1). `DishMarginResolved` gains `price_gross` (to quote the menu price) and `margin_pct`: `margin = net_price - cost`, `margin_pct = margin / net_price`, `food_cost = cost / net_price`, `margin_pct + food_cost = 100`, checked within the rounding of centavos. For the pastor at Centro (cost $18.40, menu price $65.00, net $56.03): margin 67.16 % and food cost 32.84 %, not 71.69 % and 28.31 %. Prices are greater than zero and `net_price` does not exceed `price_gross`; the IVA rate is not hard-coded. | `rpc.py`, `test_dish_margin.py` |
| D21 | **The token budget is still not measured** (D13 stands; no `tool_tokens.json`; no API key was used). Typed `propose_change.values` grew that tool's schema from 519 to 2397 characters (characters, not tokens; both as compact JSON, the comparable figures: the same schemas are 563 and 2594 with the default separators): by a character estimate the 125-token limit is very likely exceeded by it and by most other tools (an estimate, not a measurement); the real measurement decides what to cut. `test_propose_change.py` has a character guard so the size does not grow unnoticed. | `agent_tools.py`, 6.2 |

### 7.1 What the other tickets must do

| Ticket | Consequence |
|---|---|
| MR-12 (#51) | Not merged when this was written. Its `fixtures/README.md` and `expected.json` give the margin on the gross price (`margin_pct_of_gross`, 71.7 %); the contract is net (D20, decided). That README and `expected.json` must adopt the same definition (MR-12's to change; not touched here). The RPC examples are NOT aligned with the fixtures yet (see 7.2). |
| MR-13 | Do not copy the C3 examples as the mock's answers until they are aligned with the fixtures (7.2). Money in `compare_*` and top dishes is centavos; `compare_periods` needs both ranges and a null `meta.period_resolved`. |
| MR-17, MR-24 | SQL returns centavos for the money `Figure`s, null `pct_change` over a zero base, `period_a` and `period_b`, margin on net price with `price_gross` and `margin_pct`, `PriceMove` with `base_unit` and a formatted `text`. The IVA rate must come from data, not a constant. |
| MR-19 (eval) | 13 H3 #9 must send `effective_from` with `unit_price` and `unit` (the closed list). 13 H3 #4 must quote the net margin (D20, decided): for the pastor, 67.2 % with the menu price $65.00 from `price_gross`, not 71.7 %. |
| MR-20 | Add the token measurement to its acceptance criteria (the ticket does not mention it; D8/D13 deferred it, the MR-11 "Done when" item was moved to MR-20 by editing issue #11, see 7.3; issue #20 itself was not edited) and re-measure `propose_change` after D15. `measure_tool_tokens` and the budget tests exist and skip until `schemas/tool_tokens.json` does. |
| MR-25 | Cost formulas divide by yields and `yield_qty`: they are greater than zero in a change (D17) but the database has no `CHECK`. Verify the `yield_override_pct` semantics against the real export. |
| MR-32 | The stored payload stays per base unit. Whether to add `base_unit` so apply can compare it with `ingredient.base_unit` (6.3) is still the owner's decision. |
| MR-37 | Convert the user's `{unit_price, unit}` to pesos per base unit with `ingredient.base_unit` and `unit_conversion` (reject a unit family that does not match, such as a kg price for a ml ingredient), store before and after WITH the unit in `pending_change.diff`, and show it to the approver. Not implemented here. |
| MR-27 | `propose_change` input numbers come from the user's text, not from a tool result. |
| New migration ticket (MR-14 area) | `CHECK` constraints for `unit_price_net`, `price_gross`, `qty_base`, `yield_qty`, `yield_override_pct` and `default_yield_pct` (greater than zero); none exists today. The purchase rules of `batch.py` (discounts, credit notes) are MR-23's. |

### 7.2 Open items found while fixing

- **Examples versus MR-12 fixtures: pending.** The RPC examples still differ from the fixture seed: the week (10-12..18 against 10-05..11), compare `b` ($171,900.00 against $171,905.00), pastor cost and price (18.20 and 50.00 against 18.40 and 65.00), the top dish name and units (640 against 656), the discount count (14 against the 17 of the cancellation Saturday), the food cost (34.1 % against 37.5 %) and the price move (0.22 per g and +22.2 % against 170 to 195 per kg). They were not changed because #51 is not merged, and the fixtures are not the agreed reference until then. Align them from `expected.json` afterwards (MR-13 or a follow-up commit here). The invariants a self-consistent example must satisfy are tested now.
- **`PriceSuggestion` price basis.** `current_price` and `suggested_price` are `Money`, and nothing says whether they are the menu price (with IVA) or the net price. `03` computes the suggested menu price with IVA; the example uses the net price of the margin example. Decide before MR-24 and MR-33.
- **Menu price input.** `menu_item_price.set` takes `price_gross` in centavos, so the model converts "$65.00" to 6500. The audit decision covered ingredient prices only. Accepting pesos would avoid that arithmetic; not decided.
- **Negative cost.** `DishMarginResolved.cost` is `Money` and accepts a negative value (a cost correction); the net-price checks still hold. Nothing else in the contract bounds it.
- **Phase 2 types.** `Figure.raw` and `Pct.raw` are `number | string` in the exported schemas and `MetricCardMsg.data` is JSON; the checks above are validators that the JSON Schema cannot express.

### 7.3 MR-11 "Done when": status

The criteria live in issue #11 (not in this repository). This is where this MR stands against them. On 2026-10-19 the project owner had the token criterion of #11 rewritten as a note deferring it to MR-20; the other criteria are unchanged.

| Criterion | Status |
|---|---|
| All four contracts are merged on main | **Pending.** C3 to C6 are implemented on the branch; #50 is open and has not been merged or approved. |
| Token budget check (formerly "Tool schemas pass the token budget check") | **Deferred to MR-20. MR-11 does not meet or implement it, and it no longer blocks closing #11** (the issue's checkbox is now a note). Nothing was measured (no `schemas/tool_tokens.json`, no API key was used) and no schema was cut. `propose_change` grew from 519 to 2397 characters (compact JSON), so by a character estimate it very likely needs a design cut, not a trim, once measured (D21). Measuring the budget and any optimization of the `propose_change` schema are MR-20's work. |
| CODEOWNERS is active | **Partly.** `.github/CODEOWNERS` is on the branch and takes effect only once it is on `main`. "Both devs must approve" is not enforced: owners on one line are alternatives and `main` has no branch protection (D12). |
