"""MR-23: the "Recetas" parser (golden file in test_golden.py).

One row per recipe line, grouped by product. Quantities come out in base units (g, ml, pza),
since the MR-25 costing engine does no unit conversion. Wrong files raise a ReportError with a
Spanish message, never crash.
"""

import datetime as dt
import io
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import Workbook

from mermia_api.ingestion.errors import MalformedReport, UnknownReport
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.db.models import IssueSeverity

HEADER = [
    "Clave",
    "Producto",
    "Clave insumo",
    "Insumo",
    "Cantidad",
    "Unidad",
    "Rendimiento %",
    "Costo",
]
PASTOR = "Tacos al pastor (orden de 3)"
TORTILLA = ["P001", PASTOR, "I038", "Tortilla de maíz", 0.075, "KG", 100, 1.65]
MEAT = ["P001", PASTOR, "I001", "Carne al pastor (adobada)", 0.06385, "KG", 92, 13.53]
SALSA = ["P001", PASTOR, "E001", "Salsa verde (preparada)", 30, "GR", None, 0.86]
HORCHATA = ["P050", "Agua de horchata", "I039", "Leche entera", 0.1, "LT", 100, 2.6]


def xlsx(*rows: list[Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Recetas"
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def report(
    *lines: list[Any],
    header: list[str] = HEADER,
    title: str = "Recetas - Productos",
    date: Any = "Al 12/10/2026",
) -> bytes:
    return xlsx(["Taquería El Güero - Centro"], [title], [date], [], header, *lines)


def with_(row: list[Any], column: str, value: Any) -> list[Any]:
    return [value if c == column else v for c, v in zip(HEADER, row, strict=True)]


def test_a_small_report() -> None:
    batch = parse_file(report(TORTILLA, MEAT, SALSA, HORCHATA))
    assert (batch.parser, batch.grain, batch.location_hint) == (
        "sr.recetas@v1",
        "catalog",
        "Centro",
    )
    assert (batch.period.from_, batch.period.to) == (dt.date(2026, 10, 12), dt.date(2026, 10, 12))
    assert (batch.totals.lines, batch.totals.net_sales) == (2, None)
    assert batch.issues == []
    pastor, horchata = batch.recipes
    assert (pastor.menu_item_external_id, pastor.menu_item_name) == ("P001", PASTOR)
    assert pastor.yield_qty == Decimal(1)
    assert [(x.ingredient_external_id, x.ingredient_name) for x in pastor.lines] == [
        ("I038", "Tortilla de maíz"),
        ("I001", "Carne al pastor (adobada)"),
        ("E001", "Salsa verde (preparada)"),
    ]
    assert [x.yield_override_pct for x in pastor.lines] == [Decimal(100), Decimal(92), None]
    assert horchata.lines[0].ingredient_name == "Leche entera"


@pytest.mark.parametrize(
    ("qty", "unit", "base_qty", "base_unit"),
    [
        (0.06385, "KG", "63.85", "g"),
        (2, "kg", "2000", "g"),
        (30, "GR", "30", "g"),
        (12.5, "g", "12.5", "g"),
        (0.25, "LT", "250", "ml"),
        (1, "l", "1000", "ml"),
        (40, "ml", "40", "ml"),
        (1, "PZA", "1", "pza"),
        (2, "pz", "2", "pza"),
        ("0.5", "Kg.", "500", "g"),
    ],
)
def test_units_become_base_units(qty: Any, unit: str, base_qty: str, base_unit: str) -> None:
    row = with_(with_(TORTILLA, "Cantidad", qty), "Unidad", unit)
    (line,) = parse_file(report(row)).recipes[0].lines
    assert (line.qty_base, line.unit) == (Decimal(base_qty), base_unit)


def test_an_unknown_unit_is_an_error_for_review() -> None:
    batch = parse_file(report(TORTILLA, with_(with_(MEAT, "Unidad", "taza"), "Cantidad", 2)))
    (issue,) = batch.issues
    assert (issue.severity, issue.code, issue.row_ref) == (
        IssueSeverity.error,
        "sr.unknown_unit",
        "7",
    )
    assert "«taza»" in issue.message_es
    # the line is kept as written, so the reviewer sees it; it is not converted
    meat = batch.recipes[0].lines[1]
    assert (meat.qty_base, meat.unit) == (Decimal(2), "taza")


@pytest.mark.parametrize("qty", [0, -0.05, "0"])
def test_a_quantity_of_zero_or_less_drops_the_line_and_is_an_error_for_review(qty: Any) -> None:
    batch = parse_file(report(TORTILLA, with_(MEAT, "Cantidad", qty), SALSA))
    (issue,) = batch.issues
    assert (issue.severity, issue.code, issue.row_ref) == (
        IssueSeverity.error,
        "sr.qty_not_positive",
        "7",
    )
    for part in ("fila 7", PASTOR, "Carne al pastor (adobada)"):
        assert part in issue.message_es
    (pastor,) = batch.recipes
    assert [x.ingredient_external_id for x in pastor.lines] == ["I038", "E001"]


def test_a_recipe_whose_every_line_is_dropped_is_not_emitted() -> None:
    batch = parse_file(report(with_(TORTILLA, "Cantidad", 0), HORCHATA))
    assert [r.menu_item_name for r in batch.recipes] == ["Agua de horchata"]
    assert [i.code for i in batch.issues] == ["sr.qty_not_positive"]


@pytest.mark.parametrize("qty", [None, "un poco"])
def test_a_missing_or_bad_quantity_is_refused(qty: Any) -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, with_(MEAT, "Cantidad", qty)))
    assert "fila 7" in e.value.message_es


