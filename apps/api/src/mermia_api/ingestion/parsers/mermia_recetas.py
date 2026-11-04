"""The MermIA recipe template (plantilla de recetas), filled by the owner and sent back.

Layout (written by ingestion/templates/recetas.py, which imports the names below): a sheet
"Recetas" with a title block ("<restaurant> - <location>", or "<restaurant> - Todas las
sucursales" for the whole tenant: no location hint; "Plantilla de recetas MermIA", "Versión 1",
"Fecha: dd/mm/aaaa"), then the header
Clave | Platillo | Porciones | Insumo | Cantidad | Unidad | Rendimiento % | Notas.
The dish (Clave, Platillo, Porciones) is written once; the rows below it, blank ones included,
belong to it until the next Platillo. A dish written again (on every row, as in the SR report)
joins its recipe. A dish with no line has no recipe yet and is skipped. A row with Clave or
Porciones but no Platillo is a dish without a name: it and the rows below it are held, never
joined to the dish above.

Output: one catalog batch (source_kind manual), one RecipeIn per dish with lines. Porciones is
yield_qty (blank is one portion). Quantities leave in base units and yields as percent points,
read as the SR Recetas parser reads them (_recipe_units). Notas and unknown columns are ignored.

Each problem (a quantity or Porciones of zero or less, an unknown unit, a missing value, an
implausible quantity or yield, an ingredient twice, two claves or Porciones for one dish) is an
error-level plantilla.* issue that holds only its own dish, plus one plantilla.recipe_held warning
naming it: proposing a recipe without a line would understate its cost. The other dishes load.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from openpyxl.workbook.workbook import Workbook
from pydantic import ValidationError

from mermia_api.ingestion.errors import MalformedReport
from mermia_api.ingestion.parsers._recipe_units import (
    IMPLAUSIBLE_QTY,
    MAX_FRACTION_YIELD,
    MAX_QTY,
    QTY_PLACES,
    base_qty,
    unit_of,
    yield_pct,
)
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

PARSER = "mermia.plantilla_recetas@v1"
VERSION = 1
MAX_ROWS = 50_000  # far above a real recipe book; a small zip cannot unpack into a huge sheet
TOO_MANY_ROWS = "borra las filas que no usas y envíamela de nuevo"

# What the writer prints, in Mexican Spanish
TITLE = "Plantilla de recetas MermIA"
VERSION_LINE = f"Versión {VERSION}"
DATE_LINE = "Fecha: {:%d/%m/%Y}"
SHEET_INSTRUCTIONS = "Instrucciones"
SHEET_RECIPES = "Recetas"
SHEET_INGREDIENTS = "Insumos"
ALL_LOCATIONS = "Todas las sucursales"  # the location line of a template for the whole tenant
CODE, DISH, PORTIONS, INGREDIENT, QTY, UNIT, YIELD, NOTES = HEADER = (
    "Clave",
    "Platillo",
    "Porciones",
    "Insumo",
    "Cantidad",
    "Unidad",
    "Rendimiento %",
    "Notas",
)
INGREDIENTS_HEADER = ("Insumo", "Unidad base", "Rendimiento normal %", "Categoría")
UNIT_CHOICES = ("g", "kg", "ml", "l", "pza")

REQUIRED = {norm(c) for c in (DISH, INGREDIENT, QTY, UNIT)}
KNOWN = {norm(c) for c in HEADER}
HELD = "plantilla.recipe_held"
LINE_WITHOUT_DISH = "plantilla.line_without_dish"
DISH_NAME_MISSING = "plantilla.dish_name_missing"
VERSION_RE = re.compile(r"^version\s+(\d+)$")
DATE_RE = re.compile(rf"\bfecha\s*:?\s*{DATE}")


class _Problem(Exception):
    def __init__(self, code: str, message_es: str) -> None:
        super().__init__(message_es)
        self.code = code
        self.message_es = message_es


def _header_at(sheet_rows: list[Row]) -> int | None:
    for i, row in enumerate(sheet_rows[:SEARCH_ROWS]):
        if {norm(c) for c in row} >= REQUIRED:
            return i
    return None


def _sheet_name(wb: Workbook) -> str | None:
    """The sheet with the template's title and header in its first rows."""
    for name in wb.sheetnames:
        top = rows(wb, name, max_row=SEARCH_ROWS)
        h = _header_at(top)
        if h is not None and has_title(top, h, norm(TITLE)):
            return name
    return None


