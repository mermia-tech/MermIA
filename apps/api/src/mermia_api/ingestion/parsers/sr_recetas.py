"""Soft Restaurant "Recetas - Productos" (recipes) report, xlsx export.

PROVISIONAL layout (SR 8 manual; the pilot's real export decides, MR-5): a title block
("<restaurant> - <location>", "Recetas - Productos", a date line such as "Al dd/mm/yyyy"), a
header row Clave | Producto | Clave insumo | Insumo | Cantidad | Unidad | Rendimiento % | Costo
(found by name; Producto, Insumo, Cantidad and Unidad are required), one row per recipe line.

Output: one catalog batch, one RecipeIn per product (in order of first appearance) with
yield_qty 1, a portion. The MR-25 costing engine does no unit conversion, so quantities leave
here in base units: kg -> g and l -> ml; g, ml and pza pass through. An unknown unit is kept as
written with an error-level issue, which sends the batch to needs_review. Rendimiento % becomes
the line's yield override. Costo is read past: the contract has no field for it, and costs come
from purchase prices. A catalog has no period, so the date line gives a one-day period.
"Recetas - Insumos elaborados" (sub-recipes such as salsa verde) is another report, not read yet.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import MalformedReport
from mermia_api.ingestion.parsers._sr_common import (
    DATE,
    SEARCH_ROWS,
    Line,
    columns,
    has_title,
    location_hint,
    read_table,
    sr_date,
)
from mermia_api.ingestion.xlsx import Row, norm, number, rows, text
from mermia_contracts.batch import (
    Grain,
    IssueIn,
    NormalizedBatch,
    Period,
    RecipeIn,
    RecipeLineIn,
    Totals,
)
from mermia_contracts.db.models import IssueSeverity, SourceKind

PARSER = "sr.recetas@v1"
# hyphen, en dash or em dash between the words, or the bare name
TITLES = ("recetas - productos", "recetas \u2013 productos", "recetas \u2014 productos", "recetas")
MAX_ROWS = 50_000  # far above a real recipe book; a small zip cannot unpack into a huge sheet

CODE = "clave"
PRODUCT = "producto"
INGREDIENT_CODE = "clave insumo"
INGREDIENT = "insumo"
QTY = "cantidad"
UNIT = "unidad"
YIELD = "rendimiento %"
COST = "costo"  # read past: the contract has no field for it
REQUIRED = {PRODUCT, INGREDIENT, QTY, UNIT}
KNOWN = {CODE, PRODUCT, INGREDIENT_CODE, INGREDIENT, QTY, UNIT, YIELD, COST}

# unit as SR may print it -> (base unit, base units per unit)
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
}

QTY_PLACES = Decimal("0.000001")  # the contract's Quantity: 6 decimals, 12 integer digits
MAX_QTY = Decimal(10) ** 12
YIELD_PLACES = Decimal("0.0001")  # the contract's PercentPoints: 4 decimals, up to 999.9999
MAX_YIELD = Decimal("999.9999")
# A yield this low is a fraction (0.92 for 92 %) read as percent points: it would cost the
# line about a hundred times too much, so a person checks it.
MAX_FRACTION_YIELD = Decimal(1)


def _header_at(sheet_rows: list[Row]) -> int | None:
    for i, row in enumerate(sheet_rows[:SEARCH_ROWS]):
        if {norm(c) for c in row} >= REQUIRED:
            return i
    return None


def _sheet_name(wb: Workbook) -> str | None:
    """The sheet with the title and header in its first rows (only those rows are read)."""
    for name in wb.sheetnames:
        top = rows(wb, name, max_row=SEARCH_ROWS)
        h = _header_at(top)
        if h is not None and has_title(top, h, *TITLES):
            return name
    return None


def matches(wb: Workbook) -> bool:
    return _sheet_name(wb) is not None


def _as_of(title: list[Row]) -> Period:
    """The report's date as a one-day period: the first date in the title block (the last one of
    its line, so "Del 01/10/2026 al 12/10/2026" is the 12th)."""
    for row in title:
        for cell in row:
            if isinstance(cell, dt.datetime):  # an Excel date cell
                day = cell.date()
            elif isinstance(cell, dt.date):
                day = cell
            else:
                found = re.findall(DATE, text(cell) or "")
                if not found:
                    continue
                day = sr_date("/".join(found[-1]))
            return Period.model_validate({"from": day, "to": day})
    raise MalformedReport(
        "No encontré la fecha del reporte de recetas (la línea «Al dd/mm/aaaa»).",
        "no date in the title block",
    )


def _qty(value: Any, where: str) -> Decimal:
    qty = number(value, where)
    if qty <= 0:
        raise MalformedReport(
            f"La cantidad {value} en {where} debe ser mayor que cero.",
            f"quantity <= 0 at {where}",
        )
    return qty


def _base_qty(qty: Decimal, factor: Decimal, where: str) -> Decimal:
    base = qty * factor
    if base != base.quantize(QTY_PLACES) or base >= MAX_QTY:
        raise MalformedReport(
            f"La cantidad en {where} tiene demasiados decimales o es demasiado grande.",
            f"quantity {base} out of the contract's range at {where}",
        )
    return base.quantize(QTY_PLACES)


def _yield(value: Any, where: str) -> Decimal:
    pct = number(value, where)
    if not 0 < pct <= MAX_YIELD or pct != pct.quantize(YIELD_PLACES):
        raise MalformedReport(
            f"El rendimiento {value} en {where} debe ser un porcentaje mayor que cero, con "
            "máximo cuatro decimales.",
            f"yield out of range at {where}: {value!r}",
        )
    return pct.quantize(YIELD_PLACES)


def _error(code: str, message_es: str, n: int) -> IssueIn:
    return IssueIn(severity=IssueSeverity.error, code=code, message_es=message_es, row_ref=str(n))


def _required_text(line: Line, name: str, what: str) -> str:
    value = text(line.raw(name))
    if value is None:
        raise MalformedReport(f"Falta {what} en la fila {line.n}.", f"no {name} at row {line.n}")
    return value


@dataclass(frozen=True)
class _Row:
    """One recipe line read from the sheet, with the issues it raised."""

    product_code: str | None
    product: str
    line: RecipeLineIn
    issues: tuple[IssueIn, ...]


def _read(line: Line) -> _Row:
    product = _required_text(line, PRODUCT, "el producto")
    ingredient = _required_text(line, INGREDIENT, "el insumo")
    qty = line.read(QTY, _qty)
    if qty is None:
        raise MalformedReport(
            f"Falta la cantidad en la fila {line.n}.", f"no quantity at row {line.n}"
        )
    unit = _required_text(line, UNIT, "la unidad")
    issues: list[IssueIn] = []
    known = UNITS.get(norm(unit).rstrip("."))
    if known is None:
        issues.append(
            _error(
                "sr.unknown_unit",
                f"En la fila {line.n}, no conozco la unidad «{unit}» de {ingredient}. Revisa la "
                "cantidad en gramos, mililitros o piezas antes de usar la receta.",
                line.n,
            )
        )
        base_unit, base = unit, _base_qty(qty, Decimal(1), line.where(QTY))
    else:
        base_unit, base = known[0], _base_qty(qty, known[1], line.where(QTY))
    pct = line.read(YIELD, _yield)
    if pct is not None and pct <= MAX_FRACTION_YIELD:
        issues.append(
            _error(
                "sr.yield_implausible",
                f"En la fila {line.n}, el rendimiento de {ingredient} es {pct.normalize()} %; "
                "parece una fracción (0.92 en lugar de 92). Revísalo antes de usar la receta.",
                line.n,
            )
        )
    return _Row(
        product_code=text(line.raw(CODE)),
        product=product,
        line=RecipeLineIn(
            ingredient_name=ingredient,
            ingredient_external_id=text(line.raw(INGREDIENT_CODE)),
            qty_base=base,
            unit=base_unit,
            yield_override_pct=pct,
        ),
        issues=tuple(issues),
    )


def _is_footer(line: Line) -> bool:
    """A row with no ingredient, quantity or unit: a text footer ("Impreso el ...") or a product
    with no recipe, neither of which is a recipe line."""
    return all(text(line.raw(c)) is None for c in (INGREDIENT, QTY, UNIT))


def parse(wb: Workbook) -> NormalizedBatch:
    sheet_name = _sheet_name(wb)
    if sheet_name is None:  # the registry calls parse only after matches
        raise MalformedReport("El reporte no tiene el formato esperado.", "header not found")
    h = _header_at(rows(wb, sheet_name, max_row=SEARCH_ROWS))
    assert h is not None
    sheet_rows = read_table(wb, sheet_name, h, MAX_ROWS)
    title = sheet_rows[:h]
    as_of = _as_of(title)
    cols = columns(sheet_rows[h], KNOWN)

    products: dict[str, tuple[str | None, str]] = {}  # product key -> (code, name)
    lines: dict[str, list[RecipeLineIn]] = {}
    seen: dict[tuple[str, str], int] = {}  # (product, ingredient) -> first row
    issues: list[IssueIn] = []
    for n, cells in enumerate(sheet_rows[h + 1 :], start=h + 2):
        line = Line(cells, n, cols)
        if _is_footer(line):
            continue
        row = _read(line)
        key = row.product_code or row.product
        _, name = products.setdefault(key, (row.product_code, row.product))
        if name != row.product:
            raise MalformedReport(
                f"La clave {key} aparece como «{name}» y como «{row.product}» (fila {n}). "
                "Envíame el reporte con un nombre por producto.",
                f"product {key!r} has two names, second at row {n}",
            )
        pair = (key, row.line.ingredient_external_id or row.line.ingredient_name)
        if pair in seen:
            raise MalformedReport(
                f"Las filas {seen[pair]} y {n} repiten el insumo «{row.line.ingredient_name}» "
                f"en la receta de «{name}». Envíame el reporte con una fila por insumo.",
                f"ingredient {pair[1]!r} repeated in {key!r} at rows {seen[pair]} and {n}",
            )
        seen[pair] = n
        lines.setdefault(key, []).append(row.line)
        issues.extend(row.issues)
    if not products:
        raise MalformedReport(
            "El reporte no tiene ninguna receta; revisa que exportaste «Recetas - Productos».",
            "no recipe rows",
        )

    recipes = [
        RecipeIn(
            menu_item_external_id=code,
            menu_item_name=name,
            yield_qty=Decimal(1).quantize(QTY_PLACES),
            lines=lines[key],
        )
        for key, (code, name) in products.items()
    ]
    return NormalizedBatch(
        parser=PARSER,
        source_kind=SourceKind.sr_report,
        location_hint=location_hint(title),
        period=as_of,
        grain=Grain.catalog,
        totals=Totals(lines=len(recipes)),
        recipes=recipes,
        issues=issues,
    )
