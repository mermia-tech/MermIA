"""MR-15: the "Productos vendidos" parser and the registry that picks it.

Golden test: the synthetic SR export (fixtures/sr/synthetic, MR-12) must parse to its golden
NormalizedBatch. When the pilot's real export arrives (MR-5), add it under fixtures/sr/<version>/
with its golden file and it joins GOLDEN below. Wrong files must raise a ReportError with a Spanish
message, never crash.
"""

import io
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from mermia_api.ingestion.errors import (
    MalformedReport,
    ReportError,
    UnknownReport,
    UnreadableFile,
)
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import NormalizedBatch

SR = Path(__file__).parents[4] / "fixtures" / "sr"
GOLDEN = sorted(SR.glob("*/productos_vendidos_*.xlsx"))

HEADER = ["Clave", "Descripción", "Grupo", "Cantidad", "Precio", "Importe", "Descuento", "Total"]


def xlsx(*rows: list[Any], title: str = "Productos vendidos") -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = title
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def report(*lines: list[Any], total: list[Any] | None = None, header: list[str] = HEADER) -> bytes:
    return xlsx(
        ["Taquería El Güero - Centro"],
        ["Productos vendidos en general"],
        ["Del 11/10/2026 al 11/10/2026"],
        [],
        header,
        *lines,
        total if total is not None else [None, "Total", None, 3, None, 195, 5, 190],
    )


PASTOR = ["P001", "Tacos al pastor (orden de 3)", "Tacos", 2, 65, 130, 5, 125]
COCA = ["P043", "Coca-Cola", "Bebidas", 1, 30, 30, 0, 30]
AGUA = ["P040", "Agua de horchata", "Bebidas", 1, 35, 35, 0, 35]


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_golden(path: Path) -> None:
    golden = path.with_name(path.stem + ".golden.json")
    expected = NormalizedBatch.model_validate_json(golden.read_text())
    assert parse_file(path.read_bytes()) == expected


def test_there_is_a_golden_file() -> None:
    assert GOLDEN, "no Productos vendidos sample under fixtures/sr"


def test_a_small_report() -> None:
    batch = parse_file(report(PASTOR, COCA, AGUA))
    assert batch.parser == "sr.productos_vendidos@v1"
    assert batch.location_hint == "Centro"
    assert (str(batch.period.from_), str(batch.period.to)) == ("2026-10-11", "2026-10-11")
    assert (batch.totals.net_sales, batch.totals.units, batch.totals.lines) == (
        19000,
        Decimal(3),
        3,
    )
    pastor = batch.item_sales[0]
    assert (pastor.units, pastor.gross, pastor.discount, pastor.net) == (
        Decimal(2),
        13000,
        500,
        12500,
    )
    assert [m.category for m in batch.menu_items] == ["Tacos", "Bebidas", "Bebidas"]
    assert batch.issues == []


def test_headers_match_without_accents_or_case() -> None:
    header = [
        "CLAVE",
        "Descripcion",
        "grupo",
        "Cantidad",
        "PRECIO",
        "Importe",
        "Descuento",
        "Total ",
    ]
    assert parse_file(report(PASTOR, COCA, AGUA, header=header)).totals.lines == 3


def test_decimal_pesos_and_quantities_are_exact() -> None:
    line = ["P099", "Carne por kilo", "Extras", 1.5, 189.9, 284.85, 0, 284.85]
    batch = parse_file(report(line, total=[None, "Total", None, 1.5, None, 284.85, 0, 284.85]))
    assert (batch.item_sales[0].units, batch.item_sales[0].net) == (Decimal("1.5"), 28485)


def test_importe_that_is_not_qty_times_price_is_a_warning() -> None:
    line = ["P043", "Coca-Cola", "Bebidas", 2, 30, 50, 0, 50]
    batch = parse_file(report(line, total=[None, "Total", None, 2, None, 50, 0, 50]))
    assert [(i.severity, i.code, i.row_ref) for i in batch.issues] == [
        ("warning", "sr.importe_mismatch", "6")
    ]


def test_location_hint_is_optional() -> None:
    data = xlsx(
        ["Productos vendidos"],
        ["Del 11/10/2026 al 11/10/2026"],
        HEADER,
        COCA,
        [None, "Total", None, 1, None, 30, 0, 30],
    )
    assert parse_file(data).location_hint is None


# --- wrong files: a clear Spanish message, never a crash ----------------------------------


def test_not_an_excel_file() -> None:
    with pytest.raises(UnreadableFile) as e:
        parse_file(b"%PDF-1.7 not a spreadsheet")
    assert "Excel" in e.value.message_es


