# Mock RPC server (MR-13)

A small FastAPI app that answers the 11 read RPCs of the C3 contract
(`packages/contracts/src/mermia_contracts/rpc.py`, `docs/kickoff/09-architecture.md` §4.1) with
the C3 examples (`packages/contracts/tests/examples/rpc/`), which match the fixture restaurant
"Taquería El Güero" (`fixtures/el_guero/`). Dev B
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
| `get_top_dishes` | top 2 by units, 2026-10-01..11, both locations | `error` |
| `get_sales_breakdown` | by payment method, Centro, yesterday | `error`, `no_tickets` (by category) |
| `get_cancellations` | Centro, Saturday 2026-10-10: 17 cancelled tickets | `error` |
| `get_dish_margin` | tacos al pastor at Centro: margin 67.2 % on the net price | `error`, `ambiguous`, `needs_location` |
| `get_food_cost_pct` | Centro, yesterday: 37.5 % (target 32.0 %), coverage 71.4 %, by category | `error` |
| `get_menu_engineering` | Centro, last 30 days, Kasavana-Smith (03) | `error` |
| `get_cost_alerts` | last 30 days, Centro: the two price jumps, one breach | `error` |
| `get_data_status` | all sources | `error` |

The answer is the `response` of the example file, as it is: `tests/test_examples.py` checks that every
mock answer (data and meta) equals its example.

## Things to know

- **`nulls` is synthetic.** The fixtures report every figure on every day, so this variant is invented;
  it carries a `mock_synthetic` flag that says so.
- **Variants** are the example files named `<rpc>.<variant>.json` (`nulls`, `no_tickets`, `ambiguous`,
  `needs_location`, and `get_sales_summary.error`).
- **`get_cost_alerts` and `get_data_status`** serve the examples (one breach, 29 stale costs): the
  real definitions belong to MR-24.
- Every `raw` is a JSON number (a percentage has up to four decimals), as in the C3 examples.
- **Every answer carries a `mock_fixed_answer` flag** naming the canonical query it answers: the
  request values are not used, so a different query is not an error, only a flagged answer.
- Changes between figures (`abs_change`, `diff_vs_best`) have a signed `text` (`+$12,415.50`).

## Differences from the C3 examples

Only these, all on purpose:

- Every answer has one extra flag, `mock_fixed_answer`, naming the args of its own example; the
  `nulls` variant also has `mock_synthetic`.
- The `error` variant of the 10 RPCs without an error example is a generic `no_data` error
  (`Mock: the forced error variant`) with the `as_of` of that RPC's example.
- The canonical query is the example's `args`; the answer ignores what you send.

## Test

```bash
uv run pytest apps/mock-rpc
```

CI runs it with the rest of the workspace: if a response stops matching its C3 schema, it fails.