def test_a_quantity_that_rounds_to_zero_is_refused() -> None:
    # 0.0000000001 kg is 0.0000001 g: zero at the contract's six decimals
    with pytest.raises(MalformedReport) as e:
        parse_file(report(with_(TORTILLA, "Cantidad", "0.0000000001")))
    assert "demasiado pequeña" in e.value.message_es


@pytest.mark.parametrize(
    ("qty", "unit", "base_qty"),
    [
        ("0.3333333333", "KG", "333.333333"),
        ("0.12345675", "g", "0.123457"),  # half-up, not half-even
        ("0.0000005", "g", "0.000001"),
    ],
    ids=["third-of-a-kilo", "half-up", "smallest"],
)
def test_a_quantity_finer_than_the_contract_is_rounded(qty: str, unit: str, base_qty: str) -> None:
    row = with_(with_(TORTILLA, "Cantidad", qty), "Unidad", unit)
    (line,) = parse_file(report(row)).recipes[0].lines
    assert line.qty_base == Decimal(base_qty)


def test_a_missing_unit_is_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(with_(TORTILLA, "Unidad", None)))
    assert "unidad" in e.value.message_es


def test_a_repeated_ingredient_in_one_recipe_is_refused() -> None:
    again = with_(MEAT, "Cantidad", 0.01)
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, MEAT, again))
    assert "7 y 8" in e.value.message_es


def test_the_same_ingredient_in_two_recipes_is_fine() -> None:
    other = ["P002", "Tacos de bistec (orden de 3)", *TORTILLA[2:]]
    batch = parse_file(report(TORTILLA, other))
    assert [r.menu_item_external_id for r in batch.recipes] == ["P001", "P002"]


def test_rows_are_grouped_by_product_in_order_of_first_appearance() -> None:
    batch = parse_file(report(TORTILLA, HORCHATA, MEAT))
    assert [r.menu_item_external_id for r in batch.recipes] == ["P001", "P050"]
    assert [x.ingredient_external_id for x in batch.recipes[0].lines] == ["I038", "I001"]


def test_one_code_with_two_product_names_is_refused() -> None:
    renamed = with_(MEAT, "Producto", "Tacos de pastor")
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, renamed))
    assert "P001" in e.value.message_es


def test_products_without_a_code_are_grouped_by_name() -> None:
    batch = parse_file(report(with_(TORTILLA, "Clave", None), with_(MEAT, "Clave", None)))
    (recipe,) = batch.recipes
    assert (recipe.menu_item_external_id, len(recipe.lines)) == (None, 2)


def test_costo_is_read_past() -> None:
    plain = parse_file(report(TORTILLA, MEAT))
    assert parse_file(report(with_(TORTILLA, "Costo", 999.99), with_(MEAT, "Costo", None))) == plain
    assert parse_file(report(with_(TORTILLA, "Costo", "n/d"), MEAT)) == plain
    no_cost = [h for h in HEADER if h != "Costo"]
    assert parse_file(report(TORTILLA[:-1], MEAT[:-1], header=no_cost)) == plain


def test_optional_columns_may_be_missing() -> None:
    header = ["Producto", "Insumo", "Cantidad", "Unidad"]
    batch = parse_file(report([PASTOR, "Tortilla de maíz", 0.075, "KG"], header=header))
    (line,) = batch.recipes[0].lines
    assert batch.recipes[0].menu_item_external_id is None
    assert (line.ingredient_external_id, line.yield_override_pct) == (None, None)