def test_old_xls_is_named() -> None:
    with pytest.raises(UnreadableFile) as e:
        parse_file(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    assert ".xls" in e.value.message_es


def test_another_sr_report_is_not_recognized() -> None:
    other = next(SR.glob("*/ventas_por_dia_*.xlsx"))
    with pytest.raises(UnknownReport) as e:
        parse_file(other.read_bytes())
    assert "Productos vendidos" in e.value.message_es


def test_a_spreadsheet_without_the_header_is_not_recognized() -> None:
    with pytest.raises(UnknownReport):
        parse_file(xlsx(["Inventario"], ["Clave", "Nombre", "Existencia"], ["A1", "Tortilla", 10]))


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (report(PASTOR, total=[]), "Total"),
        (report(["P001", "Pastor", "Tacos", 2, 65, 130, 5, 130]), "Importe"),
        (report(["P001", None, "Tacos", 2, 65, 130, 5, 125]), "descripción"),
        (report(["P001", "Pastor", "Tacos", 2, 65, 130.001, 0, 130.001]), "dos decimales"),
        (report(["P001", "Pastor", "Tacos", "dos", 65, 130, 0, 130]), "no es un número"),
        (
            xlsx(["Productos vendidos"], HEADER, COCA, [None, "Total", None, 1, None, 30, 0, 30]),
            "periodo",
        ),
        (xlsx(["Productos vendidos"], ["Del 31/02/2026 al 31/02/2026"], HEADER), "fecha"),
    ],
    ids=[
        "no-total-row",
        "total-not-importe-minus-descuento",
        "no-description",
        "three-decimals",
        "text-quantity",
        "no-period",
        "bad-date",
    ],
)
def test_malformed_reports_say_why(data: bytes, fragment: str) -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(data)
    assert fragment in e.value.message_es


def test_every_error_is_a_report_error() -> None:
    for cls in (UnreadableFile, UnknownReport, MalformedReport):
        assert issubclass(cls, ReportError)


# --- damaged or hostile files (skeptic review): still a ReportError -----------------------


def corrupt(part: str, content: bytes) -> bytes:
    src = io.BytesIO(report(PASTOR, COCA, AGUA))
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == part:
                data = content(data) if callable(content) else content
            zout.writestr(item, data)
    return out.getvalue()


@pytest.mark.parametrize(
    ("part", "content"),
    [
        ("xl/workbook.xml", b"<not xml"),
        ("xl/styles.xml", b"<not xml"),
        ("xl/worksheets/sheet1.xml", lambda d: d[: len(d) // 2]),
        ("xl/worksheets/sheet1.xml", lambda d: d.replace(b"<v>130</v>", b"<v>abc</v>", 1)),
    ],
    ids=["workbook-xml", "styles-xml", "truncated-sheet", "bad-numeric-cell"],
)
def test_a_damaged_xlsx_is_unreadable_not_a_crash(part: str, content: Any) -> None:
    with pytest.raises(ReportError):
        parse_file(corrupt(part, content))


@pytest.mark.parametrize(
    "line",
    [
        ["P001", "Pastor", "Tacos", 2, 65, "Infinity", 0, "Infinity"],
        ["P001", "Pastor", "Tacos", 2, 65, "sNaN", 0, "sNaN"],
        ["P001", "Pastor", "Tacos", 1e25, 65, 130, 0, 130],
        ["P001", "Pastor", "Tacos", 1e15, 65, 130, 0, 130],
        ["P001", "Pastor", "Tacos", 2, 65, 1e18, 0, 1e18],
    ],
    ids=["infinity", "snan", "qty-1e25", "qty-1e15", "importe-1e18"],
)
def test_non_finite_or_huge_numbers_are_malformed(line: list[Any]) -> None:
    with pytest.raises(MalformedReport):
        parse_file(report(line))


def test_a_reversed_period_is_malformed() -> None:
    data = xlsx(
        ["Productos vendidos"],
        ["Del 12/10/2026 al 11/10/2026"],
        HEADER,
        COCA,
        [None, "Total", None, 1, None, 30, 0, 30],
    )
    with pytest.raises(MalformedReport) as e:
        parse_file(data)
    assert "periodo" in e.value.message_es


def test_items_after_total_are_not_dropped_silently() -> None:
    data = xlsx(
        ["X - Centro"],
        ["Productos vendidos"],
        ["Del 11/10/2026 al 11/10/2026"],
        HEADER,
        PASTOR,
        [None, "Total", None, 2, None, 130, 5, 125],
        COCA,
        [None, "Total", None, 1, None, 30, 0, 30],
    )
    with pytest.raises(MalformedReport) as e:
        parse_file(data)
    assert "después de la fila" in e.value.message_es


def test_a_text_footer_after_total_is_fine() -> None:
    data = xlsx(
        ["X - Centro"],
        ["Productos vendidos"],
        ["Del 11/10/2026 al 11/10/2026"],
        HEADER,
        COCA,
        [None, "Total", None, 1, None, 30, 0, 30],
        ["Impreso el 12/10/2026 09:00"],
    )
    assert parse_file(data).totals.lines == 1


def test_excel_float_artifacts_are_read_as_excel_shows_them() -> None:
    line = [
        "P099",
        "Carne por kilo",
        "Extras",
        1.5,
        189.9,
        284.84999999999997,
        0,
        284.84999999999997,
    ]
    total = [None, "Total", None, 1.5, None, 284.84999999999997, 0, 284.84999999999997]
    assert parse_file(report(line, total=total)).item_sales[0].net == 28485


def test_an_odd_price_is_only_a_warning() -> None:
    line = ["P043", "Coca-Cola", "Bebidas", 1, 30.125, 30, 0, 30]
    batch = parse_file(report(line, total=[None, "Total", None, 1, None, 30, 0, 30]))
    assert [i.code for i in batch.issues] == ["sr.importe_mismatch"]


def test_an_oversized_file_is_refused_before_reading() -> None:
    with pytest.raises(UnreadableFile) as e:
        parse_file(b"PK" + b"\0" * (10 * 1024 * 1024))
    assert "grande" in e.value.message_es
