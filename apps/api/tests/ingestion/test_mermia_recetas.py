"""MR-25: the MermIA recipe template parser (golden file in test_golden.py).

The owner fills the template we generate: the dish is written once and the rows below it are its
lines, Porciones is the recipe's yield, quantities leave in base units. Each problem holds only
its own dish with a plantilla.* issue; the rest of the file still loads. Wrong files raise a
ReportError with a Spanish message, never crash.
"""

import datetime as dt
import io
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import Workbook

from mermia_api.ingestion.errors import MalformedReport, UnknownReport
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import NormalizedBatch
from mermia_contracts.db.models import IssueSeverity, SourceKind

HEADER = [
    "Clave",
    "Platillo",
    "Porciones",
    "Insumo",
    "Cantidad",
    "Unidad",
    "Rendimiento %",
    "Notas",
]
TITLE = ["Taquería El Güero - Centro", "Plantilla de recetas MermIA", "Versión 1"]
PASTOR = "Tacos al pastor (orden de 3)"
HORCHATA = "Agua de horchata"
FIRST_ROW = 7  # title block (4 lines), a blank line, the header


def dish(code: str | None, name: str, porciones: Any, *line: Any) -> list[Any]:
    return [code, name, porciones, *line]


def line(ingredient: Any, qty: Any, unit: Any, pct: Any = None, notes: Any = None) -> list[Any]:
    return [None, None, None, ingredient, qty, unit, pct, notes]


PASTOR_ROWS = [
    dish("P001", PASTOR, 1, "Tortilla de maíz", 75, "g", None),
    line("Carne al pastor (adobada)", 0.06385, "kg", 92),
    line("Salsa verde (preparada)", 30, "g"),
]
HORCHATA_ROWS = [dish("P050", HORCHATA, 2, "Leche entera", 0.2, "l", None, "dos vasos")]


def xlsx(sheets: dict[str, list[list[Any]]]) -> bytes:
    wb = Workbook()
    first = wb.active
    assert first is not None
    wb.remove(first)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def template(
    *rows: list[Any],
    header: list[str] = HEADER,
    title: list[str] = TITLE,
    date: Any = "Fecha: 12/10/2026",
) -> bytes:
    recetas = [[t] for t in title] + [[date], [], header, *rows]
    return xlsx(
        {
            "Instrucciones": [["Cómo llenar la plantilla"], ["1. Escribe ..."]],
            "Recetas": recetas,
            "Insumos": [["Insumo", "Unidad base", "Rendimiento normal %", "Categoría"]],
        }
    )


def errors(batch: NormalizedBatch) -> list[tuple[str, str | None]]:
    return [(i.code, i.row_ref) for i in batch.issues if i.severity == IssueSeverity.error]


def held(batch: NormalizedBatch) -> list[str]:
    return [i.message_es for i in batch.issues if i.code == "plantilla.recipe_held"]


def test_a_small_template() -> None:
    batch = parse_file(
        template(
            *PASTOR_ROWS,
            *HORCHATA_ROWS,
            dish("P020", "Quesadilla", 1),  # no recipe yet: the owner left its rows blank
            line(None, None, None),
            line(None, None, None, None, "pendiente"),
        )
    )
    assert (batch.parser, batch.source_kind, batch.grain, batch.location_hint) == (
        "mermia.plantilla_recetas@v1",
        SourceKind.manual,
        "catalog",
        "Centro",
    )
    assert (batch.period.from_, batch.period.to) == (dt.date(2026, 10, 12), dt.date(2026, 10, 12))
    assert (batch.totals.lines, batch.issues) == (2, [])
    pastor, horchata = batch.recipes
    assert (pastor.menu_item_external_id, pastor.menu_item_name, pastor.yield_qty) == (
        "P001",
        PASTOR,
        Decimal("1.000000"),
    )
    assert [
        (x.ingredient_name, x.qty_base, x.unit, x.yield_override_pct) for x in pastor.lines
    ] == [
        ("Tortilla de maíz", Decimal("75.000000"), "g", None),
        ("Carne al pastor (adobada)", Decimal("63.850000"), "g", Decimal("92.0000")),
        ("Salsa verde (preparada)", Decimal("30.000000"), "g", None),
    ]
    assert all(x.ingredient_external_id is None for x in pastor.lines)
    assert horchata.yield_qty == Decimal("2.000000"), "Porciones is the recipe's yield"
    assert [(x.qty_base, x.unit) for x in horchata.lines] == [(Decimal("200.000000"), "ml")]


