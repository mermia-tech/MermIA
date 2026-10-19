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
| 4 | Tacos al pastor: cost $18.40, menu price $65.00 ($56.03 without IVA), margin 67.2% on the net price | same |
| 6 | Centro food cost on 2026-10-11: 37.5% (not the 31.4% in `13` H3, see below) | `60_seed.test.sql` |
| 7 | 2026-10-10 is the Saturday with the most cancellations, and every cancelled ticket has a waiter | same |
| 9 | Pastor meat costs less than $220/kg today ($195) | `test_fixtures.py` |

`el_guero/expected.json` has the other figures the eval and the RPC tests need: weekly and daily totals, this month's top 5 dishes, today's dish costs, the price jumps, cancellations by waiter, and yesterday's food cost.

Example 6 quotes a food cost of 31.4% for yesterday, which the seed does not reproduce. That figure was written in the kickoff docs (commit `ab3062d`, 2026-10-15) before any data existed, so no dataset produced it. The seed gives **37.5%** for Centro on 2026-10-11, and it is traced in two independent ways:
- `food_cost_yesterday` in `expected.json` lists every covered item: units, dish cost, cost and net.
- `60_seed.test.sql` recomputes the 37.5% in SQL from `item_sales_agg`, `recipe`, `recipe_line` and `ingredient_price`, without the generator.

The figure is high mainly because bottled drinks are covered and cost a lot relative to their price: Coca-Cola runs at 54% and Corona at 46%. Alambre (49%) and torta de pastor (50%) add to it. Example 6 should quote 37.5% (MR-19), unless the team agrees a different definition (MR-24).

## Definitions

All money is integer centavos, rounded once, half away from zero.

| Figure | Formula | IVA | Discounts |
|---|---|---|---|
| Sales line `net` (`item_sales_agg.net`) | `gross - discount`, where `gross = units x menu price` | **included** (menu prices include 16% IVA) | subtracted |
| Daily `net_sales` (`daily_sales_agg`) | sum of that day's item nets | included | subtracted |
| Daily `tax` | IVA inside `net_sales`: `round(net_sales x 16 / 116)` | | |
| `payment_mix` | cash + card + transfer = `net_sales` | included | |
| Ticket line `net` (`sale_line.net`) | `qty x unit_price - discount` | **included** (`unit_price` is the menu price) | n/a (seed tickets have none) |
| Ticket line `tax` (`sale_line.tax`) | IVA inside the line: `round(net x 16 / 116)` | | |
| Ticket `total` / `tax` / `subtotal` (`sale_ticket`) | `total = sum(line net) - ticket discount`, `tax = sum(line tax)`, `subtotal = total - tax` | `total` included, `subtotal` excluded | |
| Dish cost | `sum(qty_base x price per base unit x 100 / yield_pct)` over the recipe, sub-recipes per gram of their yield, using the ingredient prices in effect that day | excluded (purchase prices are pre-IVA) | n/a |
| Net price | `price_gross - round(price_gross x 16 / 116)` | excluded | n/a |
| Dish margin | `margin_pct = (net_price - cost) / net_price`, `food_cost_pct = cost / net_price` (MR-11 D20) | excluded | n/a |
| Day food cost | `sum(units x dish cost) / (covered net - IVA inside it)`, dish cost rounded once per dish, over items with a recipe only | excluded | lower the denominator |
| Coverage | `covered net / day net` | same basis on both sides | |

Sales `net` keeps the meaning the MR-10 contract examples already use (`packages/contracts/tests/examples/daily_valid.json`: `payment_mix` adds up to `net_sales`, so `net_sales` includes IVA). **Ticket grain uses the same `net` as item and daily grain** (decided in #51): a line's `net` includes IVA, and `subtotal` is the ticket without IVA. Two documented rules need this. Batch totals must equal the sum of lines (`03` B.5), and `v_item_sales_daily` takes ticket lines where they exist and `item_sales_agg` otherwise (`09` §2). Both only work if `sum(sale_line.net)` is on the same basis as `item_sales_agg.net` and `net_sales`. `packages/contracts/tests/examples/ticket_valid.json` follows this rule, and `test_ticket_money_adds_up` (contracts and fixtures) plus `60_seed` check it.

Cost-side ratios (margin, food cost) take IVA out, as `03` requires ("food cost % = ingredient cost / (menu price / 1.16)").

Calibration: to land exactly on the two pinned weeks, calibration adds units across each week's best sellers. It then takes the last few pesos (less than the cheapest item) off that Sunday's pastor order as a discount. That's why Centro's pastor order has a small, unexplained discount on 2026-10-04 ($6) and 2026-10-11 ($5).

## Sample SR exports (`sr/synthetic/`)

- `productos_vendidos_L1_2026-10-11.xlsx`: one day at Centro.
- `ventas_por_dia_L1_2026-10-05.xlsx`: Centro's last week.

Each file has a `.golden.json` beside it: the `NormalizedBatch` a parser must produce from it.

**These files are synthetic.** The column layout is a guess based on the SR 8 manual (`01` §3). The parsers (MR-15, MR-23) must be built against the pilot's real exports (MR-5). When those arrive, put them in `sr/<sr version>/` with their own golden files, and delete or keep these as extra cases.
