# Fixtures

The shared fixture restaurant, **Taquería El Güero** (`08` C7, `13` H3), and sample Soft
Restaurant exports (`08` C8). Tests, the mock RPC server and the LLM eval all use these numbers.

Everything here, plus `supabase/seed.sql`, is generated. Don't edit it by hand:

```bash
uv run python -m mermia_fixtures           # regenerate after changing packages/fixtures
uv run python -m mermia_fixtures --check   # fail if a committed file is stale (also a test)
supabase db reset                          # loads supabase/seed.sql into the local database
```

The restaurant itself is written by hand in `packages/fixtures/src/mermia_fixtures/restaurant.py`.

## What it contains

- 2 locations: `L1` Centro and `L2` Polanco. Polanco sells less at prices about 10% higher.
- 8 weeks of item-daily and daily sales, Monday 2026-08-17 to Sunday 2026-10-11. "Today" in the eval is Monday 2026-10-12.
- 41 menu items, 61 ingredients (one is the prepared salsa verde), 3 suppliers with CFDI and market purchases.
- Recipes for the 15 items that sell the most units, plus a salsa verde sub-recipe.
- 2 price jumps: carne al pastor goes from $170 to $195/kg on 2026-09-21, and aguacate from $55 to $89/kg on 2026-09-28.
- 1 cancellation-heavy Saturday: Centro, 2026-10-10, with 17 cancelled tickets at ticket grain. Each line is voided by a waiter (Pepe 8, Luis 5, Ana 3, Marta 1) with a reason. These are the seed's only tickets. Paid sales stay at item and daily grain, so nothing counts twice.
- A "Martes de pastor" promotion: 15% off the pastor order on Tuesdays.
- Users: an owner (all locations) and one manager per location.

## Figures pinned by the eval (`13` H3)

| Example | Figure | Where it is checked |
|---|---|---|
| 1, 2 | Centro net sales: $184,320.50 for 2026-10-05..11 and $171,905.00 for 2026-09-28..10-04 | `test_fixtures.py`, `supabase/tests/60_seed.test.sql` |
| 4 | Tacos al pastor: cost $18.40, price $65.00, margin 71.7% | same |
| 7 | 2026-10-10 is the Saturday with the most cancellations, and every cancelled ticket has a waiter | same |
| 9 | Pastor meat costs less than $220/kg today ($195) | `test_fixtures.py` |

`el_guero/expected.json` has the other figures the eval and the RPC tests need: weekly and daily totals, this month's top 5 dishes, today's dish costs, the price jumps, cancellations by waiter, and yesterday's food cost.

Example 6 (food cost yesterday = 31.4%) is **not** pinned. The seed's figure is in `food_cost_yesterday` (Centro: 37.5% of recipe-covered sales without IVA, covering 71.4% of the day's sales). The eval question should quote that figure, or the definition should change. That's a decision for MR-19 and MR-24.

## Conventions

- Money is integer centavos. A sales line's `net` is `gross - discount`, **IVA included**. A day's `net_sales` is the sum of its item nets. `tax` is the IVA inside it, and `payment_mix` adds up to `net_sales`.
- Margin is `(price_gross - cost) / price_gross`, which is how `13` H3 example 4 computes it.
- Dish cost is `sum(qty * price per base unit * 100 / yield_pct)`, rounded once to centavos, half away from zero.
- To land exactly on the two pinned weeks, calibration adds units across each week's best sellers. It then takes the last few pesos (less than the cheapest item) off that Sunday's pastor order as a discount. That's why Centro's pastor order has a small, unexplained discount on 2026-10-04 ($6) and 2026-10-11 ($5).

## Sample SR exports (`sr/synthetic/`)

- `productos_vendidos_L1_2026-10-11.xlsx`: one day at Centro.
- `ventas_por_dia_L1_2026-10-05.xlsx`: Centro's last week.

Each file has a `.golden.json` beside it: the `NormalizedBatch` a parser must produce from it.

**These files are synthetic.** The column layout is a guess based on the SR 8 manual (`01` §3). The parsers (MR-15, MR-23) must be built against the pilot's real exports (MR-5). When those arrive, put them in `sr/<sr version>/` with their own golden files, and delete or keep these as extra cases.
