# MR-32: apply_pending_change Implementation Plan (part 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Approved pending changes (price, menu price, batch approve, rollback; recipe in part 2) are applied safely and logged.

**Architecture:** One SQL function, `app.apply_pending_change(id uuid, user_id uuid) returns jsonb`, does every check and the write in one transaction and returns the C5 `ApplyResult` shape. A Python wrapper, `mermia_api.confirm.apply.apply_pending_change(conn, args)`, calls it and validates the result; it is the seam for the confirmation service (MR-37).

**Tech Stack:** Postgres (Supabase), pgTAP, Python 3.12, psycopg 3, pydantic v2. It uses what already exists:
- `mermia_contracts.pending` (C5: `PendingKind`, `ApplyPendingChangeArgs`, `ApplyResult`);
- `app.apply_batch` / `app.rollback_batch` (MR-16);
- `app.compute_dish_costs`, `app.price_of_record` (MR-25);
- `app.business_today` (MR-17).

**Spec:** `docs/superpowers/specs/2026-10-18-mr-11-contracts-rpc-tools-design.md` §3 (call, result, persisted effects, order of checks) and MR-10 spec 7.5.7. Branch `MR-32-pending-change`, cut from `main`.

## Approved decisions (owner, 2026-11-05)

- **D1 authorization.** Approve only if the kind is in the member's `can_approve`, the role is not `support`, and `required_role = 'owner'` requires the owner; the member's location scope must cover the target. MR-30 defaults stay (manager: imports only; default admin: no recipes; owner: everything). The recipe importer's `required_role = manager` stays.
- **D2 version.** Price kinds: the count of that ingredient's `ingredient_price` rows / of the (menu_item, location) `menu_item_price` rows. Recipe: `recipe_version` of the recipe of record (or null). Import batch: `import_batch.version`. All computed by `app.pending_base_version(kind, target_id, payload) returns int`, granted to `service_role`; proposers must use it.
- **D3 recompute (revised 2026-11-05).** The tap recomputes **today only** (`app.compute_dish_costs(tenant, today, today)`) inside the apply transaction after a price kind, so the reply shows fresh numbers; skipped when `effective_from` is in the future. The older days, `greatest(effective_from, today - 399)` to yesterday, are recomputed **after commit**: `app.backfill_dish_costs(pending_change_id, before, max_days)` (service_role only, SECURITY DEFINER) recomputes one chunk of at most 7 days per call, walking back from yesterday, and `mermia_api.confirm.backfill.backfill_dish_costs(conn, pending_change_id)` loops over the chunks, one transaction each, so the per-tenant `dish_cost_snapshot` advisory lock is held for a couple of seconds at most. MR-37 calls it in the background after the apply commits. Idempotent and safe to rerun. The apply audit `after.backfill` records `{from, to, requested_from, capped}`; `capped` is true when the 400-day limit cut the range.
- **D4 kg/g.** No hard guard. The audit `after` records `ingredient.base_unit`; MR-37 warns on jumps of 10x or more when it builds the diff.
- **Split.** Part 1: the core, `ingredient_price.set`, `menu_item_price.set`, `import_batch.approve`, `import_batch.rollback`, the recompute and the Python wrapper. Part 2: `recipe.upsert`. In part 1, `recipe.upsert` returns `failed` (no new result code).

## Global Constraints

- No change to `packages/contracts`. If one becomes necessary, stop and report.
- `apply_pending_change` is `SECURITY DEFINER`, `search_path = ''`, `EXECUTE` for `service_role` only.
- Check order (MR-11 §3.3): tenant from the row + membership (`not_found`, nothing revealed, no state change) -> authorization (`forbidden_role`, audit `pending_change.deny`, no state change) -> status (`already_applied` / `not_pending`) -> expiry (`expired`, audit) -> version (`conflict`, audit) -> write.
- The write runs in `begin ... exception`: on failure it rolls back, the row becomes `failed`, audit `pending_change.fail`. `42501` from `apply_batch` maps to `forbidden_role`.
- Audit actions, all with `pending_change_id`: `pending_change.apply` (before/after), `.expire`, `.conflict`, `.fail`, `.deny`.

## Tasks

### Task 1: tests first
- [ ] pgTAP `supabase/tests/95_apply_pending_change.test.sql`: one block per part-1 kind asserting `applied`, the write and exactly one `pending_change.apply` audit row; refusals with no write and no status change: Centro manager on a Polanco change, `support` role, `required_role = owner`, other-tenant user (`not_found`); `already_applied` (second tap), `not_pending` (rejected), `expired`, `conflict` (target moved), `failed` (temporary raising trigger); the pastor `dish_cost_snapshot` changes after a pastor price change; privileges `service_role` only.
- [ ] pytest `apps/api/tests/confirm/test_apply_pending_change.py` (`-m db`): the same codes through `ApplyResult`, plus a two-connection concurrent double tap (exactly one `applied`, the other `already_applied`).
- [ ] Run both; they fail.

### Task 2: migration
- [ ] `supabase/migrations/20261105090000_apply_pending_change.sql`: `app.pending_base_version`, the per-kind write, `app.apply_pending_change`, grants.
- [ ] `supabase db reset`, pgTAP green; `50_exposure` and `00_catalog` still pass.

### Task 3: Python wrapper
- [ ] `apps/api/src/mermia_api/confirm/apply.py`: `apply_pending_change(conn, args: ApplyPendingChangeArgs) -> ApplyResult`.
- [ ] pytest `-m db` green; `gen_db_models --check` clean; `/check` green.

## Follow-up fixes (review, 2026-11-05)
- Indexes without the `tenant_id` prefix for the costing engine and `pending_base_version`: `ingredient_price(ingredient_id, effective_from)`, `menu_item_price(menu_item_id, location_id, effective_from)`, `recipe(menu_item_id)`, `recipe(produces_ingredient_id)`, `recipe_line(recipe_id)` (about 6x faster).
- Transient errors (40P01, 40001, 55P03; 57014 already escapes) are re-raised, not marked `failed`: the change stays `pending` for a retry.
- `menu_item_price.set` with no price covering the date takes the location's latest tax rate for the item; with none it ends `failed`.

## Known risks (noted in the PR, not fixed here)
- A manual price loses to a same-day CFDI price in `app.price_of_record`.
- No caller creates `import_batch.approve` changes yet (loader vs MR-37).
- `apply_batch` hard-codes owner/manager while apply uses `can_approve` (an admin allowed by `can_approve` gets `forbidden_role`).
- No channel or request_id in the audit rows.
- Phase 2 dashboard "under the user's session" (09 §5.3) vs `service_role` only.
