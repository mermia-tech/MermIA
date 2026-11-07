# MR-86 Costing engine: recompute only on change days (plan)

Goal: the same `dish_cost_snapshot` rows, faster. No contract change; every existing function keeps
its signature and meaning. One new migration, `20261107100000_costing_change_days.sql`, after
everything on main and the open PRs (#91/#94/#97 end at `20261106120000`).

## Approach

1. **Change days (all callers).** A dish's snapshot on day `d` is a function of the rows in effect on
   `d`: its recipe of record, the sub-recipes of record, the prices of record, the menu price per
   location, and whether each price is under 30 days old (`confirmed` grade). Those only change on
   a *boundary*: an `effective_from` or `effective_to + 1` of any recipe of the dish, of any recipe
   producing an ingredient the dish can reach (every version), of any price of a reachable
   ingredient or of a menu price of the dish, plus `effective_from + 30` of each reachable price.
   `app.compute_dish_costs_for` evaluates the unchanged per-day code (`recipe_of_record`,
   `recipe_cost`, the same insert expression) once per dish per boundary inside the range and
   copies that row set to every day up to the next boundary. A superset of boundaries is always
   safe (an extra boundary only costs time), so reachability uses every recipe version.
2. **Affected dishes only (apply paths).** A price on ingredient I can only move dishes whose recipe
   graph (any version, through sub-recipes) reaches I; a menu price or recipe change only moves its
   dish. `app.dish_cost_items(pending_change)` returns that list; `recompute_after_change` (new
   3-arg overload) and `backfill_dish_costs` rewrite only those dishes. Snapshots of other dishes
   are not touched (same row id).
3. **P6, per-location today.** `app.tenant_days(tenant)` = the earliest and latest business day of
   the tenant's locations. The tap recomputes `[max(effective_from, earliest), latest]`; the
   backfill range ends at `earliest - 1`. `app.tenant_today` is unchanged (open PRs use it).
4. **R10.** The committing double-tap test prices a throwaway ingredient it creates and deletes.

Rejected: a set-based rewrite (one SQL statement for all days). Faster in theory, but numeric scale
and rounding order would differ from the plpgsql walk, so "byte-identical" would need proof per
expression. Change days reuse the exact per-day code, so equivalence follows from the boundary set.

## Tests first

- pgTAP `97_costing_change_days.test.sql`: the old engine re-created as
  `app.compute_dish_costs_reference` inside the test transaction; identical rows (every column but
  id and timestamps) on the seed and on a synthetic tenant with backdated prices, `effective_to`,
  same-day sources, benchmark prices, CFDI freshness, recipe versions (draft and confirmed, dated),
  versioned sub-recipes, 3 locations with menu price changes, an inactive dish, an unpriced line.
  Affected-dish lists; untouched dishes keep their row ids; a two-time-zone tenant recomputes both
  business days.
- Existing: `90_costing`, `95_apply_pending_change`, `96_apply_recipe`, pytest `-m db`.

## Benchmark

`bench.py` (300 dishes, 10 locations, 150 ingredients, weekly prices, rolled back): 30 and 400 days
full recompute, one 7-day backfill chunk and a 400-day backfill for a price used by about 10 dishes,
before and after.
