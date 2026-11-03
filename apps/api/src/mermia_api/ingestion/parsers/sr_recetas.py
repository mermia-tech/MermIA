"""Soft Restaurant "Recetas - Productos" (recipes) report, xlsx export.

PROVISIONAL layout (SR 8 manual; the pilot's real export decides, MR-5): a title block
("<restaurant> - <location>", "Recetas - Productos", a date line such as "Al dd/mm/yyyy"), a
header row Clave | Producto | Clave insumo | Insumo | Cantidad | Unidad | Rendimiento % | Costo
(found by name; Producto, Insumo, Cantidad and Unidad are required), one row per recipe line.

Output: one catalog batch, one RecipeIn per product (in order of first appearance) with
yield_qty 1, a portion. The MR-25 costing engine does no unit conversion, so quantities leave
here in base units: kg -> g and l -> ml; g, ml and pza pass through (abbreviated or spelled out,
"kilos", "piezas"). An unknown unit is kept as written with an error-level issue, which sends the
batch to needs_review. Quantities and yields finer than the contract are rounded half-up.
Rendimiento % (or "Rendimiento", "% Rendimiento"...) becomes the line's yield override; another
header that mentions rendimiento is a warning, since its yields would be dropped. Costo, like any
other unknown column, is ignored: the contract has no field for it, and costs come from purchase
prices. A catalog has no period, so the date line ("Al dd/mm/yyyy", "Fecha: ...") gives a
one-day period; a printed-on line ("Impreso el ...") is never the report date.

Rows are grouped into one recipe per product name (case and accents aside), so a dish whose
Clave is missing on some rows is still one recipe; a name with two claves, or a clave with two
names, is refused. An ingredient repeated in one recipe (by clave or by name) is refused.
"Recetas - Insumos elaborados" (sub-recipes such as salsa verde) is another report, not read yet.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import MalformedReport
from mermia_api.ingestion.parsers._sr_common import (
    DATE,
    SEARCH_ROWS,
    Columns,
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
REQUIRED = {PRODUCT, INGREDIENT, QTY, UNIT}
KNOWN = {CODE, PRODUCT, INGREDIENT_CODE, INGREDIENT, QTY, UNIT, YIELD}
ALIASES = {  # normalized header -> known name
    "rendimiento": YIELD,
    "rendimiento%": YIELD,
    "rendimiento (%)": YIELD,
    "% rendimiento": YIELD,
    "%rendimiento": YIELD,
    "clave del insumo": INGREDIENT_CODE,
    "clave de insumo": INGREDIENT_CODE,
}

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
# A yield this low is a fraction (0.92 for 92 %) read as percent points: it would cost the
# line about a hundred times too much, so a person checks it.
MAX_FRACTION_YIELD = Decimal(1)
# The report's date: "Al 12/10/2026", "Del ... al 12/10/2026" or "Fecha: 12/10/2026" (normalized)
AS_OF = re.compile(rf"\b(?:al|fecha\s*:?)\s*{DATE}")
PRINTED = re.compile(r"\bimpres(?:o|ion)\b")  # "Impreso el ...", "Fecha de impresión ..."


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


def _cell_date(cell: Any) -> tuple[bool, dt.date] | None:
    """(whether the date is labelled "Al"/"Fecha", the date) of a title cell, or None. The last
    date of a line counts, so "Del 01/10/2026 al 12/10/2026" is the 12th."""
    if isinstance(cell, dt.datetime):  # an Excel date cell
        return False, cell.date()
    if isinstance(cell, dt.date):
        return False, cell
    line = norm(cell)
    if PRINTED.search(line):
        return None
    labelled = AS_OF.findall(line)
    found = labelled or re.findall(DATE, line)
    if not found:
        return None
    return bool(labelled), sr_date("/".join(found[-1]))


def _as_of(title: list[Row]) -> Period:
    """The report's date as a one-day period: the first "Al"/"Fecha" date in the title block, or
    else its first date; printed-on lines are skipped."""
    dates = [d for row in title for cell in row if (d := _cell_date(cell)) is not None]
    labelled = [day for is_labelled, day in dates if is_labelled]
    days = labelled or [day for _, day in dates]
    if days:
        return Period.model_validate({"from": days[0], "to": days[0]})
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


def _yield(value: Any, where: str) -> Decimal:
    """Percent points rounded half-up to the contract's four decimals (100/1.08 is 92.5926)."""
    pct = number(value, where).quantize(YIELD_PLACES, rounding=ROUND_HALF_UP)
    if not 0 < pct <= MAX_YIELD:
        raise MalformedReport(
            f"El rendimiento {value} en {where} debe ser un porcentaje mayor que cero y hasta "
            f"{MAX_YIELD.normalize()}.",
            f"yield out of range at {where}: {value!r}",
        )
    return pct


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


