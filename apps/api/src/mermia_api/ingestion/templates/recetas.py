"""The recipe template (plantilla de recetas): generated from the tenant's menu, filled by the
owner or manager in Excel or Google Sheets, and read back by parsers/mermia_recetas.py, whose
sheet and column names this module uses.

- "Instrucciones": how to fill it, in Mexican Spanish.
- "Recetas": the title block, the header, then one block per menu item (modifiers left out:
  "Extra queso" is costed with the dish it goes on), listed by units sold in the 28 days
  before the template's date. A dish with a recipe of record is prefilled with its lines in
  base units, biggest quantity first (a yield only when it differs from the ingredient's
  default); a dish without one gets its row plus BLANK_ROWS blank rows. Insumo and Unidad have
  dropdowns: the Insumo one only warns, so a new ingredient can still be typed.
- A template for the whole tenant says "Todas las sucursales" where the location goes, and
  lists only the items shared by every location (the ones the loader can match without one).
- Text that starts with = + - or @ (a dish named "=HYPERLINK(...)") is written as text, never
  as a formula.
- "Insumos": the tenant's ingredients, a protected reference that feeds the Insumo dropdown.

render(data) is pure and gives the same bytes for the same data. build(conn, ...) reads the
database. CLI (writes the file; --golden also writes the parsed batch beside it, for samples):
    uv run python -m mermia_api.ingestion.templates.recetas --tenant <uuid> [--location <uuid>]
        [--date yyyy-mm-dd] --out plantilla.xlsx [--golden]
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from mermia_api.ingestion.parsers import mermia_recetas as fmt
from mermia_api.ingestion.recipes import TENANT_TIMEZONE, current_recipe
from mermia_api.ingestion.registry import parse_file

BLANK_ROWS = 8  # rows to fill below a dish without a recipe
EXTRA_ROWS = 300  # rows below the last dish that keep the dropdowns, for lines the owner adds
SALES_DAYS = 28  # dishes are listed by units sold in this many days before the template's date
FORMULA_START = ("=", "+", "-", "@")  # what a spreadsheet may read as a formula
WIDTHS = (10, 34, 11, 34, 11, 9, 15, 30)  # Recetas columns, in characters
INGREDIENT_WIDTHS = (34, 13, 21, 16)
INSTRUCTIONS = (
    "Cómo llenar la plantilla de recetas",
    "1. En la hoja «Recetas», cada platillo empieza en la fila con su nombre; las filas de abajo "
    "son sus insumos, hasta el siguiente platillo.",
    "2. Los platillos que ya tienen receta vienen llenos: corrige solo lo que cambió. Para "
    "agregar un insumo, inserta una fila debajo del platillo.",
    "3. Escribe cuánto lleva la receta completa de cada insumo y su unidad: g, kg, ml, l o pza.",
    "4. Porciones: cuántas porciones salen de la receta (casi siempre 1).",
    "5. Rendimiento %: déjalo vacío para usar el rendimiento normal del insumo (hoja «Insumos»); "
    "escríbelo solo si en este platillo es distinto, por ejemplo 75.",
    "6. Elige el insumo de la lista. Si no está, escribe su nombre: lo doy de alta cuando "
    "apruebes la receta.",
    "7. Solo los platillos de la lista pueden llevar receta: no cambies su nombre ni su Clave. "
    "Un platillo nuevo aparece en la lista cuando se vende en Soft Restaurant o se da de alta "
    "en el menú; entonces pídeme una plantilla nueva.",
    "8. Guarda el archivo en Excel (.xlsx) y envíamelo. Ningún cambio se usa hasta que lo "
    "apruebes.",
)


@dataclass(frozen=True)
class TemplateLine:
    ingredient: str
    qty_base: Decimal
    unit: str  # base unit: g, ml or pza
    yield_pct: Decimal | None  # None: the ingredient's default


@dataclass(frozen=True)
class TemplateDish:
    code: str | None
    name: str
    yield_qty: Decimal | None  # None: no recipe yet (written as one portion)
    lines: tuple[TemplateLine, ...]


@dataclass(frozen=True)
class TemplateIngredient:
    name: str
    base_unit: str
    default_yield_pct: Decimal
    category: str | None


@dataclass(frozen=True)
class Template:
    restaurant: str
    location: str | None  # None: a template for the whole tenant
    day: dt.date
    dishes: tuple[TemplateDish, ...]
    ingredients: tuple[TemplateIngredient, ...]


def _number(value: Decimal) -> int | float:
    """A cell value: whole numbers as integers, so Excel shows 75 and not 75.0."""
    return int(value) if value == value.to_integral_value() else float(value)


def _append(ws: Worksheet, values: Sequence[Any]) -> None:
    """Appends a row. A text value a spreadsheet could take for a formula stays text, so it
    reads back as typed (openpyxl turns "=..." into a formula; Excel would run +, - and @ ones
    once edited)."""
    ws.append(list(values))
    for column, value in enumerate(values, start=1):
        if isinstance(value, str) and value.startswith(FORMULA_START):
            cell = ws.cell(ws.max_row, column)
            cell.data_type = "s"
            cell.quotePrefix = True


def _instructions(ws: Worksheet) -> None:
    ws.column_dimensions["A"].width = 110
    for line in INSTRUCTIONS:
        _append(ws, [line])
    ws["A1"].font = Font(bold=True, size=14)


def _recipes(ws: Worksheet, data: Template) -> None:
    title = f"{data.restaurant} - {data.location or fmt.ALL_LOCATIONS}"
    for line in (title, fmt.TITLE, fmt.VERSION_LINE, fmt.DATE_LINE.format(data.day)):
        _append(ws, [line])
    ws["A2"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(list(fmt.HEADER))
    header_row = ws.max_row
    for cell in ws[header_row]:
        cell.font = Font(bold=True)
    ws.freeze_panes = f"A{header_row + 1}"
    for i, width in enumerate(WIDTHS):
        ws.column_dimensions[chr(ord("A") + i)].width = width
    for d in data.dishes:
        dish = [d.code, d.name, _number(d.yield_qty or Decimal(1))]
        if not d.lines:
            _append(ws, dish)
            for _ in range(BLANK_ROWS):
                ws.append([])
            continue
        for i, x in enumerate(d.lines):
            pct = None if x.yield_pct is None else _number(x.yield_pct)
            _append(
                ws,
                [*(dish if i == 0 else [None] * 3), x.ingredient, _number(x.qty_base), x.unit, pct],
            )
    _dropdowns(ws, data, header_row + 1, ws.max_row + EXTRA_ROWS)


def _column(name: str) -> str:
    return chr(ord("A") + fmt.HEADER.index(name))


def _dropdowns(ws: Worksheet, data: Template, first: int, last: int) -> None:
    if data.ingredients:
        insumo = DataValidation(
            type="list",
            formula1=f"{fmt.SHEET_INGREDIENTS}!$A$2:$A${len(data.ingredients) + 1}",
            errorStyle="warning",
            showErrorMessage=True,
            errorTitle="Insumo nuevo",
            error="Este insumo no está en tu catálogo. Si es nuevo, déjalo: lo doy de alta "
            "cuando apruebes la receta.",
        )
        insumo.add(f"{_column(fmt.INGREDIENT)}{first}:{_column(fmt.INGREDIENT)}{last}")
        ws.add_data_validation(insumo)
    unidad = DataValidation(
        type="list",
        formula1=f'"{",".join(fmt.UNIT_CHOICES)}"',
        showErrorMessage=True,
        errorTitle="Unidad",
        error=f"Usa una de estas unidades: {', '.join(fmt.UNIT_CHOICES)}.",
    )
    unidad.add(f"{_column(fmt.UNIT)}{first}:{_column(fmt.UNIT)}{last}")
    ws.add_data_validation(unidad)


def _ingredients(ws: Worksheet, data: Template) -> None:
    ws.append(list(fmt.INGREDIENTS_HEADER))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for x in data.ingredients:
        _append(ws, [x.name, x.base_unit, _number(x.default_yield_pct), x.category])
    for i, width in enumerate(INGREDIENT_WIDTHS):
        ws.column_dimensions[chr(ord("A") + i)].width = width
    ws.protection.sheet = True  # a reference: no password, it only prevents slips


def render(data: Template) -> bytes:
    """The template as .xlsx bytes."""
    wb = Workbook()
    first = wb.active
    assert first is not None
    first.title = fmt.SHEET_INSTRUCTIONS
    _instructions(first)
    recetas = wb.create_sheet(fmt.SHEET_RECIPES)
    _recipes(recetas, data)
    _ingredients(wb.create_sheet(fmt.SHEET_INGREDIENTS), data)
    wb.active = 1
    return _save(wb, dt.datetime.combine(data.day, dt.time()))


def _save(wb: Workbook, stamp: dt.datetime) -> bytes:
    """Saves with the template's date as every timestamp, so the same data gives the same bytes
    (the committed sample is checked byte for byte)."""
    wb.properties.creator = "MermIA"
    wb.properties.created = stamp
    wb.properties.modified = stamp
    raw = io.BytesIO()
    wb.save(raw)
    out = io.BytesIO()
    iso = f"{stamp:%Y-%m-%dT%H:%M:%SZ}".encode()
    with zipfile.ZipFile(raw) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as dst:
        for info in src.infolist():
            content = src.read(info.filename)
            if info.filename == "docProps/core.xml":  # openpyxl stamps "modified" with now
                content = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*", rb"\g<1>" + iso, content)
            fixed = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            fixed.compress_type = zipfile.ZIP_STORED  # deflate output varies with the zlib build
            dst.writestr(fixed, content)
    return out.getvalue()


def ordered(lines: Sequence[TemplateLine]) -> tuple[TemplateLine, ...]:
    """A dish's lines as the template lists them: biggest quantity first, ties by name."""
    return tuple(sorted(lines, key=lambda x: (-x.qty_base, x.ingredient)))


