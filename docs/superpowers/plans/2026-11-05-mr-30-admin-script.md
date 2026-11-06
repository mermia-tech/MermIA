# MR-30: tenant and user admin script

**Goal:** one command creates (or brings up to date) a restaurant tenant, its locations and its
users with roles, for concierge onboarding. Safe to rerun, works under the RLS model, short
README note.

**Command:** `uv run python -m mermia_api.admin <spec.yaml> --operator <handle> [--dry-run]`, on the
postgres connection in `MERMIA_DB_URL` (or `--db-url`), like the recipe template CLI (MR-25).

## Design

- **Spec file (YAML, so JSON also works):** `tenant` (name, rfc), `locations` (name, timezone,
  address, SR version/edition), `users` (name, phone, email, role, locations, can_approve).
  Pydantic validates it before any database work. Example:
  `apps/api/src/mermia_api/admin/example.yaml`.
- **Declarative and idempotent.** Natural keys: tenant only by a pinned `id` (without one it is
  created, and refused if a tenant with the same normalized name exists; the first run prints
  the id to pin), location by normalized name inside the tenant (or `id`; two spec entries on one
  row are refused), user by canonical `phone_e164` (unique in the DB), membership by
  `(tenant_id, user_id)` (unique), WhatsApp identity by `(channel, external_id)` (unique), source
  by `(location, kind)`. A rerun updates what differs and creates nothing twice. Nothing is ever
  deleted: rows in the DB but not in the spec are reported, members with a warning that they
  keep their access. Optional fields left out (rfc, timezone, address, email, SR version) keep
  the DB value; a new location gets `America/Mexico_City`.
- **One transaction** plus `pg_advisory_xact_lock`, so two operators cannot interleave.
  `--dry-run` runs everything and rolls back.
- **What a user gets:** `app_user`, `membership` (scope `all` gives `location_ids null` +
  `all_locations true`; a list gives those ids), and a verified `channel_identity` (`whatsapp`,
  `external_id` = canonical digits without `+`; `mermia_api.phone`: +52 1 + 10 digits becomes
  +52 + 10 digits, and MR-27 looks senders up with `canonical_wa_id`) so the channel can resolve
  the sender (09 §2.1,
  MR-10 spec 7.5.6). No `consent_log`: consent comes from the user (MR-29).
- **Role defaults** (`can_approve`, from the seed and 09 §5.1): owner = all five C5 kinds; manager
  = `import_batch.approve/rollback` (the seed's narrower set: only owner approves recipes); admin
  = `ingredient_price.set`, `menu_item_price.set` (no `recipe.upsert`: MR-25, owner only); support = none (09: support
  never approves; the spec cannot override it). Owner, admin and support default to all
  locations; a manager must list locations.
- **Sources:** each location gets an `sr_report` and a `manual` source when it has none of that
  kind (MR-25 decision 4: template uploads need a manual source).
- **Safety:** a phone that already belongs to a user under a different name is refused (likely a
  typo that would hand this tenant to someone else). A user who is a member of another tenant
  joins only with `existing_user: true`, and their shared name and email are never changed.
  Duplicate YAML keys, pinned location ids, phones and emails are refused. The spec needs at least one
  owner. Phones are masked in all output (`+52******0001`); the DB URL is printed without its
  password.
- **Audit:** one `audit_log` row per created or updated entity (`actor_kind system`,
  `action admin.<entity>.create|update`, `request_id` = `mermia_api.admin:<operator>:<run id>`);
  no phone numbers or emails in before/after (`email_changed: true` instead).
- **Supabase Auth users: deferred to Phase 2** (dropped after review). When added: never adopt an
  existing auth user found by email; link only ids returned by the Admin API's `create_user`.

## Tests first

`apps/api/tests/admin/`:
- `test_spec.py` (no DB): validation (phones, duplicates, manager scope, unknown location, support
  approvals, at least one owner), defaults, masking.
- `test_onboard.py` (`-m db`, rolled-back transaction): creates everything; a rerun creates
  nothing and audits nothing; a changed spec updates; the phone-typo guard; dry run saves nothing;
  **under RLS** with claims computed from `membership` (as the issuer will, spec 7.5.5) the owner
  sees only the new tenant and every location, a manager only their location and its sources.
- `apps/api/tests/test_phone.py`: canonical phones and wa_ids.

No migration and no change to `packages/contracts`.
