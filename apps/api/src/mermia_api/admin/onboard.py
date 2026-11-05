"""Brings one tenant to what its onboarding spec says (MR-30), inside the caller's transaction.

Runs on the postgres connection (the admin URL): the identity tables are class X, so no client
role can write them, and the script is the concierge path that does. Natural keys, so a rerun
creates nothing twice:
- tenant: its pinned id, or its name after normalize_name (two matches: refused, pin one);
- location: its pinned id (must be in the tenant), or its normalized name in the tenant;
- app_user: phone_e164 (unique). A phone whose user has another name and belongs to another
  tenant is refused: it is most likely a typo that would hand this tenant to someone else;
- membership: (tenant_id, user_id) (unique); channel_identity: (whatsapp, wa_id) (unique);
- source: one sr_report and one manual source per location (MR-25 decision 4), if missing.

Nothing is deleted: locations and members in the database but not in the spec are kept and
reported in the notes. Every created or updated row gets an audit_log row (actor_kind system,
request_id `mermia_api.admin:<run id>`), with no phone number or wa_id in before/after. The
WhatsApp identity is created verified: the operator confirmed the number during onboarding.
Consent (consent_log) is not recorded here; the user gives it on WhatsApp (MR-29).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from mermia_api.admin.auth import AuthAdmin
from mermia_api.admin.spec import (
    LocationSpec,
    OnboardingSpec,
    TenantSpec,
    UserSpec,
    mask_phone,
    wa_id,
)
from mermia_contracts.keys import normalize_name

ACTOR = "mermia_api.admin"
SOURCE_KINDS = ("sr_report", "manual")
LOCK_KEY = "mermia_api.admin"

Action = Literal["created", "updated", "unchanged"]
Conn = psycopg.Connection[Any]

AUDIT_ENTITY = {
    "tenant": "tenant",
    "location": "location",
    "source": "source",
    "user": "app_user",
    "whatsapp": "channel_identity",
    "membership": "membership",
    "auth": "app_user",
}
AUDIT_VERB = {"created": "create", "updated": "update"}


class OnboardingError(ValueError):
    """The spec cannot be applied safely; nothing was saved."""


@dataclass(frozen=True)
class Change:
    entity: str  # a key of AUDIT_ENTITY
    label: str  # what the operator reads; never a full phone number
    action: Action
    entity_id: UUID
    detail: str = ""
    before: Mapping[str, Any] | None = field(default=None, repr=False)
    after: Mapping[str, Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Summary:
    run_id: UUID
    tenant_id: UUID
    tenant_name: str
    changes: tuple[Change, ...]
    notes: tuple[str, ...]
    audit_rows: int


def onboard(conn: Conn, spec: OnboardingSpec, *, auth: AuthAdmin | None = None) -> Summary:
    """Applies the spec in the caller's transaction; the caller commits or rolls back."""
    conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (LOCK_KEY,))
    run_id = uuid.uuid4()
    tenant = _tenant(conn, spec.tenant)
    changes: list[Change] = [tenant]
    notes: list[str] = []
    loc_ids = _locations(conn, tenant.entity_id, spec.locations, changes, notes)
    for loc in spec.locations:
        changes += _sources(conn, tenant.entity_id, loc_ids[normalize_name(loc.name)], loc.name)
    user_ids = []
    for user in spec.users:
        user_id = _user(conn, tenant.entity_id, user, changes, notes)
        user_ids.append(user_id)
        changes.append(_whatsapp(conn, user_id, user))
        changes.append(_membership(conn, tenant.entity_id, user_id, user, loc_ids))
        if auth is not None:
            linked = _auth(conn, user_id, user, auth)
            changes += [linked] if linked else []
            notes += [] if linked else [f"{user.name}: no email, no auth user"]
    notes += _members_not_in_spec(conn, tenant.entity_id, user_ids)
    audited = _audit(conn, tenant.entity_id, run_id, changes)
    return Summary(
        run_id, tenant.entity_id, spec.tenant.name, tuple(changes), tuple(notes), audited
    )


