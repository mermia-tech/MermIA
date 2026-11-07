"""Units, quantities and yields as recipe files print them: shared by the SR Recetas parser and
the MermIA recipe template.

The MR-25 costing engine does no unit conversion, so quantities leave the parsers in base units:
kg -> g and l -> ml; g, ml and pza pass through (abbreviated or spelled out, "kilos", "piezas").
Quantities and yields finer than the contract are rounded half-up.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from mermia_api.ingestion.errors import MalformedReport
from mermia_api.ingestion.xlsx import norm, number

# unit as a file may print it -> (base unit, base units per unit)
_GRAMS = ("g", Decimal(1))
_KILOS = ("g", Decimal(1000))
_ML = ("ml", Decimal(1))
_LITRES = ("ml", Decimal(1000))
_PIECES = ("pza", Decimal(1))
UNITS = {
    "kg": _KILOS,
    "kgs": _KILOS,
    "g": _GRAMS,
    "gr": _GRAMS,
    "grs": _GRAMS,
    "l": _LITRES,
    "lt": _LITRES,
    "lts": _LITRES,
    "ml": _ML,
    "pza": _PIECES,
    "pzas": _PIECES,
    "pz": _PIECES,
    "kilo": _KILOS,
    "kilos": _KILOS,
    "kilogramo": _KILOS,
    "kilogramos": _KILOS,
    "gramo": _GRAMS,
    "gramos": _GRAMS,
    "litro": _LITRES,
    "litros": _LITRES,
    "mililitro": _ML,
    "mililitros": _ML,
    "pieza": _PIECES,
    "piezas": _PIECES,
}

QTY_PLACES = Decimal("0.000001")  # the contract's Quantity: 6 decimals, 12 integer digits
MAX_QTY = Decimal(10) ** 12
YIELD_PLACES = Decimal("0.0001")  # the contract's PercentPoints: 4 decimals, up to 999.9999
MAX_YIELD = Decimal("999.9999")
# Per portion, a base quantity this large is a slip (a decimal comma read as thousands,
# "1,500" kg): 1000 kg or l (in g or ml), or 1000 pieces, goes to a person.
IMPLAUSIBLE_QTY = {"g": Decimal(10) ** 6, "ml": Decimal(10) ** 6, "pza": Decimal(1000)}
# A yield this low is a fraction (0.92 for 92 %) read as percent points: it would cost the
# line about a hundred times too much, so a person checks it.
MAX_FRACTION_YIELD = Decimal(1)


def unit_of(unit: str) -> tuple[str, Decimal] | None:
    """(base unit, base units per unit) of a unit as printed ("KG", "Kilos", "pza."), or None."""
    return UNITS.get(norm(unit).rstrip("."))


def base_qty(qty: Decimal, factor: Decimal, where: str) -> Decimal:
    """The quantity in base units, rounded half-up to the contract's six decimals (1/3 kg)."""
    base = (qty * factor).quantize(QTY_PLACES, rounding=ROUND_HALF_UP)
    if base <= 0:
        raise MalformedReport(
            f"La cantidad en {where} es demasiado pequeña (menos de una millonésima de gramo, "
            "mililitro o pieza).",
            f"quantity {qty * factor} rounds to zero at {where}",
        )
    if base >= MAX_QTY:
        raise MalformedReport(
            f"La cantidad en {where} es demasiado grande.",
            f"quantity {base} out of the contract's range at {where}",
        )
    return base


def yield_pct(value: Any, where: str) -> Decimal:
    """Percent points rounded half-up to the contract's four decimals (100/1.08 is 92.5926)."""
    pct = number(value, where).quantize(YIELD_PLACES, rounding=ROUND_HALF_UP)
    if not 0 < pct <= MAX_YIELD:
        raise MalformedReport(
            f"El rendimiento {value} en {where} debe ser un porcentaje mayor que cero y hasta "
            f"{MAX_YIELD.normalize()}.",
            f"yield out of range at {where}: {value!r}",
        )
    return pct