def test_columns_are_found_by_name_in_any_order() -> None:
    order = [4, 5, 3, 1, 0, 2, 6, 7]
    batch = parse_file(report([TORTILLA[i] for i in order], header=[HEADER[i] for i in order]))
    assert batch == parse_file(report(TORTILLA))


@pytest.mark.parametrize("value", [0, -5, 1000, "0.00001", "999.99995", "mucho"])
def test_a_bad_yield_is_refused(value: Any) -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(with_(MEAT, "Rendimiento %", value)))
    assert "fila 6" in e.value.message_es


@pytest.mark.parametrize("value", [0.92, 1])
def test_a_yield_that_looks_like_a_fraction_is_an_error_for_review(value: Any) -> None:
    batch = parse_file(report(with_(MEAT, "Rendimiento %", value)))
    (issue,) = batch.issues
    assert (issue.severity, issue.code) == (IssueSeverity.error, "sr.yield_implausible")
    assert batch.recipes[0].lines[0].yield_override_pct == Decimal(str(value))


@pytest.mark.parametrize(
    "date",
    [
        "Al 12/10/2026",
        "Fecha: 12/10/2026",
        "Del 01/10/2026 al 12/10/2026",
        dt.datetime(2026, 10, 12, 8, 30),
    ],
)
def test_the_date_line_gives_a_one_day_period(date: Any) -> None:
    batch = parse_file(report(TORTILLA, date=date))
    assert (batch.period.from_, batch.period.to) == (dt.date(2026, 10, 12), dt.date(2026, 10, 12))


def test_a_missing_date_is_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, date=""))
    assert "fecha" in e.value.message_es


def test_a_bad_date_is_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, date="Al 31/02/2026"))
    assert "31/02/2026" in e.value.message_es


def test_a_report_without_recipes_is_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report())
    assert "ninguna receta" in e.value.message_es


def test_blank_rows_and_a_text_footer_are_skipped() -> None:
    footer = ["Impreso el 12/10/2026 08:30", None, None, None, None, None, None, None]
    batch = parse_file(report(TORTILLA, [], MEAT, [], footer))
    assert len(batch.recipes[0].lines) == 2


def test_a_line_without_a_product_or_an_ingredient_is_refused() -> None:
    for column in ("Producto", "Insumo"):
        with pytest.raises(MalformedReport) as e:
            parse_file(report(TORTILLA, with_(MEAT, column, None)))
        assert "fila 7" in e.value.message_es, column


def test_a_repeated_column_is_refused() -> None:
    with pytest.raises(MalformedReport):
        parse_file(report([*TORTILLA, "KG"], header=[*HEADER, "Unidad"]))


@pytest.mark.parametrize("title", ["Recetas - Productos", "Recetas \u2013 Productos", "Recetas"])
def test_title_variants_are_recognized(title: str) -> None:
    assert parse_file(report(TORTILLA, title=title)).parser == "sr.recetas@v1"


@pytest.mark.parametrize("title", ["Recetas - Insumos elaborados", "Explosión de insumos"])
def test_another_title_is_not_recognized(title: str) -> None:
    with pytest.raises(UnknownReport) as e:
        parse_file(report(TORTILLA, title=title))
    assert "«Recetas»" in e.value.message_es


def test_a_header_without_the_required_columns_is_not_recognized() -> None:
    header = ["Clave", "Producto", "Insumo", "Cantidad"]  # no Unidad
    with pytest.raises(UnknownReport):
        parse_file(report(TORTILLA[:2] + TORTILLA[3:5], header=header))


def test_a_sheet_with_too_many_rows_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from mermia_api.ingestion.parsers import sr_recetas

    monkeypatch.setattr(sr_recetas, "MAX_ROWS", 1)
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, MEAT))
    assert "renglones" in e.value.message_es


# --- review on #73 ---------------------------------------------------------------------------


def test_a_product_with_and_without_a_code_is_one_recipe() -> None:
    batch = parse_file(report(with_(TORTILLA, "Clave", None), MEAT, with_(SALSA, "Clave", None)))
    (recipe,) = batch.recipes
    assert (recipe.menu_item_external_id, recipe.menu_item_name) == ("P001", PASTOR)
    assert len(recipe.lines) == 3


def test_a_product_name_in_another_case_is_the_same_recipe() -> None:
    upper = with_(with_(MEAT, "Producto", PASTOR.upper()), "Clave", None)
    (recipe,) = parse_file(report(TORTILLA, upper)).recipes
    assert (recipe.menu_item_name, len(recipe.lines)) == (PASTOR, 2)


