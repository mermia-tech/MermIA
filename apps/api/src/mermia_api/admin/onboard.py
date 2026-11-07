"""Brings one tenant to what its onboarding spec says (MR-30), inside the caller's transaction.

Runs on the postgres connection (the admin URL): the identity tables are class X, so no client
role can write them, and the script is the concierge path that does. Natural keys, so a rerun
creates nothing twice:
- tenant: only its pinned id. Without an id the tenant is created, and a tenant with the same
  normalized name is refused: a name match must never hand an existing restaurant to a new
  owner. The CLI prints the id to pin after the first real run;
- location: its pinned id (must be in the tenant), or its normalized name in the tenant. Two
  spec entries that resolve to the same row are refused;
- app_user: phone_e164 (unique, canonical). An existing phone under another name is refused
  (most likely a typo). A user who is a member of another tenant joins only with
  `existing_user: true`, and their name and email are never changed (they are shared);
- membership: (tenant_id, user_id) (unique); channel_identity: (whatsapp, wa_id) (unique);
- source: one sr_report and one manual source per location (MR-25 decision 4), if missing.

Nothing is deleted: locations and members in the database but not in the spec are kept, and
the notes warn that those members keep their access. Every created or updated row gets an
audit_log row (actor_kind system, request_id `mermia_api.admin:<operator>:<run id>`), with no
phone number, wa_id or email in before/after (an email change is logged as email_changed). The
WhatsApp identity is created verified: the operator confirmed the number during onboarding.
Consent (consent_log) is not recorded here; the user gives it on WhatsApp (MR-29).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from mermia_api.admin.spec import (
    DEFAULT_TIMEZONE,
    WEEKDAY_NAMES,
    LocationSpec,
    OnboardingSpec,
    TenantSpec,
    UserSpec,
    mask_phone,
)
from mermia_api.phone import wa_id
from mermia_contracts.keys import normalize_name

ACTOR = "mermia_api.admin"
SOURCE_KINDS = ("sr_report", "manual")
LOCK_KEY = "mermia_api.admin"
OPERATOR = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")

Action = Literal["created", "updated", "unchanged"]
Conn = psycopg.Connection[Any]

AUDIT_ENTITY = {
    "tenant": "tenant",
    "location": "location",
    "source": "source",
    "user": "app_user",
    "whatsapp": "channel_identity",
    "membership": "membership",
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


def check_operator(value: str) -> str:
    """The operator's handle for the audit trail: lower case, 2-40 of a-z 0-9 . _ -."""
    if not OPERATOR.match(value):
        raise ValueError("operator must be a short handle like 'guillermo' (a-z, 0-9, . _ -)")
    return value


def onboard(conn: Conn, spec: OnboardingSpec, *, operator: str) -> Summary:
    """Applies the spec in the caller's transaction; the caller commits or rolls back."""
    check_operator(operator)
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
    notes += _members_not_in_spec(conn, tenant.entity_id, user_ids)
    audited = _audit(conn, tenant.entity_id, f"{ACTOR}:{operator}:{run_id}", changes)
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


def _closed_detail(days: Sequence[int]) -> str:
    if not days:
        return "abre todos los días"
    return "cierra: " + ", ".join(WEEKDAY_NAMES[d - 1] for d in days)


# Tenant and locations --------------------------------------------------------------------------