def matches(wb: Workbook) -> bool:
    return _sheet_name(wb) is not None


def _check_version(title: list[Row]) -> None:
    for cell in (c for row in title for c in row):
        m = VERSION_RE.match(norm(cell))
        if m and int(m[1]) != VERSION:
            raise MalformedReport(
                f"Esta plantilla es de la versión {m[1]} y solo conozco la versión {VERSION}. "
                "Pídeme una plantilla nueva y llénala de nuevo.",
                f"template version {m[1]}",
            )


def _as_of(title: list[Row]) -> Period:
    """The template's "Fecha:" line as a one-day period."""
    for cell in (c for row in title for c in row):
        m = DATE_RE.search(norm(cell))
        if m:
            day = sr_date("/".join(m.groups()))
            return Period.model_validate({"from": day, "to": day})
    raise MalformedReport(
        "No encontré la fecha de la plantilla (la línea «Fecha: dd/mm/aaaa»). Pídeme una "
        "plantilla nueva.",
        "no date in the title block",
    )


def _location_hint(title: list[Row]) -> str | None:
    """The location the title names; None for a template of the whole tenant."""
    hint = location_hint(title)
    return None if hint is None or norm(hint) == norm(ALL_LOCATIONS) else hint


def _number(line: Line, name: str, code: str) -> Decimal:
    try:
        value = line.read(norm(name), number)
    except MalformedReport as e:
        raise _Problem(code, e.message_es) from e
    assert value is not None
    return value


def _portions(line: Line, dish: str) -> Decimal | None:
    """The dish row's Porciones (None when blank)."""
    if _cell(line, PORTIONS) is None:
        return None
    what = f"las porciones de «{dish}»"
    value = _number(line, PORTIONS, "plantilla.porciones_invalid")
    if value <= 0:
        raise _Problem(
            "plantilla.porciones_not_positive",
            f"En la fila {line.n}, {what} son {_cell(line, PORTIONS)}; deben ser más "
            "que cero (cuántas porciones salen de la receta).",
        )
    portions = value.quantize(QTY_PLACES, rounding=ROUND_HALF_UP)
    if not 0 < portions < MAX_QTY:
        raise _Problem(
            "plantilla.porciones_invalid",
            f"En la fila {line.n}, {what} ({_cell(line, PORTIONS)}) no son un número "
            "válido de porciones.",
        )
    return portions


def _cell(line: Line, name: str) -> str | None:
    """A cell of the column with header `name`, as text (None when blank)."""
    return text(line.raw(norm(name)))


def _missing(line: Line, name: str) -> bool:
    return _cell(line, name) is None


def _read_line(line: Line, dish: str) -> RecipeLineIn:
    """One recipe line, or a _Problem that holds the dish."""
    ingredient = _cell(line, INGREDIENT)
    n = line.n
    if ingredient is None:
        raise _Problem(
            "plantilla.ingredient_missing",
            f"En la fila {n}, falta el insumo de la receta de «{dish}».",
        )
    if _missing(line, QTY):
        raise _Problem(
            "plantilla.qty_missing", f"En la fila {n}, falta la cantidad de {ingredient}."
        )
    qty = _number(line, QTY, "plantilla.qty_invalid")
    if qty <= 0:
        raise _Problem(
            "plantilla.qty_not_positive",
            f"En la fila {n}, la cantidad de {ingredient} es {_cell(line, QTY)}; debe "
            "ser mayor que cero.",
        )
    unit = _cell(line, UNIT)
    if unit is None:
        raise _Problem(
            "plantilla.unit_missing", f"En la fila {n}, falta la unidad de {ingredient}."
        )
    known = unit_of(unit)
    if known is None:
        raise _Problem(
            "plantilla.unit_unknown",
            f"En la fila {n}, no conozco la unidad «{unit}» de {ingredient}; usa "
            f"{', '.join(UNIT_CHOICES[:-1])} o {UNIT_CHOICES[-1]}.",
        )
    try:
        base = base_qty(qty, known[1], line.where(norm(QTY)))
    except MalformedReport as e:
        raise _Problem("plantilla.qty_invalid", e.message_es) from e
    if base >= IMPLAUSIBLE_QTY[known[0]]:
        raise _Problem(
            "plantilla.qty_implausible",
            f"En la fila {n}, la cantidad de {ingredient} es {_cell(line, QTY)} {unit} "
            "por receta; parece demasiado (¿una coma decimal?).",
        )
    try:
        pct = line.read(norm(YIELD), yield_pct)
    except MalformedReport as e:
        raise _Problem("plantilla.yield_invalid", e.message_es) from e
    if pct is not None and pct <= MAX_FRACTION_YIELD:
        raise _Problem(
            "plantilla.yield_implausible",
            f"En la fila {n}, el rendimiento de {ingredient} es {pct.normalize()} %; parece una "
            "fracción (0.92 en lugar de 92).",
        )
    return RecipeLineIn(
        ingredient_name=ingredient, qty_base=base, unit=known[0], yield_override_pct=pct
    )


