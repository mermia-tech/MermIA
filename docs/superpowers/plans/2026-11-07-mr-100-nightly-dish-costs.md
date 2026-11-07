# MR-100 Nightly dish-cost job: plan

Goal: every tenant has a `dish_cost_snapshot` row for every active dish at each location's own
business today, even on a day nobody approves a change (#100).

## Design

- **SQL (migration `20261107110000_nightly_dish_costs.sql`)**
  - `app.nightly_dish_cost_range(tenant, days)`: `[earliest location today - (days - 1), latest
    location today]`; nulls for a tenant without locations.
  - `app.fill_dish_costs(tenant, from_date, to_date)`: at most 31 days (22023 otherwise). Takes the
    per-tenant lock (`app.lock_dish_costs`), then, per group of locations sharing a business today,
    fills `[from_date, least(to_date, that today)]` for every active item that has a priced
    (location, day) with no snapshot. It reuses MR-86's change days and `app.write_dish_cost_rows`
    (insert only, `on conflict do nothing`): rows that exist keep their ids, a rerun writes nothing.
    Same rows as `app.compute_dish_costs` for the days it fills.
  - Both service_role only (revoked from public, anon, authenticated).
- **Python (`mermia_api.costing.nightly`)**
  - `run_nightly_dish_costs(conn, *, today=None, days=2, only=None) -> NightlyResult`.
  - Tenant ids from `public.tenant` only (`only` is a test seam that narrows that list).
  - Tenants one at a time; per tenant the range is split into chunks of at most 7 days, newest
    first, one transaction each (the lock is held per chunk only; the SQL itself allows 31).
    Each transaction runs `set local role service_role` and sets `lock_timeout` 5 s and
    `statement_timeout` 60 s. The job needs a direct or session-mode DB URL (not the pooler).
  - A tenant that fails is logged and reported (`SQLSTATE ExceptionClass`, no message); the run
    goes on. A broken connection is raised (nothing else can run). MR-87's transient/permanent
    split (`confirm.backfill.is_transient`) tags each failure.
  - CLI `python -m mermia_api.costing.nightly [--days N] [--today YYYY-MM-DD]`; exit 1 when a
    tenant failed. Cron line in the docstring. No scheduler, no Procrastinate.

## Tests first

- db (pytest): seed today equals `compute_dish_costs`; two time zones; rerun keeps row ids;
  failing tenant reported, others done; runs as service_role; inactive dish gets no row; 400-day
  window runs in 58 chunks of at most 7 days; the SQL refuses more than 31 days.
- pgTAP: privileges of the two new functions.
- Unit: chunk planner, argument parsing.

## Out of scope

- Calling the cost-alert evaluator (#91) and the weekly report (#97): TODO after #91 merges.
- Scheduling (cron/Render/Procrastinate).

## Benchmark (7-day chunks)

One tenant: 300 dishes, 10 locations, 150 ingredients, 2 years of weekly prices, no snapshots;
local Supabase, rolled back. Stagger = each ingredient's price on its own weekday.

| window | weekly | stagger | rerun | x50 tenants (est.) |
|---|---|---|---|---|
| 2 days | 0.65 s | 0.97 s | 0.01 s | 33-49 s |
| 7 days (1 chunk) | 1.44 s | 2.78 s | 0.03 s | 1.2-2.3 min |
| 30 days (5 chunks) | 6.4 s | 11.2 s | 0.2-0.4 s | 5.3-9.3 min |
| 400 days (58 chunks) | 136 s | 165 s | 48 s | - |

The 30-day stagger case misses the ticket's 1-4 min target (about 9 min for 50 tenants); it is a
full catch-up from no rows, which a normal night never does. Handled in #102.