def test_blank_porciones_is_one_portion() -> None:
    (recipe,) = parse_file(
        template(dish("P001", PASTOR, None, "Tortilla de maíz", 75, "g"))
    ).recipes
    assert recipe.yield_qty == Decimal(1)


def test_the_dish_carries_down_across_blank_rows() -> None:
    batch = parse_file(
        template(
            dish("P001", PASTOR, 1, None, None, None),
            line(None, None, None),
            line("Tortilla de maíz", 75, "g"),
            [],
            line("Cebolla blanca", 10, "gramos"),
        )
    )
    (pastor,) = batch.recipes
    assert [x.ingredient_name for x in pastor.lines] == ["Tortilla de maíz", "Cebolla blanca"]


def test_a_dish_written_on_every_row_is_one_recipe() -> None:
    batch = parse_file(
        template(
            dish("P001", PASTOR, 1, "Tortilla de maíz", 75, "g"),
            dish(None, PASTOR, None, "Cebolla blanca", 10, "g"),
            dish("P001", "tacos al PASTOR (orden de 3)", 1, "Cilantro", 3, "g"),
        )
    )
    (pastor,) = batch.recipes
    assert len(pastor.lines) == 3
    assert batch.issues == []


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        (line("Cebolla blanca", 0, "g"), "plantilla.qty_not_positive"),
        (line("Cebolla blanca", -5, "g"), "plantilla.qty_not_positive"),
        (line("Cebolla blanca", "mucho", "g"), "plantilla.qty_invalid"),
        (line("Cebolla blanca", "0,5", "kg"), "plantilla.qty_invalid"),
        (line("Cebolla blanca", 0.0000001, "g"), "plantilla.qty_invalid"),
        (line("Cebolla blanca", None, "g"), "plantilla.qty_missing"),
        (line(None, 10, "g"), "plantilla.ingredient_missing"),
        (line("Cebolla blanca", 10, None), "plantilla.unit_missing"),
        (line("Cebolla blanca", 10, "taza"), "plantilla.unit_unknown"),
        (line("Cebolla blanca", 1500, "kg"), "plantilla.qty_implausible"),
        (line("Cebolla blanca", 10, "g", 0.92), "plantilla.yield_implausible"),
        (line("Cebolla blanca", 10, "g", 0), "plantilla.yield_invalid"),
        (line("Cebolla blanca", 10, "g", "alto"), "plantilla.yield_invalid"),
        (line("Tortilla de maíz", 10, "g"), "plantilla.ingredient_repeated"),
    ],
)
def test_a_bad_line_holds_only_its_dish(bad: list[Any], code: str) -> None:
    batch = parse_file(template(*PASTOR_ROWS, bad, *HORCHATA_ROWS))
    assert [r.menu_item_name for r in batch.recipes] == [HORCHATA]
    assert batch.totals.lines == 1
    assert errors(batch) == [(code, str(FIRST_ROW + 3))]
    (message,) = held(batch)
    assert f"«{PASTOR}»" in message
    assert f"fila {FIRST_ROW + 3}" in message


