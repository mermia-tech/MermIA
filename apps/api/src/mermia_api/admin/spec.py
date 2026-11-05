"""The onboarding spec: one restaurant tenant, its locations and its users (MR-30).

A spec is declarative: running it again brings the database to what it says and creates
nothing twice (see onboard.py for the natural keys). Pydantic validates everything here, before
the database is touched. YAML is read with safe_load, so a JSON file works too.

Role defaults (09 section 5.1 and the El Güero seed): owner, admin and support see every
location; a manager must list theirs. `can_approve` defaults per role and may be overridden
with the C5 kinds (PendingKind), except for support, which never approves (09 section 2.1).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import Field, field_validator, model_validator

from mermia_contracts.batch import Model, Text
from mermia_contracts.db.models import MemberRole
from mermia_contracts.keys import normalize_name
from mermia_contracts.pending import PendingKind

EXAMPLE = Path(__file__).with_name("example.yaml")
DEFAULT_TIMEZONE = "America/Mexico_City"

# The same check as app_user.phone_e164 in the database.
E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
PHONE_SEPARATORS = re.compile(r"[\s\-().]")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Persona moral (3 letters) or física (4), yymmdd, 3-character homoclave.
RFC = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$")

ROLE_APPROVALS: dict[MemberRole, tuple[PendingKind, ...]] = {
    MemberRole.owner: tuple(PendingKind),
    MemberRole.manager: (PendingKind.import_batch_approve, PendingKind.import_batch_rollback),
    MemberRole.admin: (
        PendingKind.ingredient_price_set,
        PendingKind.recipe_upsert,
        PendingKind.menu_item_price_set,
    ),
    MemberRole.support: (),
}

MASK_KEEP_START = 3  # "+52"
MASK_KEEP_END = 4


def mask_phone(phone: str) -> str:
    """'+525512345001' -> '+52******5001': the only form of a phone number the script prints."""
    hidden = max(len(phone) - MASK_KEEP_START - MASK_KEEP_END, 0)
    return phone[:MASK_KEEP_START] + "*" * hidden + phone[len(phone) - MASK_KEEP_END :]


def wa_id(phone: str) -> str:
    """The WhatsApp id stored in channel_identity.external_id: the E.164 digits without '+'."""
    return phone.removeprefix("+")


class TenantSpec(Model):
    id: UUID | None = None  # pins the tenant, so a rerun can rename it
    name: Text
    rfc: str | None = None

    @field_validator("rfc")
    @classmethod
    def _rfc(cls, value: str | None) -> str | None:
        if value is None:
            return None
        rfc = value.strip().upper()
        if not RFC.match(rfc):
            raise ValueError("RFC must look like ABC123456XY1 (3-4 letters, yymmdd, homoclave)")
        return rfc


class LocationSpec(Model):
    id: UUID | None = None  # pins the location, so a rerun can rename it
    name: Text
    timezone: str = DEFAULT_TIMEZONE
    address: Text | None = None
    sr_version: Text | None = None
    sr_edition: Text | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown time zone {value!r}") from None
        return value


class UserSpec(Model):
    name: Text
    phone: str
    email: str | None = None
    role: MemberRole
    locations: Literal["all"] | Annotated[list[Text], Field(min_length=1)] | None = None
    can_approve: tuple[PendingKind, ...] | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        phone = PHONE_SEPARATORS.sub("", value)
        if not E164.match(phone):
            raise ValueError("phone must be E.164 with the country code, e.g. +52 55 1234 5678")
        return phone

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        if not EMAIL.match(email):
            raise ValueError("email must look like name@domain.mx")
        return email

    @model_validator(mode="after")
    def _scope(self) -> UserSpec:
        if self.role == MemberRole.manager and self.locations is None:
            raise ValueError("a manager must list its locations (or say 'all')")
        if self.role == MemberRole.support and self.can_approve:
            raise ValueError("support never approves: leave can_approve out")
        return self

    @property
    def all_locations(self) -> bool:
        return self.locations is None or self.locations == "all"

    @property
    def location_names(self) -> tuple[str, ...]:
        return () if self.all_locations else tuple(self.locations or ())

    @property
    def approvals(self) -> tuple[str, ...]:
        kinds = self.can_approve if self.can_approve is not None else ROLE_APPROVALS[self.role]
        return tuple(k.value for k in kinds)


class OnboardingSpec(Model):
    tenant: TenantSpec
    locations: Annotated[list[LocationSpec], Field(min_length=1)]
    users: Annotated[list[UserSpec], Field(min_length=1)]

    @model_validator(mode="after")
    def _consistent(self) -> OnboardingSpec:
        names = [normalize_name(loc.name) for loc in self.locations]
        twice = {n for n in names if names.count(n) > 1}
        if twice:
            raise ValueError(f"location listed twice: {', '.join(sorted(twice))}")
        phones = [u.phone for u in self.users]
        repeated = sorted({mask_phone(p) for p in phones if phones.count(p) > 1})
        if repeated:
            raise ValueError(f"phone listed twice: {', '.join(repeated)}")
        if not any(u.role == MemberRole.owner for u in self.users):
            raise ValueError("the spec needs at least one owner")
        for user in self.users:
            unknown = [n for n in user.location_names if normalize_name(n) not in names]
            if unknown:
                raise ValueError(f"{user.name}: unknown location {', '.join(unknown)}")
        return self


def load_spec(path: Path) -> OnboardingSpec:
    """Reads a YAML (or JSON) spec file. Raises ValueError (ValidationError is one) if invalid."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise ValueError(f"{path.name} is not valid YAML{where}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: the spec must be a mapping with tenant, locations, users")
    return OnboardingSpec.model_validate(data)