def _dishes(
    conn: psycopg.Connection[Any], tenant_id: UUID, location_id: UUID | None, day: dt.date
) -> tuple[TemplateDish, ...]:
    """The active menu but its modifiers, by units sold in the SALES_DAYS before `day`, with its
    recipes. Without a location, only the items every location shares."""
    items = conn.execute(
        """select mi.id, mi.external_id, mi.name
           from public.menu_item mi
           left join app.v_item_sales_daily v
             on v.tenant_id = mi.tenant_id and v.menu_item_id = mi.id
            and (%s::uuid is null or v.location_id = %s)
            and v.business_date >= %s and v.business_date < %s
           where mi.tenant_id = %s and mi.is_active and mi.kind <> 'modifier'
             and (mi.location_id is null or mi.location_id = %s)
           group by mi.id
           order by coalesce(sum(v.units), 0) desc, mi.name, mi.id""",
        (
            location_id,
            location_id,
            day - dt.timedelta(days=SALES_DAYS),
            day,
            tenant_id,
            location_id,
        ),
    ).fetchall()
    dishes = []
    for item_id, code, name in items:
        recipe = current_recipe(conn, item_id, day)
        lines = () if recipe is None else recipe.lines
        dishes.append(
            TemplateDish(
                code,
                name,
                None if recipe is None else recipe.yield_qty,
                ordered(
                    [TemplateLine(x.name, x.qty_base, x.unit, x.yield_override_pct) for x in lines]
                ),
            )
        )
    return tuple(dishes)


