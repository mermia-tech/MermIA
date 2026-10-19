# MR-17: source of truth for the read RPCs

Status: decided 2026-10-19 (F resolved with a schema prerequisite). Draft for Issue 17, kept local for review. Architecture reference: `docs/kickoff/09-architecture.md` §2.6 (line 179).

## Decision

1. **Source.** The read RPCs read `v_daily_sales` and `v_item_sales_daily`, created in MR-17. They unify ticket and aggregate grain and include only batches with `status = 'applied'`.
2. **`daily_location_metrics`.** No MR-17 RPC reads it. It stays an optional cache until we define its writer, refresh strategy and consistency tests against the unified views. Derived metrics are not seeded by hand.
3. **IVA.** `net_sales` includes IVA. The ex-IVA conversion applies only to food cost and margin.
4. **Regression tests.** Each RPC is compared with a direct calculation over the seeded source rows, including Centro $184,320.50 (2026-10-05..11), $171,905.00 (2026-09-28..10-04) and the 17 cancelled tickets.

## Rules

**A. Precedence.** For sales, ticket counts and average ticket, use ticket-level data only when at least one valid *paid* ticket exists for that `(location, date)`. Cancelled tickets alone never override the aggregate. Otherwise fall back to `daily_sales_agg`. Sources are never mixed within a `(location, date)` for these metrics.

**B. Granularity.** The source is chosen per `(location, date)`.

**C. Cancellations.** The aggregate stays the source of daily sales totals. Ticket-level records feed the waiter and reason breakdowns where available. Reconciliation between the two is validated without double-counting.

**D. Item sales.** Cancelled ticket lines never reduce sold quantities in `v_item_sales_daily`.

**E. Batch status.** Tests cover applied, non-applied and replaced (superseded) batches. The seed has only `applied` batches (225), so the tests create the other two.

**F. Null `batch_id` (decided; no rows possible today).** A null `batch_id` never decides inclusion by itself, and `batch_id IS NULL` is never treated as `status = 'applied'`.

- Batch-backed rows stay under the explicit applied-batch rule (E).
- A ticket without a batch may count in paid-sales metrics only if its source and status establish a valid, finalized sale. Voided, cancelled or otherwise invalid batchless tickets are excluded from paid-sales metrics and kept for cancellation metrics where appropriate.
- Verified against the schema on 2026-10-19 (`supabase/migrations/20261018185056_catalog_and_sales.sql:147-179`, `20261018184746_enums.sql`, `20261018184909_identity_and_sources.sql:112`):
  - `sale_ticket.batch_id` is `NOT NULL` with a foreign key to `import_batch`. A ticket without a batch **cannot exist today**, so the rule has no row to apply to and the seed has none.
  - `sale_ticket.status` is `app.ticket_status` = `paid | cancelled`. There is no open, void or unprocessed state.
  - `source.kind` has `sr_erp_push`, `sr_connector` and `mermia_pos`, but `source.status` is free text tagged "values not yet specified", and `sale_ticket.closed_at` is nullable.
- **Prerequisite, not a guess.** The schema cannot tell a valid finalized batchless sale from an unprocessed or invalid one. Before any POS/push path writes tickets without a batch, a ticket would need (a) `batch_id` made nullable by a migration and (b) a defined finalized signal (for example a status value or a non-null `closed_at` plus a source state with specified values). Until then MR-17 keeps every ticket batch-backed, and the views do not special-case null batches.
- Tests to write in MR-17 once the prerequisite exists: a valid POS/push ticket with null `batch_id` is counted; a cancelled one is excluded from paid sales and kept for cancellations; an unfinalized or invalid one is excluded. Until then, one test proves that the current schema rejects a ticket with null `batch_id`.

## Required tests

- **Mixed grain, Centro 2026-10-10.** The seed has the daily aggregate (net_sales 3,789,500 centavos = $37,895.00, 134 tickets, 17 cancellations worth 265,500) and 17 cancelled tickets in `sale_ticket`, no paid ones. `v_daily_sales` must return $37,895.00 and 134 tickets for that day. The 17 cancelled tickets must not override them or be added to them.
- **Paid ticket wins.** A day with at least one paid ticket takes sales, tickets and average ticket from tickets only, with no double count against the aggregate.
- **Cancelled lines and items.** `v_item_sales_daily` units for 2026-10-10 are unchanged by the 17 cancelled lines.
- **Batch status.** Rows from non-applied and superseded batches do not appear in either view.
- **Totals.** Centro $184,320.50 and $171,905.00 match a direct sum over the seeded source rows.

## Not decided here

When `daily_location_metrics` gets a writer, it needs its own decision and a consistency test against the views.
