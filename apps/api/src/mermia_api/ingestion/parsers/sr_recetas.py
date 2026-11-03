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

Rows are grouped into one recipe per Clave, so one name under two claves (two sizes of an agua)
is two recipes. A row without a Clave joins the recipe of its product name (case and accents
aside) when that name has one clave in the file, so a dish whose Clave is missing on some rows is
still one recipe; when the name has several claves the row is refused, and when it has none the
name alone is the recipe. A clave with two names is refused, and so is an ingredient repeated in
one recipe (by clave or by name). A quantity of 1000 kg, l or pza or more per portion is an
error-level issue (a decimal comma read as thousands, "1,500" kg).
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
# Per portion, a base quantity this large is a slip (a decimal comma read as thousands,
# "1,500" kg): 1000 kg or l (in g or ml), or 1000 pieces, goes to a person.
IMPLAUSIBLE_QTY = {"g": Decimal(10) ** 6, "ml": Decimal(10) ** 6, "pza": Decimal(1000)}
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
    line: RecipeLineIn | None  # None when the line is dropped (its quantity is not positive)
    issues: tuple[IssueIn, ...]


def _read(line: Line) -> _Row:
    product = _required_text(line, PRODUCT, "el producto")
    ingredient = _required_text(line, INGREDIENT, "el insumo")
    qty = line.read(QTY, number)
    if qty is None:
        raise MalformedReport(
            f"Falta la cantidad en la fila {line.n}.", f"no quantity at row {line.n}"
        )
    unit = _required_text(line, UNIT, "la unidad")
    issues: list[IssueIn] = []
    if qty <= 0:
        issues.append(
            _error(
                "sr.qty_not_positive",
                f"En la fila {line.n}, la cantidad de {ingredient} en la receta de {product} es "
                f"{text(line.raw(QTY))}; debe ser mayor que cero. No usé ese insumo: corrígelo "
                "antes de usar la receta.",
                line.n,
            )
        )
        return _Row(text(line.raw(CODE)), product, None, tuple(issues))
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
        if base >= IMPLAUSIBLE_QTY[base_unit]:
            issues.append(
                _error(
                    "sr.qty_implausible",
                    f"En la fila {line.n}, la cantidad de {ingredient} es "
                    f"{text(line.raw(QTY))} {unit} por porción; parece demasiado (¿una coma "
                    "decimal?). Revísala antes de usar la receta.",
                    line.n,
                )
            )
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


def _empty_recipes(
    bare: list[tuple[int, str | None, str]], by_name: dict[str, list[str]], grouped: _Recipes
) -> list[IssueIn]:
    """A warning per product row with no ingredient whose product has no rows at all."""
    found: list[IssueIn] = []
    warned: set[str] = set()
    for n, code, name in bare:
        keys = (
            [f"code:{code}"]
            if code is not None
            else [f"code:{c}" for c in by_name.get(norm(name), [])] or [f"name:{norm(name)}"]
        )
        label = name or code or ""
        if any(k in grouped.names for k in keys) or keys[0] in warned:
            continue
        warned.add(keys[0])
        found.append(
            _warning(
                "sr.recipe_empty",
                f"En la fila {n}, «{label}» no trae ningún insumo, así que no tiene receta. "
                "Revisa si falta capturarla en Soft Restaurant.",
                n,
            )
        )
    return found


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


def _listed(claves: list[str]) -> str:
    return claves[0] if len(claves) == 1 else f"{', '.join(claves[:-1])} y {claves[-1]}"


def _claves_by_name(read: list[tuple[int, _Row]]) -> dict[str, list[str]]:
    """Each product name (normalized) -> its claves in order. A clave with two names is
    refused."""
    first: dict[str, tuple[str, str]] = {}  # clave -> (name key, name as first given)
    by_name: dict[str, list[str]] = {}
    for n, row in read:
        code = row.product_code
        if code is None:
            continue
        key = norm(row.product)
        other_key, other_name = first.setdefault(code, (key, row.product))
        if other_key != key:
            raise MalformedReport(
                f"La clave {code} aparece como «{other_name}» y como «{row.product}» "
                f"(fila {n}). Envíame el reporte con un nombre por producto.",
                f"product {code!r} has two names, second at row {n}",
            )
        claves = by_name.setdefault(key, [])
        if code not in claves:
            claves.append(code)
    return by_name


def _clave(row: _Row, n: int, by_name: dict[str, list[str]]) -> str | None:
    """The row's clave, or the one clave its name has in the file; None when it has none."""
    if row.product_code is not None:
        return row.product_code
    claves = by_name.get(norm(row.product), [])
    if len(claves) > 1:
        raise MalformedReport(
            f"La fila {n} trae «{row.product}» sin clave, y ese producto aparece con las claves "
            f"{_listed(claves)}; no sé a cuál receta pertenece. Envíame el reporte con la clave "
            "en cada fila.",
            f"codeless row {n} for {row.product!r}, which has claves {claves}",
        )
    return claves[0] if claves else None


@dataclass
class _Recipes:
    """Recipe rows grouped by clave, or by product name for a name without one, in order of
    first appearance."""

    names: dict[str, str] = field(default_factory=dict)  # recipe key -> name as first given
    codes: dict[str, str | None] = field(default_factory=dict)  # recipe key -> its clave
    lines: dict[str, list[RecipeLineIn]] = field(default_factory=dict)
    seen: dict[tuple[str, str], int] = field(default_factory=dict)  # (recipe, ingredient) -> row

    def add(self, row: _Row, n: int, code: str | None) -> None:
        key = f"code:{code}" if code is not None else f"name:{norm(row.product)}"
        self.names.setdefault(key, row.product)
        self.codes.setdefault(key, code)
        if row.line is None:  # dropped: the recipe exists, but this line is not in it
            return
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
                menu_item_external_id=self.codes[key],
                menu_item_name=name,
                yield_qty=Decimal(1).quantize(QTY_PLACES),
                lines=self.lines[key],
            )
            for key, name in self.names.items()
            if key in self.lines  # a recipe whose every line was dropped is explained by issues
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

    issues = _unknown_yield_columns(sheet_rows[h], cols, h + 1)
    read: list[tuple[int, _Row]] = []
    bare: list[tuple[int, str | None, str]] = []  # product rows with no ingredient: n, clave, name
    for n, cells in enumerate(sheet_rows[h + 1 :], start=h + 2):
        line = Line(cells, n, cols)
        if _is_footer(line):
            product = text(line.raw(PRODUCT))
            if product is not None or text(line.raw(CODE)) is not None:
                bare.append((n, text(line.raw(CODE)), product or ""))
            continue
        row = _read(line)
        read.append((n, row))
        issues.extend(row.issues)
    by_name = _claves_by_name(read)  # all rows first: a codeless row may come before its clave
    grouped = _Recipes()
    for n, row in read:
        grouped.add(row, n, _clave(row, n, by_name))
    issues.extend(_empty_recipes(bare, by_name, grouped))
    recipes = grouped.recipes()
    if not grouped.names:
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