# Generic row helpers ---------------------------------------------------------------------------


def _insert(conn: Conn, table: str, values: Mapping[str, Any]) -> UUID:
    query = sql.SQL("insert into public.{} ({}) values ({}) returning id").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join(sql.Placeholder() * len(values)),
    )
    row = conn.execute(query, list(values.values())).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def _sync(
    conn: Conn, table: str, row_id: UUID, current: Mapping[str, Any], desired: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Updates the columns whose desired value differs; returns (before, after) of those."""
    after = {k: v for k, v in desired.items() if current[k] != v}
    if after:
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(k)) for k in after
        )
        conn.execute(
            sql.SQL("update public.{} set {} where id = %s").format(
                sql.Identifier(table), assignments
            ),
            [*after.values(), row_id],
        )
    return {k: current[k] for k in after}, after


def _upsert(
    conn: Conn,
    table: str,
    found: tuple[UUID, Mapping[str, Any]] | None,
    desired: Mapping[str, Any],
    insert_extra: Mapping[str, Any],
) -> tuple[UUID, Action, dict[str, Any] | None, dict[str, Any]]:
    """Inserts desired + insert_extra when nothing was found, else syncs desired."""
    if found is None:
        values = {**insert_extra, **desired}
        return _insert(conn, table, values), "created", None, dict(desired)
    row_id, current = found
    before, after = _sync(conn, table, row_id, current, desired)
    return row_id, ("updated" if after else "unchanged"), before, after


def _given(**values: Any) -> dict[str, Any]:
    """The optional fields the spec states; None means the spec leaves the column as it is."""
    return {k: v for k, v in values.items() if v is not None}


# Tenant and locations --------------------------------------------------------------------------


def _tenant(conn: Conn, spec: TenantSpec) -> Change:
    rows = conn.execute("select id, name, rfc from public.tenant").fetchall()
    if spec.id is not None:
        matches = [r for r in rows if r[0] == spec.id]
        if not matches:
            raise OnboardingError(f"no tenant with id {spec.id}")
    else:
        matches = [r for r in rows if normalize_name(r[1]) == normalize_name(spec.name)]
        if len(matches) > 1:
            raise OnboardingError(
                f"{len(matches)} tenants are named like {spec.name!r}; pin one with tenant.id"
            )
    found = (matches[0][0], {"name": matches[0][1], "rfc": matches[0][2]}) if matches else None
    desired = {"name": spec.name, **_given(rfc=spec.rfc)}
    tid, action, before, after = _upsert(conn, "tenant", found, desired, {})
    return Change("tenant", spec.name, action, tid, before=before, after=after)


def _locations(
    conn: Conn,
    tenant_id: UUID,
    specs: Sequence[LocationSpec],
    changes: list[Change],
    notes: list[str],
) -> dict[str, UUID]:
    """Creates or updates each location; returns normalized name -> id."""
    cols = ("name", "timezone", "address", "sr_version", "sr_edition")
    rows = {
        r[0]: dict(zip(cols, r[1:], strict=True))
        for r in conn.execute(
            "select id, name, timezone, address, sr_version, sr_edition from public.location"
            " where tenant_id = %s",
            (tenant_id,),
        )
    }
    ids: dict[str, UUID] = {}
    for loc in specs:
        found_id = _find_location(rows, loc)
        desired = {
            "name": loc.name,
            "timezone": loc.timezone,
            **_given(address=loc.address, sr_version=loc.sr_version, sr_edition=loc.sr_edition),
        }
        found = (found_id, rows[found_id]) if found_id else None
        lid, action, before, after = _upsert(
            conn, "location", found, desired, {"tenant_id": tenant_id}
        )
        ids[normalize_name(loc.name)] = lid
        changes.append(Change("location", loc.name, action, lid, before=before, after=after))
    notes += [
        f"location {row['name']!r} is not in the spec (kept)"
        for lid, row in rows.items()
        if lid not in ids.values()
    ]
    return ids


def _find_location(rows: Mapping[UUID, Mapping[str, Any]], loc: LocationSpec) -> UUID | None:
    if loc.id is not None:
        if loc.id not in rows:
            raise OnboardingError(f"no location with id {loc.id} in this tenant")
        return loc.id
    matches = [
        lid for lid, r in rows.items() if normalize_name(r["name"]) == normalize_name(loc.name)
    ]
    if len(matches) > 1:
        raise OnboardingError(
            f"{len(matches)} locations are named like {loc.name!r}; pin one with id"
        )
    return matches[0] if matches else None


def _sources(conn: Conn, tenant_id: UUID, location_id: UUID, label: str) -> list[Change]:
    out = []
    for kind in SOURCE_KINDS:
        row = conn.execute(
            """select id from public.source where tenant_id = %s and location_id = %s
               and kind = %s order by created_at, id limit 1""",
            (tenant_id, location_id, kind),
        ).fetchone()
        if row is not None:
            out.append(Change("source", f"{label} {kind}", "unchanged", row[0]))
            continue
        values = {
            "tenant_id": tenant_id,
            "location_id": location_id,
            "kind": kind,
            "status": "active",
        }
        sid = _insert(conn, "source", {**values, "config": Jsonb({})})
        out.append(Change("source", f"{label} {kind}", "created", sid, after=values))
    return out


# Users -----------------------------------------------------------------------------------------


def _user(
    conn: Conn, tenant_id: UUID, user: UserSpec, changes: list[Change], notes: list[str]
) -> UUID:
    row = conn.execute(
        "select id, name, email from public.app_user where phone_e164 = %s", (user.phone,)
    ).fetchone()
    label, phone = user.name, mask_phone(user.phone)
    desired = {"name": user.name, **_given(email=user.email)}
    found = (row[0], {"name": row[1], "email": row[2]}) if row else None
    if row is not None:
        others = _other_tenants(conn, row[0], tenant_id)
        if others and normalize_name(row[1]) != normalize_name(user.name):
            raise OnboardingError(
                f"{mask_phone(user.phone)} already belongs to {row[1]!r}, a member of another"
                f" tenant; check the number (spec says {user.name!r})"
            )
        if others:
            notes.append(f"{user.name} is also a member of {others} other tenant(s)")
    uid, action, before, after = _upsert(
        conn, "app_user", found, desired, {"phone_e164": user.phone}
    )
    changes.append(Change("user", label, action, uid, phone, before=before, after=after))
    return uid


def _other_tenants(conn: Conn, user_id: UUID, tenant_id: UUID) -> int:
    row = conn.execute(
        "select count(*) from public.membership where user_id = %s and tenant_id <> %s",
        (user_id, tenant_id),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _whatsapp(conn: Conn, user_id: UUID, user: UserSpec) -> Change:
    label, phone = user.name, mask_phone(user.phone)
    row = conn.execute(
        """select id, user_id, verified_at from public.channel_identity
           where channel = 'whatsapp' and external_id = %s""",
        (wa_id(user.phone),),
    ).fetchone()
    if row is not None and row[1] != user_id:
        raise OnboardingError(f"WhatsApp {phone} is linked to another user")
    audit = {"channel": "whatsapp", "user_id": user_id, "verified": True}
    if row is None:
        values = {
            "user_id": user_id,
            "channel": "whatsapp",
            "external_id": wa_id(user.phone),
            "verified_at": dt.datetime.now(dt.UTC),
        }
        return Change(
            "whatsapp",
            label,
            "created",
            _insert(conn, "channel_identity", values),
            phone,
            after=audit,
        )
    if row[2] is None:
        conn.execute(
            "update public.channel_identity set verified_at = now() where id = %s", (row[0],)
        )
        return Change(
            "whatsapp", label, "updated", row[0], phone, before={"verified": False}, after=audit
        )
    return Change("whatsapp", label, "unchanged", row[0], phone)


def _membership(
    conn: Conn, tenant_id: UUID, user_id: UUID, user: UserSpec, loc_ids: Mapping[str, UUID]
) -> Change:
    scope = (
        None
        if user.all_locations
        else sorted({loc_ids[normalize_name(n)] for n in user.location_names}, key=str)
    )
    desired = {
        "role": user.role.value,
        "location_ids": scope,
        "all_locations": scope is None,
        "can_approve": list(user.approvals),
    }
    row = conn.execute(
        """select id, role::text, location_ids, all_locations, can_approve from public.membership
           where tenant_id = %s and user_id = %s""",
        (tenant_id, user_id),
    ).fetchone()
    found = None
    if row is not None:
        current_scope = None if row[2] is None else sorted(row[2], key=str)
        found = (
            row[0],
            {
                "role": row[1],
                "location_ids": current_scope,
                "all_locations": row[3],
                "can_approve": row[4],
            },
        )
    mid, action, before, after = _upsert(
        conn, "membership", found, desired, {"tenant_id": tenant_id, "user_id": user_id}
    )
    where = "all locations" if scope is None else ", ".join(user.location_names)
    detail = f"{user.role.value}, {where}"
    return Change("membership", user.name, action, mid, detail, before=before, after=after)


def _auth(conn: Conn, user_id: UUID, user: UserSpec, auth: AuthAdmin) -> Change | None:
    """Links the user to a Supabase Auth user found by email, or created through the API."""
    if user.email is None:
        return None
    row = conn.execute(
        "select auth_user_id from public.app_user where id = %s", (user_id,)
    ).fetchone()
    assert row is not None
    if row[0] is not None:
        return Change("auth", user.name, "unchanged", user_id)
    found = conn.execute(
        "select id from auth.users where lower(email) = lower(%s) order by created_at limit 1",
        (user.email,),
    ).fetchone()
    taken = (
        found is not None
        and conn.execute(
            "select 1 from public.app_user where auth_user_id = %s and id <> %s",
            (found[0], user_id),
        ).fetchone()
    )
    if taken:
        raise OnboardingError(
            f"{user.name}: the auth user with this email is already linked to another MermIA user"
        )
    auth_id = found[0] if found is not None else auth.create_user(user.email)
    conn.execute("update public.app_user set auth_user_id = %s where id = %s", (auth_id, user_id))
    action: Action = "updated" if found is not None else "created"
    return Change(
        "auth",
        user.name,
        action,
        user_id,
        before={"auth_user_id": None},
        after={"auth_user_id": auth_id},
    )


def _members_not_in_spec(conn: Conn, tenant_id: UUID, user_ids: Sequence[UUID]) -> list[str]:
    rows = conn.execute(
        """select u.name, m.role::text from public.membership m
           join public.app_user u on u.id = m.user_id
           where m.tenant_id = %s and not (m.user_id = any(%s)) order by u.name""",
        (tenant_id, list(user_ids)),
    ).fetchall()
    return [f"{name} ({role}) is a member but not in the spec (kept)" for name, role in rows]


# Audit -----------------------------------------------------------------------------------------


def _jsonable(value: Mapping[str, Any] | None) -> Jsonb | None:
    return None if value is None else Jsonb(json.loads(json.dumps(value, default=str)))


def _audit(conn: Conn, tenant_id: UUID, run_id: UUID, changes: Sequence[Change]) -> int:
    rows = [
        (
            tenant_id,
            f"admin.{c.entity}.{AUDIT_VERB[c.action]}",
            AUDIT_ENTITY[c.entity],
            c.entity_id,
            _jsonable(c.before),
            _jsonable(c.after),
            f"{ACTOR}:{run_id}",
        )
        for c in changes
        if c.action != "unchanged"
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """insert into public.audit_log
               (tenant_id, actor_kind, action, entity_type, entity_id, before, after, request_id)
               values (%s, 'system', %s, %s, %s, %s, %s, %s)""",
            rows,
        )
    return len(rows)
