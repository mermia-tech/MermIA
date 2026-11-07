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
  - Tenants one at a time; per tenant the range is split into chunks of at most 31 days, newest
    first, one transaction each (the lock is held per chunk only).
  - A tenant that fails is logged and reported (`SQLSTATE ExceptionClass`, no message); the run
    goes on. A broken connection is raised (nothing else can run). MR-87's transient/permanent
    split (`confirm.backfill.is_transient`) tags each failure.
  - CLI `python -m mermia_api.costing.nightly [--days N] [--today YYYY-MM-DD]`; exit 1 when a
    tenant failed. Cron line in the docstring. No scheduler, no Procrastinate.

## Tests first

- db (pytest): seed today equals `compute_dish_costs`; two time zones; rerun keeps row ids;
  failing tenant reported, others done; runs as service_role; inactive dish gets no row; 400-day
  window runs in chunks of at most 31 days; the SQL refuses more than 31 days.
- pgTAP: privileges of the two new functions.
- Unit: chunk planner, argument parsing.

## Out of scope

- Calling the cost-alert evaluator (#91) and the weekly report (#97): TODO after #91 merges.
- Scheduling (cron/Render/Procrastinate).
