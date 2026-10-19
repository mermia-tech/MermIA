# Mock RPC server (MR-13)

A small FastAPI app that answers the 11 read RPCs of the C3 contract
(`packages/contracts/src/mermia_contracts/rpc.py`, `docs/kickoff/09-architecture.md` §4.1) with
numbers computed from the fixture restaurant "Taquería El Güero" (`fixtures/el_guero/`). Dev B
builds the agent against it until the real SQL RPCs exist (MR-17, MR-24, MR-31).

## Run

```bash
uv run uvicorn mermia_mock_rpc.app:app --port 8001
curl -s -X POST localhost:8001/rpc/get_sales_summary -H 'content-type: application/json' \
  -d '{"period": "last_week"}'
```

`POST /rpc/{name}` with the RPC arguments as the JSON body. The body is checked with the RPC's C3
args model (422 if it does not fit). `?variant=` picks a special answer (422 if the RPC has no
such variant). An unknown RPC is a 404. Every answer is checked against
`RpcEnvelope[RPCS[name].data]` before it is sent.

## One fixed answer per RPC

The answer does **not** change with the arguments: each RPC answers its canonical query below,
whatever you send. "Today" is Monday 2026-10-12 (`expected.json`); the data ends on 2026-10-11.

| RPC | Canonical query | Variants |
|---|---|---|
| `get_sales_summary` | Centro, last week (2026-10-05..11): $184,320.50, +7.2 % | `error`, `nulls` |
| `compare_periods` | `net_sales`, Centro, last week against the week before | `error` |
| `compare_locations` | `net_sales`, last week, Centro against Polanco | `error` |
| `get_top_dishes` | top 5 by units, this month, both locations | `error` |
| `get_sales_breakdown` | by payment method, Centro, yesterday | `error`, `no_tickets` (by category) |
| `get_cancellations` | Centro, Saturday 2026-10-10: 17 cancelled tickets | `error` |
| `get_dish_margin` | tacos al pastor at Centro: margin 67.2 % on the net price | `error`, `ambiguous`, `needs_location` |
| `get_food_cost_pct` | Centro, yesterday: 37.5 %, coverage 71.4 % | `error` |
| `get_menu_engineering` | Centro, last 30 days, Kasavana-Smith (03) | `error` |
| `get_cost_alerts` | last 30 days: the two price jumps | `error` |
| `get_data_status` | all sources | `error` |

Every figure comes from the fixture JSON; `expected.json` supplies the ones it pins. Pinned
figures are asserted in `tests/test_rpcs.py`.

## Things to know

- **`nulls` is synthetic.** The fixtures report every figure on every day, so this variant takes
  yesterday's real `net_sales` and blanks the rest, with a `partial_data` flag whose message says so.
- **`get_cost_alerts` has no breaches or suggestions.** The fixtures define no food-cost target and
  no price suggestion; inventing them would be a guess.
- **`get_data_status.stale_costs` is 0** and `get_menu_engineering` uses the textbook rule (popular =
  at least 70 % of an equal share of units; high margin = at or above the units-weighted average).
  The real definitions belong to MR-24.
- **`get_sales_breakdown` tickets are `null`**: `daily_sales_agg.payment_mix` holds amounts only (D23).
- Every `raw` is a JSON number (a percentage has up to four decimals), as in the C3 examples.
- **Every answer carries a `mock_fixed_answer` flag** naming the canonical query it answers: the
  request values are not used, so a different query is not an error, only a flagged answer.
- Changes between figures (`abs_change`, `diff_vs_best`) have a signed `text` (`+$12,415.50`).
- `meta.coverage_pct` is the share of the period's days that have a daily row.

## Differences from the C3 examples

The examples in `packages/contracts/tests/examples/rpc/` were written before the fixtures existed
and still disagree with them (MR-11 spec §7.2). The mock does **not** serve them and the contract
is untouched. Do not compare the two:

| What | C3 examples | Mock (fixtures) |
|---|---|---|
| "Last week" | 2026-10-12..18 | 2026-10-05..11 |
| `as_of` | 2026-10-19 | 2026-10-12 |
| Location and dish ids | `0f7a1c52-…` | the fixture ids (`705e8e51-…` for Centro) |
| Tacos al pastor | "Taco al pastor", cost $18.20, menu price $58.00, net $50.00 | "Tacos al pastor (orden de 3)", cost $18.40, menu price $65.00, net $56.03 |
| Week figures | 912 tickets, 1,304 guests, discounts $2,150.00 | what `daily_sales_agg` sums to (648 tickets, 1,428 guests, $414.50) |
| Top dish | 640 units | 1,208 units (both locations, this month) |
| Food cost | 34.1 % | 37.5 % (traced in `fixtures/README.md`) |
| Price move | pastor to $220/kg, +22.2 % | $170 to $195/kg, +14.7 %, plus aguacate +61.8 % |
| Cost alerts | one breach and one suggestion | none |
| Data status | one missing day, 3 stale costs, 87.5 % | no missing day, 0 stale, 100 % |
| `coverage_pct` | 87.5 | 100.0 |
| Payment breakdown | tickets per method | tickets `null` |

When the examples are aligned with the fixtures, these differences go away; until then the fixtures
are the reference for the eval (MR-19) and for this mock.

## Test

```bash
uv run pytest apps/mock-rpc
```

CI runs it with the rest of the workspace: if a response stops matching its C3 schema, it fails.
