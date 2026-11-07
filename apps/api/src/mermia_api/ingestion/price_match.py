"""Matching CFDI invoice lines to the tenant's ingredients, in base units (MR-36).

- Supplier: by RFC within the tenant; when that finds none, by its cleaned name (decision 10), but
  only a supplier with no RFC on file: one with another RFC is someone else, so the invoice's
  issuer stays unknown and never borrows a trusted supplier's name or aliases. A supplier is
  never created. An unknown supplier has no aliases, so its lines match by name.
- An issuer whose RFC has 4 letters is a person: an unknown one is shown by first word and
  initial (invoice_supplier_name), never by full name, since the diff may reach the LLM.
- Line: the supplier's alias whose source text normalizes to the line's description; else, when
  name matches are on (decision 2), the one ingredient with that normalized name. Two candidate
  ingredients hold the line; none leaves it unmatched.
- Units: cfdi_units.base_per_unit with the alias's pack and the ingredient's conversions.
- The supplier's RFC is used only to look it up: it is never returned or put in a message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg

from mermia_api.ingestion.cfdi_units import Conversions, Pack, normalized_conversions
from mermia_contracts.batch import SupplierIn
from mermia_contracts.keys import normalize_name

MATCH_SUPPLIER_BY_NAME = True  # decision 10: an RFC we don't know is looked up by name
PROPOSE_NAME_MATCHES = True  # decision 2: a name match without an alias is proposed, "(por nombre)"
BY_ALIAS = "alias"
BY_NAME = "name"
SUPPLIER_BY_RFC = "rfc"  # diff.supplier_matched_by
SUPPLIER_BY_NAME = "name"
SUPPLIER_UNKNOWN = "none"
PERSON_RFC = re.compile(r"[A-ZÑ&]{4}\d")  # a persona física's RFC starts with 4 letters
PERSON_LABEL = "proveedor persona física"  # a person whose name has a single word


@dataclass(frozen=True)
class Supplier:
    id: UUID
    name: str
    matched_by: str  # SUPPLIER_BY_RFC or SUPPLIER_BY_NAME


@dataclass(frozen=True)
class Ingredient:
    id: UUID
    name: str
    base_unit: str


@dataclass(frozen=True)
class Match:
    ingredient: Ingredient
    how: str  # BY_ALIAS or BY_NAME
    pack: Pack | None = None


class Ambiguous(Exception):
    """More than one ingredient fits the line."""


@dataclass(frozen=True)
class Catalog:
    """The tenant's ingredients, the supplier's aliases and the unit conversions, read once."""

    by_name: dict[str, list[Ingredient]]
    by_id: dict[UUID, Ingredient]
    aliases: dict[str, list[tuple[UUID, Pack | None]]]  # normalized source text -> candidates
    tenant_conversions: list[tuple[str, str, Decimal]]
    own_conversions: dict[UUID, list[tuple[str, str, Decimal]]] = field(default_factory=dict)

    def conversions(self, ingredient_id: UUID) -> Conversions:
        """The tenant's conversions, the ingredient's own winning."""
        return normalized_conversions(
            self.tenant_conversions + self.own_conversions.get(ingredient_id, [])
        )

    def match(self, description: str) -> Match | None:
        """The ingredient a line means (None: no match). Raises Ambiguous."""
        key = normalize_name(description)
        if not key:
            return None
        candidates = self.aliases.get(key, [])
        if len({ingredient_id for ingredient_id, _ in candidates}) > 1:
            raise Ambiguous(description)
        if candidates:
            ingredient_id, pack = candidates[0]
            return Match(self.by_id[ingredient_id], BY_ALIAS, pack)
        if not PROPOSE_NAME_MATCHES:
            return None
        found = self.by_name.get(key, [])
        if len(found) > 1:
            raise Ambiguous(description)
        return Match(found[0], BY_NAME) if found else None


def is_person(rfc: str | None) -> bool:
    """A 4-letter RFC: the issuer is a person (persona física), not a company."""
    return rfc is not None and PERSON_RFC.match(rfc.strip().upper()) is not None


def invoice_supplier_name(supplier: SupplierIn) -> str:
    """The name to show for an issuer that is not among the tenant's suppliers: a company's as
    invoiced; a person's as first word and the next word's initial ("José P.")."""
    if not is_person(supplier.rfc):
        return supplier.name
    words = supplier.name.split()
    return f"{words[0].title()} {words[1][0].upper()}." if len(words) > 1 else PERSON_LABEL


def find_supplier(
    conn: psycopg.Connection[Any], tenant_id: UUID, supplier: SupplierIn
) -> Supplier | None:
    if supplier.rfc is not None:
        rows = conn.execute(
            """select id, name from public.supplier
               where tenant_id = %s and upper(btrim(rfc)) = upper(btrim(%s)) limit 2""",
            (tenant_id, supplier.rfc),
        ).fetchall()
        if len(rows) == 1:
            return Supplier(rows[0][0], rows[0][1], SUPPLIER_BY_RFC)
    if not MATCH_SUPPLIER_BY_NAME:
        return None
    key = normalize_name(supplier.name)
    named = [
        row
        for row in conn.execute(
            "select id, name, rfc from public.supplier where tenant_id = %s order by id",
            (tenant_id,),
        ).fetchall()
        if normalize_name(row[1]) == key
    ]
    if len(named) != 1 or (named[0][2] or "").strip():
        return None  # none, several, or one with an RFC that is not the invoice's
    return Supplier(named[0][0], named[0][1], SUPPLIER_BY_NAME)


def load_catalog(
    conn: psycopg.Connection[Any], tenant_id: UUID, supplier_id: UUID | None
) -> Catalog:
    ingredients = [
        Ingredient(row[0], row[1], row[2])
        for row in conn.execute(
            """select id, name, base_unit::text from public.ingredient
               where tenant_id = %s order by name, id""",
            (tenant_id,),
        ).fetchall()
    ]
    by_id = {x.id: x for x in ingredients}
    by_name: dict[str, list[Ingredient]] = {}
    for ingredient in ingredients:
        by_name.setdefault(normalize_name(ingredient.name), []).append(ingredient)
    aliases: dict[str, list[tuple[UUID, Pack | None]]] = {}
    if supplier_id is not None:
        for text, ingredient_id, pack_qty, pack_unit in conn.execute(
            """select source_text, ingredient_id, pack_qty, pack_unit from public.ingredient_alias
               where tenant_id = %s and supplier_id = %s order by source_text, id""",
            (tenant_id, supplier_id),
        ).fetchall():
            if ingredient_id not in by_id:
                continue
            pack = Pack(pack_qty, pack_unit) if pack_qty is not None and pack_unit else None
            aliases.setdefault(normalize_name(text), []).append((ingredient_id, pack))
    tenant_wide: list[tuple[str, str, Decimal]] = []
    own: dict[UUID, list[tuple[str, str, Decimal]]] = {}
    for ingredient_id, from_unit, to_unit, factor in conn.execute(
        """select ingredient_id, from_unit, to_unit, factor from public.unit_conversion
           where tenant_id = %s order by created_at, id""",
        (tenant_id,),
    ).fetchall():
        row = (from_unit, to_unit, factor)
        if ingredient_id is None:
            tenant_wide.append(row)
        else:
            own.setdefault(ingredient_id, []).append(row)
    return Catalog(by_name, by_id, aliases, tenant_wide, own)