@dataclass
class _Dish:
    name: str
    code: str | None
    portions: Decimal | None
    lines: list[RecipeLineIn] = field(default_factory=list)
    seen: dict[str, int] = field(default_factory=dict)  # ingredient (normalized) -> its row
    errors: list[int] = field(default_factory=list)  # rows with a problem

    def recipe(self) -> RecipeIn:
        return RecipeIn(
            menu_item_external_id=self.code,
            menu_item_name=self.name,
            yield_qty=self.portions or Decimal(1).quantize(QTY_PLACES),
            lines=self.lines,
        )


def _error(problem: _Problem, n: int, outcome: str = "No tomé esa receta.") -> IssueIn:
    message = f"{problem.message_es} {outcome}"
    return IssueIn(
        severity=IssueSeverity.error, code=problem.code, message_es=message, row_ref=str(n)
    )


@dataclass
class _Dishes:
    """The template's dishes by name (normalized), in order of first appearance."""

    found: dict[str, _Dish] = field(default_factory=dict)
    issues: list[IssueIn] = field(default_factory=list)
    orphans: list[_Problem] = field(default_factory=list)  # rows held for want of a dish name

    def orphan(self, problem: _Problem, n: int) -> None:
        self.orphans.append(problem)
        self.issues.append(_error(problem, n, "No tomé esa receta."))

    def hold(self, d: _Dish, problem: _Problem, n: int) -> None:
        d.errors.append(n)
        self.issues.append(_error(problem, n))

    def start(self, line: Line, name: str) -> _Dish:
        """The dish a Platillo row names: a new one, or the earlier one with that name."""
        code = _cell(line, CODE)
        try:
            portions = _portions(line, name)
        except _Problem as p:
            d = self.found.setdefault(norm(name), _Dish(name, code, None))
            self.hold(d, p, line.n)
            return d
        d = self.found.setdefault(norm(name), _Dish(name, code, portions))
        if code is not None and d.code is not None and code != d.code:
            what = f"«{name}» aparece con las claves {d.code} y {code}"
            self.hold(
                d, _Problem("plantilla.clave_conflict", f"En la fila {line.n}, {what}."), line.n
            )
        if portions is not None and d.portions is not None and portions != d.portions:
            what = f"«{name}» trae {d.portions.normalize()} y {portions.normalize()} porciones"
            problem = _Problem("plantilla.porciones_conflict", f"En la fila {line.n}, {what}.")
            self.hold(d, problem, line.n)
        d.code, d.portions = d.code or code, d.portions or portions
        return d

    def add(self, d: _Dish, line: Line) -> None:
        try:
            x = _read_line(line, d.name)
        except _Problem as p:
            self.hold(d, p, line.n)
            return
        key = norm(x.ingredient_name)
        if key in d.seen:
            problem = _Problem(
                "plantilla.ingredient_repeated",
                f"Las filas {d.seen[key]} y {line.n} repiten {x.ingredient_name} en la receta de "
                f"«{d.name}»; deja una sola fila por insumo.",
            )
            self.hold(d, problem, line.n)
            return
        d.seen[key] = line.n
        d.lines.append(x)

    def recipes(self) -> list[RecipeIn]:
        found: list[RecipeIn] = []
        for d in self.found.values():
            if d.errors or not d.lines:
                continue
            try:
                found.append(d.recipe())
            except ValidationError:  # a value the contract refuses holds the dish, never crashes
                problem = _Problem(
                    "plantilla.recipe_invalid", f"La receta de «{d.name}» tiene un valor inválido."
                )
                self.hold(d, problem, next(iter(d.seen.values())))
        return found

    def held(self) -> list[IssueIn]:
        """One warning per held dish, at its first row with a problem."""
        found = []
        for d in self.found.values():
            if not d.errors:
                continue
            listed = [str(n) for n in sorted(set(d.errors))]
            where = (
                f"la fila {listed[0]}"
                if len(listed) == 1
                else f"las filas {', '.join(listed[:-1])} y {listed[-1]}"
            )
            found.append(
                IssueIn(
                    severity=IssueSeverity.warning,
                    code=HELD,
                    message_es=f"No tomé la receta de «{d.name}» porque tiene errores en {where}. "
                    "Corrígela en la plantilla y vuelve a enviármela; las demás recetas sí las "
                    "tomé.",
                    row_ref=listed[0],
                )
            )
        return found