def _tenant(conn: Conn, spec: TenantSpec) -> Change:
    rows = conn.execute("select id, name, rfc from public.tenant").fetchall()
    if spec.id is not None:
        matches = [r for r in rows if r[0] == spec.id]
        if not matches:
            raise OnboardingError(f"no tenant with id {spec.id}")
    else:
        same_name = [str(r[0]) for r in rows if normalize_name(r[1]) == normalize_name(spec.name)]
        if same_name:
            raise OnboardingError(
                f"a tenant named like {spec.name!r} already exists ({', '.join(same_name)});"
                " to update it, put its id in tenant.id; for a new restaurant, change the name"
            )
        matches = []
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
    cols = ("name", "timezone", "address", "sr_version", "sr_edition", "closed_weekdays")
    rows = {
        r[0]: dict(zip(cols, r[1:], strict=True))
        for r in conn.execute(
            "select id, name, timezone, address, sr_version, sr_edition, closed_weekdays"
            " from public.location"
            " where tenant_id = %s",
            (tenant_id,),
        )
    }
    ids: dict[str, UUID] = {}
    for loc in specs:
        found_id = _find_location(rows, loc)
        if found_id is not None and found_id in ids.values():
            raise OnboardingError(
                f"{loc.name!r} and another spec location resolve to the same location"
                f" ({rows[found_id]['name']!r}); rename in one run, add the new one in the next"
            )
        if found_id is None and loc.closed_weekdays is None:
            raise OnboardingError(
                f"{loc.name}: di qué días cierra (closed_days: [] si abre todos los días)"
            )
        timezone = loc.timezone or (None if found_id else DEFAULT_TIMEZONE)
        desired = {
            "name": loc.name,
            **_given(
                timezone=timezone,
                address=loc.address,
                sr_version=loc.sr_version,
                sr_edition=loc.sr_edition,
                closed_weekdays=loc.closed_weekdays,  # a list: [] is a value, and == the stored one
            ),
        }
        found = (found_id, rows[found_id]) if found_id else None
        lid, action, before, after = _upsert(
            conn, "location", found, desired, {"tenant_id": tenant_id}
        )
        ids[normalize_name(loc.name)] = lid
        detail = _closed_detail(after["closed_weekdays"]) if "closed_weekdays" in after else ""
        changes.append(
            Change("location", loc.name, action, lid, detail, before=before, after=after)
        )
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
    if row is None:
        if user.existing_user:
            raise OnboardingError(f"{label}: existing_user is set but no user has {phone}")
        new_id = _insert(conn, "app_user", {"phone_e164": user.phone, **desired})
        changes.append(Change("user", label, "created", new_id, phone, after=_redact(desired)))
        return new_id
    uid: UUID = row[0]
    name, email = row[1], row[2]
    if normalize_name(name) != normalize_name(user.name):
        raise OnboardingError(
            f"{phone} already belongs to {name!r}; check the number (spec says {user.name!r})"
        )
    others, member_here = _tenants_of(conn, uid, tenant_id)
    if others:
        if not (user.existing_user or member_here):
            raise OnboardingError(
                f"{phone} is {name!r}, a member of {others} other tenant(s); if it is the same"
                " person, set existing_user: true for them"
            )
        notes.append(f"{label} is also a member of {others} other tenant(s)")
        if desired != {"name": name, **_given(email=email)}:
            notes.append(f"{label}: name and email not changed (shared with another tenant)")
        changes.append(Change("user", label, "unchanged", uid, phone))
        return uid
    before, after = _sync(conn, "app_user", uid, {"name": name, "email": email}, desired)
    action: Action = "updated" if after else "unchanged"
    changes.append(
        Change(
            "user",
            label,
            action,
            uid,
            phone,
            before=_redact(before, mark=False),
            after=_redact(after),
        )
    )
    return uid


def _redact(values: Mapping[str, Any], *, mark: bool = True) -> dict[str, Any]:
    """Audit form of app_user values: the email itself never goes to the tenant's audit_log."""
    out = {k: v for k, v in values.items() if k != "email"}
    return {**out, "email_changed": True} if mark and "email" in values else out


def _tenants_of(conn: Conn, user_id: UUID, tenant_id: UUID) -> tuple[int, bool]:
    """(how many other tenants the user is a member of, whether they are a member of this one)."""
    row = conn.execute(
        """select count(*) filter (where tenant_id <> %s), bool_or(tenant_id = %s)
           from public.membership where user_id = %s""",
        (tenant_id, tenant_id, user_id),
    ).fetchone()
    assert row is not None
    return int(row[0]), bool(row[1])


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


def _members_not_in_spec(conn: Conn, tenant_id: UUID, user_ids: Sequence[UUID]) -> list[str]:
    rows = conn.execute(
        """select u.name, m.role::text from public.membership m
           join public.app_user u on u.id = m.user_id
           where m.tenant_id = %s and not (m.user_id = any(%s)) order by u.name""",
        (tenant_id, list(user_ids)),
    ).fetchall()
    return [
        f"WARNING: {name} ({role}) is not in the spec but keeps their access (membership and"
        " WhatsApp); a changed phone leaves the old number with access too. Remove by hand."
        for name, role in rows
    ]


# Audit -----------------------------------------------------------------------------------------


def _jsonable(value: Mapping[str, Any] | None) -> Jsonb | None:
    return None if value is None else Jsonb(json.loads(json.dumps(value, default=str)))


def _audit(conn: Conn, tenant_id: UUID, request_id: str, changes: Sequence[Change]) -> int:
    rows = [
        (
            tenant_id,
            f"admin.{c.entity}.{AUDIT_VERB[c.action]}",
            AUDIT_ENTITY[c.entity],
            c.entity_id,
            _jsonable(c.before),
            _jsonable(c.after),
            request_id,
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