def test_one_code_with_two_names_is_refused_when_a_codeless_row_comes_between() -> None:
    renamed = with_(SALSA, "Producto", "Tacos de pastor")
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, with_(MEAT, "Clave", None), renamed))
    assert "P001" in e.value.message_es


@pytest.mark.parametrize(
    "header", ["Rendimiento", "Rendimiento (%)", "% Rendimiento", "Rendimiento%", "RENDIMIENTO"]
)
def test_yield_header_variants_are_read(header: str) -> None:
    headers = [header if h == "Rendimiento %" else h for h in HEADER]
    batch = parse_file(report(TORTILLA, MEAT, header=headers))
    assert [x.yield_override_pct for x in batch.recipes[0].lines] == [Decimal(100), Decimal(92)]
    assert batch.issues == []


@pytest.mark.parametrize("header", ["Clave del insumo", "Clave de insumo"])
def test_ingredient_code_header_variants_are_read(header: str) -> None:
    headers = [header if h == "Clave insumo" else h for h in HEADER]
    batch = parse_file(report(TORTILLA, header=headers))
    assert batch.recipes[0].lines[0].ingredient_external_id == "I038"


def test_an_unknown_yield_header_is_a_warning() -> None:
    headers = ["Rendimiento neto" if h == "Rendimiento %" else h for h in HEADER]
    batch = parse_file(report(TORTILLA, header=headers))
    (issue,) = batch.issues
    assert (issue.severity, issue.code, issue.row_ref) == (
        IssueSeverity.warning,
        "sr.unknown_yield_column",
        "5",
    )
    assert "«Rendimiento neto»" in issue.message_es
    assert batch.recipes[0].lines[0].yield_override_pct is None


def test_two_yield_columns_are_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report([*TORTILLA, 100], header=[*HEADER, "Rendimiento"]))
    assert "repite la columna" in e.value.message_es


@pytest.mark.parametrize(
    ("second", "rows"),
    [
        (with_(with_(MEAT, "Insumo", "Tortilla de maíz"), "Clave insumo", None), "6 y 7"),
        (with_(with_(MEAT, "Insumo", "TORTILLA DE MAIZ"), "Clave insumo", "I099"), "6 y 7"),
        (with_(with_(MEAT, "Insumo", "Tortilla"), "Clave insumo", "I038"), "6 y 7"),
    ],
    ids=["with-and-without-code", "case-and-accents", "same-code-other-name"],
)
def test_a_repeated_ingredient_is_found_by_code_or_name(second: list[Any], rows: str) -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, second))
    assert rows in e.value.message_es


@pytest.mark.parametrize(
    ("unit", "base_qty", "base_unit"),
    [
        ("kilo", "2000", "g"),
        ("Kilos", "2000", "g"),
        ("kilogramo", "2000", "g"),
        ("KILOGRAMOS.", "2000", "g"),
        ("gramo", "2", "g"),
        ("Gramos", "2", "g"),
        ("litro", "2000", "ml"),
        ("Litros.", "2000", "ml"),
        ("mililitro", "2", "ml"),
        ("Mililitros", "2", "ml"),
        ("pieza", "2", "pza"),
        ("Piezas", "2", "pza"),
    ],
)
def test_spelled_out_units_become_base_units(unit: str, base_qty: str, base_unit: str) -> None:
    row = with_(with_(TORTILLA, "Cantidad", 2), "Unidad", unit)
    (line,) = parse_file(report(row)).recipes[0].lines
    assert (line.qty_base, line.unit) == (Decimal(base_qty), base_unit)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("92.592592592", "92.5926"), ("92.12345", "92.1235"), ("99.99995", "100.0000")],
)
def test_a_yield_finer_than_the_contract_is_rounded_half_up(value: str, expected: str) -> None:
    (line,) = parse_file(report(with_(MEAT, "Rendimiento %", value))).recipes[0].lines
    assert line.yield_override_pct == Decimal(expected)


def test_a_printed_on_line_does_not_set_the_report_date() -> None:
    data = xlsx(
        ["Taquería El Güero - Centro"],
        ["Impreso el 30/10/2026 09:15"],
        ["Recetas - Productos"],
        ["Al 12/10/2026"],
        [],
        HEADER,
        TORTILLA,
    )
    batch = parse_file(data)
    assert (batch.period.from_, batch.period.to) == (dt.date(2026, 10, 12), dt.date(2026, 10, 12))