@pytest.mark.parametrize(
    ("porciones", "code"),
    [
        (0, "plantilla.porciones_not_positive"),
        (-2, "plantilla.porciones_not_positive"),
        ("dos", "plantilla.porciones_invalid"),
        (0.0000001, "plantilla.porciones_invalid"),
        (10**13, "plantilla.porciones_invalid"),
    ],
)
def test_porciones_that_are_not_positive_hold_only_their_dish(porciones: Any, code: str) -> None:
    bad = dish("P030", "Gringa", porciones, "Tortilla de harina", 1, "pza")
    batch = parse_file(template(*PASTOR_ROWS, bad, *HORCHATA_ROWS))
    assert [r.menu_item_name for r in batch.recipes] == [PASTOR, HORCHATA]
    assert errors(batch) == [(code, str(FIRST_ROW + 3))]
    (message,) = held(batch)
    assert "«Gringa»" in message


def test_two_claves_for_one_dish_hold_it() -> None:
    batch = parse_file(
        template(
            dish("P001", PASTOR, 1, "Tortilla de maíz", 75, "g"),
            dish("P002", PASTOR, None, "Cebolla blanca", 10, "g"),
            *HORCHATA_ROWS,
        )
    )
    assert [r.menu_item_name for r in batch.recipes] == [HORCHATA]
    assert errors(batch) == [("plantilla.clave_conflict", str(FIRST_ROW + 1))]


def test_two_porciones_for_one_dish_hold_it() -> None:
    batch = parse_file(
        template(
            dish("P001", PASTOR, 1, "Tortilla de maíz", 75, "g"),
            dish(None, PASTOR, 2, "Cebolla blanca", 10, "g"),
            *HORCHATA_ROWS,
        )
    )
    assert [r.menu_item_name for r in batch.recipes] == [HORCHATA]
    assert errors(batch) == [("plantilla.porciones_conflict", str(FIRST_ROW + 1))]


def test_a_line_above_the_first_dish_is_an_error_and_the_rest_loads() -> None:
    batch = parse_file(template(line("Cebolla blanca", 10, "g"), *PASTOR_ROWS))
    assert [r.menu_item_name for r in batch.recipes] == [PASTOR]
    assert errors(batch) == [("plantilla.line_without_dish", str(FIRST_ROW))]
    assert held(batch) == []


def test_every_dish_held_gives_an_empty_batch() -> None:
    batch = parse_file(template(dish("P001", PASTOR, 0, "Tortilla de maíz", 75, "g")))
    assert (batch.recipes, batch.totals.lines) == ([], 0)
    assert len(held(batch)) == 1


def test_a_template_without_any_recipe_is_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(template(dish("P001", PASTOR, 1), line(None, None, None)))
    assert "ninguna receta" in e.value.message_es


def test_another_version_is_refused() -> None:
    title = [*TITLE[:2], "Versión 2"]
    with pytest.raises(MalformedReport) as e:
        parse_file(template(*PASTOR_ROWS, title=title))
    assert "versión" in e.value.message_es


def test_a_missing_date_is_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(template(*PASTOR_ROWS, date="Sin fecha"))
    assert "fecha" in e.value.message_es


def sr_recetas(title: str = "Recetas - Productos", product: str = "Producto") -> bytes:
    header = ["Clave", product, "Clave insumo", "Insumo", "Cantidad", "Unidad", "Rendimiento %"]
    rows = [["P001", PASTOR, "I038", "Tortilla de maíz", 0.075, "KG", 100]]
    sheet: list[list[Any]] = [["Taquería El Güero - Centro"], [title], ["Al 12/10/2026"], []]
    sheet += [header, *rows]
    return xlsx({"Recetas": sheet})


def test_the_sr_report_and_the_template_cannot_be_mistaken_for_each_other() -> None:
    assert parse_file(sr_recetas()).parser == "sr.recetas@v1"
    assert parse_file(template(*PASTOR_ROWS)).parser == "mermia.plantilla_recetas@v1"
    with pytest.raises(UnknownReport):  # the template's header under the SR title
        parse_file(sr_recetas(product="Platillo"))
    with pytest.raises(UnknownReport):  # the SR header under the template's title
        parse_file(sr_recetas(title="Plantilla de recetas MermIA"))


