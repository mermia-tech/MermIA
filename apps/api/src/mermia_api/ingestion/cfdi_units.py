"""How many base units (g, ml, pza) one invoiced unit of a CFDI line holds (MR-36). Pure.

- The SAT's measurement units are fixed: KGM is 1000 g, GRM 1 g, LTR 1000 ml, MLT 1 ml, and H87,
  EA and XUN one piece.
- Any other ClaveUnidad (a box, a pack, a bag) is a pack: it needs the supplier alias's pack_qty
  and pack_unit (what one invoiced unit holds). Without them the line is held (decision 14).
- When the invoiced unit and the ingredient's base unit are of different kinds (kilos of a
  pieces ingredient, like eggs by the kilo), a unit_conversion row of the tenant must bridge them
  (from the invoiced kind, in its small or large unit, to the base unit); otherwise the line is
  held. A conversion of the ingredient wins over one of the whole tenant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

# a unit name -> (its kind's base unit, how many of them it is)
MEASURES: dict[str, tuple[str, Decimal]] = {
    "g": ("g", Decimal(1)),
    "kg": ("g", Decimal(1000)),
    "ml": ("ml", Decimal(1)),
    "l": ("ml", Decimal(1000)),
    "pza": ("pza", Decimal(1)),
}
SAT_UNITS: dict[str, str] = {  # the SAT's ClaveUnidad that are a measurement, to a unit name
    "KGM": "kg",
    "GRM": "g",
    "LTR": "l",
    "MLT": "ml",
    "H87": "pza",
    "EA": "pza",
    "XUN": "pza",
}
PACK_UNKNOWN = "cfdi.unit_pack_unknown"
UNIT_MISMATCH = "cfdi.unit_mismatch"

Conversions = Mapping[tuple[str, str], Decimal]  # (from_unit, to_unit) -> 1 from_unit in to_unit


@dataclass(frozen=True)
class Pack:
    """What one invoiced unit holds, from the supplier alias (pack_qty, pack_unit)."""

    qty: Decimal
    unit: str


class UnitHeld(Exception):
    """The line cannot be put in the ingredient's base unit; `code` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _unit_name(text: str) -> str | None:
    """A unit as the alias or a conversion writes it (kg, KG, KGM) -> g, kg, ml, l or pza."""
    key = text.strip()
    name = SAT_UNITS.get(key.upper(), key.lower())
    return name if name in MEASURES else None


def _invoiced(clave: str, pack: Pack | None) -> tuple[str, Decimal]:
    """One invoiced unit as (kind, amount in the kind's base unit)."""
    name = SAT_UNITS.get(clave.strip().upper())
    if name is not None:
        return MEASURES[name]
    pack_name = None if pack is None else _unit_name(pack.unit)
    if pack is None or pack_name is None or pack.qty <= 0:
        raise UnitHeld(PACK_UNKNOWN)
    kind, size = MEASURES[pack_name]
    return kind, pack.qty * size


def base_per_unit(
    clave: str, base_unit: str, pack: Pack | None, conversions: Conversions
) -> Decimal:
    """Base units of the ingredient in one invoiced unit. Raises UnitHeld."""
    kind, amount = _invoiced(clave, pack)
    if kind == base_unit:
        return amount
    for name, (name_kind, size) in MEASURES.items():
        factor = conversions.get((name, base_unit))
        if name_kind == kind and factor is not None and factor > 0:
            return amount / size * factor
    raise UnitHeld(UNIT_MISMATCH)


def normalized_conversions(rows: list[tuple[str, str, Decimal]]) -> dict[tuple[str, str], Decimal]:
    """unit_conversion rows (from_unit, to_unit, factor) keyed by unit name; rows whose units are
    not g, kg, ml, l or pza are left out. Later rows win, so pass tenant-wide rows first."""
    found: dict[tuple[str, str], Decimal] = {}
    for from_unit, to_unit, factor in rows:
        a, b = _unit_name(from_unit), _unit_name(to_unit)
        if a is not None and b is not None:
            found[(a, b)] = factor
    return found
