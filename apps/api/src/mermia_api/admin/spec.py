"""The onboarding spec: one restaurant tenant, its locations and its users (MR-30).

A spec is declarative: running it again brings the database to what it says and creates
nothing twice (see onboard.py for the natural keys). Pydantic validates everything here, before
the database is touched. YAML is read with safe_load (a duplicate key is refused), so a JSON
file works too. Phones are made canonical (mermia_api.phone: +52 1 ... becomes +52 ...).

Role defaults (09 section 5.1 and the El Güero seed): owner, admin and support see every
location; a manager must list theirs. `can_approve` defaults per role and may be overridden
with the C5 kinds (PendingKind), except for support, which never approves (09 section 2.1).
Only the owner approves `recipe.upsert` by default (MR-25), so the admin default leaves it out.
"""

from __future__ import annotations

import re
from collections.abc import Hashable
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import available_timezones

import yaml
from pydantic import Field, field_validator, model_validator

from mermia_api.phone import canonical_phone
from mermia_contracts.batch import Model, Text
from mermia_contracts.db.models import MemberRole
from mermia_contracts.keys import normalize_name
from mermia_contracts.pending import PendingKind

EXAMPLE = Path(__file__).with_name("example.yaml")
DEFAULT_TIMEZONE = "America/Mexico_City"
# Canonical IANA regions a location time zone may start with. The DB helper
# app.is_valid_timezone (supabase/migrations/20261107120000_location_timezone_check.sql) mirrors
# this list: change both together.
TIMEZONE_REGIONS = (
    "Africa/", "America/", "Antarctica/", "Asia/", "Atlantic/",
    "Australia/", "Europe/", "Indian/", "Pacific/",
)  # fmt: skip

# ISO weekdays (1 = Monday ... 7 = Sunday), keyed by the normalized Spanish name.
WEEKDAYS = {
    "lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4,
    "viernes": 5, "sabado": 6, "domingo": 7,
}  # fmt: skip
WEEKDAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Persona moral (3 letters) or física (4), yymmdd, 3-character homoclave.
RFC = re.compile(r"^[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3}$")

ROLE_APPROVALS: dict[MemberRole, tuple[PendingKind, ...]] = {
    MemberRole.owner: tuple(PendingKind),
    MemberRole.manager: (PendingKind.import_batch_approve, PendingKind.import_batch_rollback),
    MemberRole.admin: (PendingKind.ingredient_price_set, PendingKind.menu_item_price_set),
    MemberRole.support: (),
}

MASK_KEEP_START = 3  # "+52"
MASK_KEEP_END = 4


def mask_phone(phone: str) -> str:
    """'+525512345001' -> '+52******5001': the only form of a phone number the script prints."""
    hidden = max(len(phone) - MASK_KEEP_START - MASK_KEEP_END, 0)
    return phone[:MASK_KEEP_START] + "*" * hidden + phone[len(phone) - MASK_KEEP_END :]


NONE_ANSWER = "ninguno"


class TenantSpec(Model):
    id: UUID | None = None  # required to touch an existing tenant (reruns); its name may change
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


@cache
def _known_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