def _has_line(line: Line) -> bool:
    return any(not _missing(line, c) for c in (INGREDIENT, QTY, UNIT, YIELD))


def _nameless(line: Line) -> _Problem | None:
    """A row that starts a dish (Clave or Porciones) without its Platillo."""
    given = [c for c in (CODE, PORTIONS) if not _missing(line, c)]
    if not given:
        return None
    return _Problem(
        DISH_NAME_MISSING,
        f"La fila {line.n} tiene {' y '.join(given)} pero no el nombre del platillo; escribe el "
        "nombre en «Platillo».",
    )


def _read_dishes(sheet_rows: list[Row], h: int, cols: Columns) -> _Dishes:
    """Every row below the header, by dish. A nameless dish (and its rows) joins none."""
    dishes = _Dishes()
    current: _Dish | None = None
    skipping = False  # below a nameless dish: its rows are held with it
    for n, cells in enumerate(sheet_rows[h + 1 :], start=h + 2):
        line = Line(cells, n, cols)
        name = _cell(line, DISH)
        nameless = None if name is not None else _nameless(line)
        if name is not None:
            current, skipping = dishes.start(line, name), False
        elif nameless is not None:
            dishes.orphan(nameless, n)
            current, skipping = None, True
        if skipping or not _has_line(line):
            continue
        if current is None:
            problem = _Problem(
                LINE_WITHOUT_DISH,
                f"La fila {n} trae un insumo pero ningún platillo arriba de ella.",
            )
            dishes.orphans.append(problem)
            dishes.issues.append(_error(problem, n, "No la tomé."))
            continue
        dishes.add(current, line)
    return dishes


def _no_recipe(dishes: _Dishes) -> MalformedReport:
    """The refusal of a template without any dish to take, naming the first stray row if any."""
    if dishes.orphans:
        first = dishes.orphans[0]
        return MalformedReport(
            f"No tomé ninguna receta de la plantilla. {first.message_es} Corrígela y envíamela "
            "de nuevo.",
            f"no dish, first stray row: {first.code}",
        )
    return MalformedReport(
        "La plantilla no tiene ninguna receta: llena los insumos de al menos un platillo y "
        "envíamela de nuevo.",
        "no recipe lines",
    )


def parse(wb: Workbook) -> NormalizedBatch:
    sheet_name = _sheet_name(wb)
    if sheet_name is None:  # the registry calls parse only after matches
        raise MalformedReport("La plantilla no tiene el formato esperado.", "header not found")
    h = _header_at(rows(wb, sheet_name, max_row=SEARCH_ROWS))
    assert h is not None
    sheet_rows = read_table(wb, sheet_name, h, MAX_ROWS, what="La plantilla", fix=TOO_MANY_ROWS)
    title = sheet_rows[:h]
    _check_version(title)
    as_of = _as_of(title)
    cols = columns(sheet_rows[h], KNOWN)

    dishes = _read_dishes(sheet_rows, h, cols)
    recipes = dishes.recipes()
    if not any(d.lines or d.errors for d in dishes.found.values()):
        raise _no_recipe(dishes)
    return NormalizedBatch(
        parser=PARSER,
        source_kind=SourceKind.manual,
        location_hint=_location_hint(title),
        period=as_of,
        grain=Grain.catalog,
        totals=Totals(lines=len(recipes)),
        recipes=recipes,
        issues=[*dishes.issues, *dishes.held()],
    )
