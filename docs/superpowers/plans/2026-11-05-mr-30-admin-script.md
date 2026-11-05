# MR-30: tenant and user admin script

**Goal:** one command creates (or brings up to date) a restaurant tenant, its locations and its
users with roles, for concierge onboarding. Safe to rerun, works under the RLS model, short
README note.

**Command:** `uv run python -m mermia_api.admin <spec.yaml> [--dry-run] [--auth-users]`, on the
postgres connection in `MERMIA_DB_URL` (or `--db-url`), like the recipe template CLI (MR-25).

## Design

- **Spec file (YAML, so JSON also works):** `tenant` (name, rfc), `locations` (name, timezone,
  address, SR version/edition), `users` (name, phone, email, role, locations, can_approve).
  Pydantic validates it before any database work. Example:
  `apps/api/src/mermia_api/admin/example.yaml`.
- **Declarative and idempotent.** Natural keys: tenant by normalized name (or a pinned `id`),
  location by normalized name inside the tenant (or `id`), user by `phone_e164` (unique in the
  DB), membership by `(tenant_id, user_id)` (unique), WhatsApp identity by `(channel,
  external_id)` (unique), source by `(location, kind)`. A rerun updates what differs and creates
  nothing twice. Nothing is ever deleted: rows in the DB but not in the spec are reported only.
- **One transaction** plus `pg_advisory_xact_lock`, so two operators cannot interleave.
  `--dry-run` runs everything and rolls back.
- **What a user gets:** `app_user`, `membership` (scope `all` gives `location_ids null` +
  `all_locations true`; a list gives those ids), and a verified `channel_identity` (`whatsapp`,
  `external_id` = E.164 digits without `+`) so the channel can resolve the sender (09 §2.1,
  MR-10 spec 7.5.6). No `consent_log`: consent comes from the user (MR-29).
- **Role defaults** (`can_approve`, from the seed and 09 §5.1): owner = all five C5 kinds; manager
  = `import_batch.approve/rollback` (the seed's narrower set: only owner approves recipes); admin
  = `ingredient_price.set`, `recipe.upsert`, `menu_item_price.set`; support = none (09: support
  never approves; the spec cannot override it). Owner, admin and support default to all
  locations; a manager must list locations.
- **Sources:** each location gets an `sr_report` and a `manual` source when it has none of that
  kind (MR-25 decision 4: template uploads need a manual source).
- **Safety:** a phone that already belongs to a user of another tenant under a different name is
  refused (likely a typo that would hand this tenant to someone else). The spec needs at least one
  owner. Phones are masked in all output (`+52******0001`); the DB URL is printed without its
  password.
- **Audit:** one `audit_log` row per created or updated entity (`actor_kind system`,
  `action admin.<entity>.create|update`, `request_id` = the run id); no phone numbers in
  before/after.
- **Supabase Auth (`--auth-users`, Phase 2 dashboard):** for users with an email, find the auth
  user by email in `auth.users`, or create it through the Admin API (`MERMIA_API_URL`,
  `MERMIA_SERVICE_ROLE_KEY`), and set `app_user.auth_user_id`. Off by default; refuses a
  non-loopback API URL unless `--allow-remote-auth`. Skipped under `--dry-run`.

## Tests first

`apps/api/tests/admin/`:
- `test_spec.py` (no DB): validation (phones, duplicates, manager scope, unknown location, support
  approvals, at least one owner), defaults, masking.
- `test_onboard.py` (`-m db`, rolled-back transaction): creates everything; a rerun creates
  nothing and audits nothing; a changed spec updates; the phone-typo guard; dry run saves nothing;
  **under RLS** with claims computed from `membership` (as the issuer will, spec 7.5.5) the owner
  sees only the new tenant and every location, a manager only their location and its sources.
- `test_auth.py` (`-m db -m rest`): `--auth-users` against the local stack (127.0.0.1:55321).

No migration and no change to `packages/contracts`.