class LocationSpec(Model):
    id: UUID | None = None  # pins the location, so a rerun can rename it
    name: Text
    timezone: str | None = None  # None: keep the stored one; DEFAULT_TIMEZONE on insert
    address: Text | None = None
    sr_version: Text | None = None
    sr_edition: Text | None = None
    # Weekdays the location normally closes, in Spanish. None: keep the stored ones (a new
    # location needs an answer); []: opens every day.
    closed_days: list[str] | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("closed_days", mode="before")
    @classmethod
    def _closed_days(cls, value: Any) -> Any:
        if value is None:
            return None
        valid = ", ".join(WEEKDAY_NAMES)
        if isinstance(value, str) and normalize_name(value) == NONE_ANSWER:
            return []  # the founders' question tells the owner to answer "ninguno"
        if not isinstance(value, list):
            raise ValueError(
                f"closed_days debe ser una lista de días ({valid}); [] o ninguno si abre todos"
            )
        is_none = [isinstance(d, str) and normalize_name(d) == NONE_ANSWER for d in value]
        if any(is_none):
            if len(value) > 1:
                raise ValueError(
                    "closed_days: «ninguno» va solo; usa solo «ninguno» o la lista de días"
                )
            return []
        numbers: list[int] = []
        for day in value:
            number = WEEKDAYS.get(normalize_name(day)) if isinstance(day, str) else None
            if number is None:
                raise ValueError(
                    f"día desconocido {day!r} en closed_days; usa: {valid}; "
                    "[] o ninguno si abre todos los días"
                )
            if number in numbers:
                raise ValueError(f"día repetido en closed_days: {WEEKDAY_NAMES[number - 1]}")
            numbers.append(number)
        if len(numbers) == len(WEEKDAYS):
            raise ValueError("closed_days no puede incluir los siete días: la sucursal no abriría")
        return value

    @property
    def closed_weekdays(self) -> list[int] | None:
        """The ISO weekday numbers, ascending; None when the spec does not say."""
        if self.closed_days is None:
            return None
        return sorted(WEEKDAYS[normalize_name(d)] for d in self.closed_days)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Same rule as the DB helper app.is_valid_timezone: exact-case name plus a canonical region.
        # (ZoneInfo alone accepts wrong case on macOS and names like CST6CDT.)
        if not value.startswith(TIMEZONE_REGIONS) or value not in _known_timezones():
            raise ValueError(f"unknown time zone {value!r}")
        return value


class UserSpec(Model):
    name: Text
    phone: str
    email: str | None = None
    role: MemberRole
    locations: Literal["all"] | Annotated[list[Text], Field(min_length=1)] | None = None
    can_approve: tuple[PendingKind, ...] | None = None
    # The phone belongs to a person who is already a member of another tenant: add them here too.
    existing_user: bool = False

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return canonical_phone(value)

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
        if _twice(names):
            raise ValueError(f"location listed twice: {', '.join(sorted(_twice(names)))}")
        pins = [str(loc.id) for loc in self.locations if loc.id is not None]
        if len(set(pins)) < len(pins):
            raise ValueError(f"location id listed twice: {', '.join(sorted(_twice(pins)))}")
        phones = [u.phone for u in self.users]
        if _twice(phones):
            raise ValueError(
                f"phone listed twice: {', '.join(sorted(map(mask_phone, _twice(phones))))}"
            )
        emails = [u.email for u in self.users if u.email is not None]
        if _twice(emails):
            raise ValueError(f"email listed twice: {', '.join(sorted(_twice(emails)))}")
        if not any(u.role == MemberRole.owner for u in self.users):
            raise ValueError("the spec needs at least one owner")
        for user in self.users:
            unknown = [n for n in user.location_names if normalize_name(n) not in names]
            if unknown:
                raise ValueError(f"{user.name}: unknown location {', '.join(unknown)}")
        return self


def _twice(values: list[str]) -> set[str]:
    return {v for v in values if values.count(v) > 1}


class DuplicateKeyError(yaml.YAMLError):
    def __init__(self, key: object, line: int) -> None:
        super().__init__(f"duplicate key {key!r} (line {line})")


class _UniqueKeyLoader(yaml.SafeLoader):
    """safe_load keeps the last of two equal keys silently (two `role:` lines); this refuses."""


def _mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Hashable] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if isinstance(key, Hashable) and key in seen:
            raise DuplicateKeyError(key, key_node.start_mark.line + 1)
        if isinstance(key, Hashable):
            seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_spec(path: Path) -> OnboardingSpec:
    """Reads a YAML (or JSON) spec file. Raises ValueError (ValidationError is one) if invalid."""
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # a SafeLoader
    except DuplicateKeyError as e:
        raise ValueError(f"{path.name}: {e}") from None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise ValueError(f"{path.name} is not valid YAML{where}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: the spec must be a mapping with tenant, locations, users")
    return OnboardingSpec.model_validate(data)