def build(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID | None = None,
    day: dt.date | None = None,
) -> Template:
    """The template's data for a tenant (or one of its locations) on `day` (default: today in
    the location's time zone, or Mexico City's for the whole tenant)."""
    row = conn.execute(
        """select t.name, l.name,
                  (now() at time zone coalesce(l.timezone, %s))::date
           from public.tenant t left join public.location l on l.id = %s and l.tenant_id = t.id
           where t.id = %s""",
        (TENANT_TIMEZONE, location_id, tenant_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown tenant {tenant_id}")
    if location_id is not None and row[1] is None:
        raise ValueError(f"location {location_id} is not one of tenant {tenant_id}")
    day = day or row[2]
    ingredients = conn.execute(
        """select name, base_unit::text, default_yield_pct, category from public.ingredient
           where tenant_id = %s order by name, id""",
        (tenant_id,),
    ).fetchall()
    return Template(
        restaurant=row[0],
        location=row[1],
        day=day,
        dishes=_dishes(conn, tenant_id, location_id, day),
        ingredients=tuple(TemplateIngredient(*x) for x in ingredients),
    )


def golden(data: bytes) -> str:
    """The parsed batch of a template, as the samples' .golden.json files store it."""
    batch = parse_file(data).model_dump(mode="json")
    return json.dumps(batch, ensure_ascii=False, indent=1) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Writes the recipe template for a tenant.")
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--location", type=UUID)
    parser.add_argument("--date", type=dt.date.fromisoformat, help="yyyy-mm-dd; default today")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--golden", action="store_true", help="also write <out>.golden.json")
    parser.add_argument("--db-url", default=os.environ.get("MERMIA_DB_URL"))
    args = parser.parse_args(argv)
    if not args.db_url:
        print("set MERMIA_DB_URL or pass --db-url", file=sys.stderr)
        return 2
    with psycopg.connect(args.db_url) as conn:
        data = render(build(conn, args.tenant, args.location, args.date))
    args.out.write_bytes(data)
    if args.golden:
        args.out.with_name(args.out.stem + ".golden.json").write_text(golden(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