def _warning(code: str, message_es: str, n: int) -> IssueIn:
    return IssueIn(severity=IssueSeverity.warning, code=code, message_es=message_es, row_ref=str(n))


def _unknown_yield_columns(header: Row, cols: Columns, n: int) -> list[IssueIn]:
    """A warning per header that mentions rendimiento but is not the yield column: its yields
    would be dropped silently, and the lines costed at the ingredient's default yield."""
    used = {i for i, _ in cols.values()}
    return [
        _warning(
            "sr.unknown_yield_column",
            f"No reconocí la columna «{text(cell)}»; si trae el rendimiento de los insumos, no "
            "lo usé y las recetas se costean con el rendimiento normal de cada insumo. "
            "Revísalo antes de usar las recetas.",
            n,
        )
        for i, cell in enumerate(header)
        if "rendimiento" in norm(cell) and i not in used
    ]


@dataclass
class _Recipes:
    """Recipe rows grouped by product name (normalized), in order of first appearance."""

    names: dict[str, str] = field(default_factory=dict)  # product key -> name as first given
    codes: dict[str, str] = field(default_factory=dict)  # product key -> its clave
    keys: dict[str, str] = field(default_factory=dict)  # clave -> product key
    lines: dict[str, list[RecipeLineIn]] = field(default_factory=dict)
    seen: dict[tuple[str, str], int] = field(default_factory=dict)  # (product, ingredient) -> row

    def _product(self, row: _Row, n: int) -> str:
        key = norm(row.product)
        code = row.product_code
        name = self.names.setdefault(key, row.product)
        if code is None:
            return key
        other = self.keys.setdefault(code, key)
        if other != key:
            raise MalformedReport(
                f"La clave {code} aparece como «{self.names[other]}» y como «{row.product}» "
                f"(fila {n}). Envíame el reporte con un nombre por producto.",
                f"product {code!r} has two names, second at row {n}",
            )
        known = self.codes.setdefault(key, code)
        if known != code:
            raise MalformedReport(
                f"El producto «{name}» aparece con las claves {known} y {code} (fila {n}). "
                "Envíame el reporte con una clave por producto.",
                f"product {key!r} has two claves, second at row {n}",
            )
        return key

    def add(self, row: _Row, n: int) -> None:
        key = self._product(row, n)
        ingredient = row.line.ingredient_external_id
        pairs = [(key, f"name:{norm(row.line.ingredient_name)}")]
        if ingredient is not None:
            pairs.append((key, f"code:{ingredient}"))
        first = next((self.seen[p] for p in pairs if p in self.seen), None)
        if first is not None:
            raise MalformedReport(
                f"Las filas {first} y {n} repiten el insumo «{row.line.ingredient_name}» "
                f"en la receta de «{self.names[key]}». Envíame el reporte con una fila por insumo.",
                f"ingredient {row.line.ingredient_name!r} repeated in {key!r} at rows {first} "
                f"and {n}",
            )
        self.seen.update(dict.fromkeys(pairs, n))
        self.lines.setdefault(key, []).append(row.line)

    def recipes(self) -> list[RecipeIn]:
        return [
            RecipeIn(
                menu_item_external_id=self.codes.get(key),
                menu_item_name=name,
                yield_qty=Decimal(1).quantize(QTY_PLACES),
                lines=self.lines[key],
            )
            for key, name in self.names.items()
        ]


def parse(wb: Workbook) -> NormalizedBatch:
    sheet_name = _sheet_name(wb)
    if sheet_name is None:  # the registry calls parse only after matches
        raise MalformedReport("El reporte no tiene el formato esperado.", "header not found")
    h = _header_at(rows(wb, sheet_name, max_row=SEARCH_ROWS))
    assert h is not None
    sheet_rows = read_table(wb, sheet_name, h, MAX_ROWS)
    title = sheet_rows[:h]
    as_of = _as_of(title)
    cols = columns(sheet_rows[h], KNOWN, ALIASES)

    grouped = _Recipes()
    issues = _unknown_yield_columns(sheet_rows[h], cols, h + 1)
    for n, cells in enumerate(sheet_rows[h + 1 :], start=h + 2):
        line = Line(cells, n, cols)
        if _is_footer(line):
            continue
        row = _read(line)
        grouped.add(row, n)
        issues.extend(row.issues)
    recipes = grouped.recipes()
    if not recipes:
        raise MalformedReport(
            "El reporte no tiene ninguna receta; revisa que exportaste «Recetas - Productos».",
            "no recipe rows",
        )
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