@pytest.mark.parametrize("printed", ["Impresión: 30/10/2026", "Fecha de impresión 30/10/2026"])
def test_a_title_block_with_only_a_printed_on_date_is_refused(printed: str) -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(TORTILLA, date=printed))
    assert "fecha" in e.value.message_es


def test_a_dated_line_is_preferred_over_a_bare_date() -> None:
    data = xlsx(
        ["Taquería El Güero - Centro", dt.datetime(2026, 10, 30, 9, 15)],
        ["Recetas - Productos"],
        ["Fecha: 12/10/2026"],
        HEADER,
        TORTILLA,
    )
    assert parse_file(data).period.from_ == dt.date(2026, 10, 12)


def test_a_repeated_costo_column_is_read_past() -> None:
    batch = parse_file(report([*TORTILLA, 1.65], header=[*HEADER, "Costo"]))
    assert batch == parse_file(report(TORTILLA))


# --- skeptic pass on #73: one name under two claves, implausible quantities -----------------

LARGE = ["P051", "Agua de horchata", "I039", "Leche entera", 0.2, "LT", 100, 5.2]
RICE = ["P050", "Agua de horchata", "I040", "Arroz", 0.03, "KG", 100, 0.9]


def test_one_product_name_with_two_codes_is_two_recipes() -> None:
    batch = parse_file(report(HORCHATA, LARGE, RICE))
    assert [(r.menu_item_external_id, len(r.lines)) for r in batch.recipes] == [
        ("P050", 2),
        ("P051", 1),
    ]
    assert batch.issues == []


def test_a_codeless_row_joins_the_one_code_its_name_has_wherever_it_comes() -> None:
    codeless = with_(RICE, "Clave", None)
    batch = parse_file(report(codeless, HORCHATA))
    (recipe,) = batch.recipes
    assert (recipe.menu_item_external_id, len(recipe.lines)) == ("P050", 2)


def test_a_codeless_row_whose_name_has_two_codes_is_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(HORCHATA, LARGE, with_(RICE, "Clave", None)))
    message = e.value.message_es
    assert all(s in message for s in ("fila 8", "«Agua de horchata»", "P050", "P051"))


def test_a_repeated_ingredient_under_two_codes_of_one_name_is_fine() -> None:
    # LARGE repeats HORCHATA's ingredient, in another recipe (P051)
    assert len(parse_file(report(HORCHATA, LARGE)).recipes) == 2


def test_a_repeated_ingredient_in_a_codeless_row_of_a_coded_recipe_is_refused() -> None:
    again = with_(with_(HORCHATA, "Clave", None), "Cantidad", 0.2)
    with pytest.raises(MalformedReport) as e:
        parse_file(report(HORCHATA, again))
    assert "6 y 7" in e.value.message_es


@pytest.mark.parametrize(
    ("qty", "unit"),
    [("1,500", "KG"), (1000, "LT"), (1000000, "GR"), (1000, "PZA")],
)
def test_an_implausible_quantity_is_an_error_for_review(qty: Any, unit: str) -> None:
    batch = parse_file(report(TORTILLA, with_(with_(MEAT, "Cantidad", qty), "Unidad", unit)))
    (issue,) = batch.issues
    assert (issue.severity, issue.code, issue.row_ref) == (
        IssueSeverity.error,
        "sr.qty_implausible",
        "7",
    )
    assert f"{qty} {unit}" in issue.message_es


@pytest.mark.parametrize(
    ("qty", "unit"), [(999.999999, "KG"), (999, "LT"), (999999, "ML"), (999, "PZA")]
)
def test_a_large_but_plausible_quantity_is_not_flagged(qty: Any, unit: str) -> None:
    batch = parse_file(report(TORTILLA, with_(with_(MEAT, "Cantidad", qty), "Unidad", unit)))
    assert batch.issues == []


def test_a_product_row_with_no_recipe_lines_is_a_warning() -> None:
    bare = ["P077", "Café de olla", None, None, None, None, None, None]
    batch = parse_file(report(TORTILLA, bare))
    (issue,) = batch.issues
    assert (issue.severity, issue.code, issue.row_ref) == (
        IssueSeverity.warning,
        "sr.recipe_empty",
        "7",
    )
    assert "Café de olla" in issue.message_es
    assert [r.menu_item_name for r in batch.recipes] == [PASTOR]


def test_a_product_header_row_before_its_ingredients_is_not_a_warning() -> None:
    header_line = ["P001", PASTOR, None, None, None, None, None, None]
    batch = parse_file(report(header_line, TORTILLA, MEAT))
    assert batch.issues == []
    assert len(batch.recipes[0].lines) == 2