def test_the_unknown_report_message_names_the_template() -> None:
    with pytest.raises(UnknownReport) as e:
        parse_file(xlsx({"Hoja1": [["nada"]]}))
    assert "la plantilla de recetas de MermIA" in e.value.message_es
    assert "«Recetas»" in e.value.message_es


@pytest.mark.parametrize(
    ("code", "porciones", "what"),
    [("P099", None, "Clave"), (None, 2, "Porciones"), ("P099", 2, "Clave y Porciones")],
)
def test_a_row_with_clave_or_porciones_but_no_platillo_is_held_not_joined(
    code: str | None, porciones: Any, what: str
) -> None:
    batch = parse_file(
        template(
            *PASTOR_ROWS,
            [code, None, porciones, "Cebolla blanca", 10, "g"],
            line("Cilantro", 3, "g"),
            *HORCHATA_ROWS,
        )
    )
    pastor, horchata = batch.recipes
    assert (pastor.menu_item_name, horchata.menu_item_name) == (PASTOR, HORCHATA)
    assert [x.ingredient_name for x in pastor.lines] == [
        "Tortilla de maíz",
        "Carne al pastor (adobada)",
        "Salsa verde (preparada)",
    ], "the nameless row and the rows below it do not join the dish above"
    assert errors(batch) == [("plantilla.dish_name_missing", str(FIRST_ROW + 3))]
    (issue,) = [i for i in batch.issues if i.code == "plantilla.dish_name_missing"]
    assert f"La fila {FIRST_ROW + 3} tiene {what} pero no el nombre del platillo" in (
        issue.message_es
    )


def test_ingredient_rows_under_a_dish_still_carry_down() -> None:
    batch = parse_file(template(*PASTOR_ROWS, line("Cilantro", 3, "g")))
    (pastor,) = batch.recipes
    assert len(pastor.lines) == 4
    assert batch.issues == []


def test_lines_without_a_dish_and_no_recipe_point_at_the_first_such_row() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(template(line("Cebolla blanca", 10, "g"), line("Cilantro", 3, "g")))
    assert "no tiene ninguna receta" not in e.value.message_es, "not the generic refusal"
    assert f"fila {FIRST_ROW}" in e.value.message_es
    assert "ningún platillo" in e.value.message_es


def test_only_a_nameless_dish_points_at_its_row() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(template(["P099", None, 1, "Cebolla blanca", 10, "g"]))
    assert f"fila {FIRST_ROW}" in e.value.message_es
    assert "nombre del platillo" in e.value.message_es


def test_too_many_rows_in_a_template_speaks_of_the_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mermia_api.ingestion.parsers import mermia_recetas

    monkeypatch.setattr(mermia_recetas, "MAX_ROWS", 2)
    with pytest.raises(MalformedReport) as e:
        parse_file(template(*PASTOR_ROWS))
    assert "renglones" in e.value.message_es
    assert "plantilla" in e.value.message_es
    assert "periodo" not in e.value.message_es


def test_a_repeated_column_in_a_template_does_not_ask_for_a_report() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(template(*PASTOR_ROWS, header=[*HEADER, "Cantidad"]))
    assert "repite la columna" in e.value.message_es
    assert "reporte" not in e.value.message_es


def test_an_unreadable_file_message_fits_a_template_too() -> None:
    from mermia_api.ingestion.errors import UnreadableFile

    with pytest.raises(UnreadableFile) as e:
        parse_file(b"PK\x03\x04 not really a zip")
    assert "Envíame el reporte" not in e.value.message_es
    assert "plantilla" in e.value.message_es


@pytest.mark.parametrize(
    ("title", "hint"),
    [
        ("Tacos - El Güero - Todas las sucursales", None),
        ("Taquería El Güero - todas las sucursales", None),
        ("Tacos - El Güero - Centro", "Centro"),
    ],
)
def test_the_location_line_of_a_tenant_wide_template(title: str, hint: str | None) -> None:
    batch = parse_file(template(*PASTOR_ROWS, title=[title, *TITLE[1:]]))
    assert batch.location_hint == hint
