"""MR-23: the "Ventas por día" parser (golden file in test_golden.py).

Columns are found by name; a column the report does not have stays None ("not reported" is not
zero). Wrong files raise a ReportError with a Spanish message, never crash.
"""

import datetime as dt
import io
from typing import Any

import pytest
from openpyxl import Workbook

from mermia_api.ingestion.errors import MalformedReport, UnknownReport
from mermia_api.ingestion.registry import parse_file

HEADER = [
    "Fecha",
    "Cuentas",
    "Personas",
    "Alimentos",
    "Bebidas",
    "Descuentos",
    "Venta neta",
    "IVA",
    "Propinas",
    "Efectivo",
    "Tarjeta",
    "Transferencia",
    "Cancelaciones",
    "Importe cancelado",
]
MON = ["05/10/2026", 63, 142, 1381, 412, 0, 1793, 247.31, 83.2, 627.5, 1039.9, 125.6, 0, 0]
TUE = [
    "06/10/2026",
    68,
    148,
    1561.5,
    453.5,
    40.95,
    1974.05,
    272.28,
    91.6,
    690,
    1144,
    140.05,
    2,
    240,
]


def xlsx(*rows: list[Any], title: str = "Ventas por día") -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = title
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def report(
    *days: list[Any],
    header: list[str] = HEADER,
    period: str = "Del 05/10/2026 al 11/10/2026",
) -> bytes:
    return xlsx(["Taquería El Güero - Centro"], ["Ventas por día"], [period], [], header, *days)


def only(columns: list[str], row: list[Any]) -> list[Any]:
    return [row[HEADER.index(c)] for c in columns]


def test_a_small_report() -> None:
    batch = parse_file(report(MON, TUE))
    assert (batch.parser, batch.grain, batch.location_hint) == (
        "sr.ventas_por_dia@v1",
        "daily",
        "Centro",
    )
    assert (str(batch.period.from_), str(batch.period.to)) == ("2026-10-05", "2026-10-11")
    assert (batch.totals.net_sales, batch.totals.units, batch.totals.lines) == (376705, None, 2)
    tue = batch.daily_sales[1]
    assert tue.business_date == dt.date(2026, 10, 6)
    assert (tue.net_sales, tue.tax, tue.tickets, tue.guests, tue.discounts, tue.tips) == (
        197405,
        27228,
        68,
        148,
        4095,
        9160,
    )
    assert (tue.cancellations_count, tue.cancellations_amount) == (2, 24000)
    assert tue.payment_mix == {"cash": 69000, "card": 114400, "transfer": 14005}
    assert batch.issues == []


def test_columns_are_found_by_name_in_any_order() -> None:
    header = ["Venta neta", "fecha", "PROPINAS", "Tarjeta", "Efectivo"]
    row = [1793, "05/10/2026", 83.2, 1000, 793]
    day = parse_file(report(row, header=header)).daily_sales[0]
    assert (day.net_sales, day.tips, day.payment_mix) == (
        179300,
        8320,
        {"card": 100000, "cash": 79300},
    )


def test_missing_optional_columns_are_not_reported_not_zero() -> None:
    day = parse_file(report(["05/10/2026", 1793], header=["Fecha", "Venta neta"])).daily_sales[0]
    assert day.net_sales == 179300
    assert (day.tax, day.tickets, day.guests, day.discounts, day.tips) == (None,) * 5
    assert (day.cancellations_amount, day.cancellations_count, day.payment_mix) == (None, None, {})


def test_a_blank_optional_cell_is_not_reported() -> None:
    row = [*MON[:7], None, *MON[8:]]
    assert parse_file(report(row)).daily_sales[0].tax is None


def test_vales_and_other_payments_go_to_the_payment_mix() -> None:
    header = ["Fecha", "Venta neta", "Efectivo", "Vales", "Otras formas de pago"]
    day = parse_file(report(["05/10/2026", 100, 50, 30, 20], header=header)).daily_sales[0]
    assert day.payment_mix == {"cash": 5000, "voucher": 3000, "other": 2000}


def test_otros_is_a_sales_category_and_counts_in_the_check() -> None:
    header = ["Fecha", "Alimentos", "Bebidas", "Otros", "Venta neta"]
    batch = parse_file(report(["05/10/2026", 60, 30, 10, 100], header=header))
    assert batch.daily_sales[0].payment_mix == {}
    assert batch.issues == []


def test_excel_date_cells_are_read() -> None:
    rows = [[dt.datetime(2026, 10, 5), 100], [dt.date(2026, 10, 6), 200]]
    batch = parse_file(report(*rows, header=["Fecha", "Venta neta"]))
    assert [d.business_date for d in batch.daily_sales] == [
        dt.date(2026, 10, 5),
        dt.date(2026, 10, 6),
    ]


def test_without_a_total_row_totals_are_the_sum_of_the_days() -> None:
    assert parse_file(report(MON, TUE)).totals.net_sales == 179300 + 197405


def test_a_total_row_that_matches_becomes_totals() -> None:
    total = ["Total", 131, 290, 2942.5, 865.5, 40.95, 3767.05]
    batch = parse_file(report(MON, TUE, total))
    assert (batch.totals.net_sales, batch.totals.lines) == (376705, 2)
    assert len(batch.daily_sales) == 2


@pytest.mark.parametrize("label", ["Totales", "Total general", "TOTAL GENERAL"])
def test_total_row_label_variants(label: str) -> None:
    batch = parse_file(report(MON, TUE, [label, 131, 290, 2942.5, 865.5, 40.95, 3767.05]))
    assert (batch.totals.net_sales, batch.totals.lines) == (376705, 2)


def test_a_whitespace_cell_in_a_footer_after_total_is_fine() -> None:
    batch = parse_file(report(MON, ["Total", *MON[1:]], ["Impreso el 12/10/2026", *["  "] * 6]))
    assert batch.totals.lines == 1


def test_a_total_row_that_does_not_match_is_kept_for_the_loader_to_reject() -> None:
    total = ["Total", None, None, None, None, None, 4000]
    batch = parse_file(report(MON, TUE, total))
    assert (batch.totals.net_sales, batch.totals.lines) == (400000, 2)


def test_a_text_footer_after_total_is_fine() -> None:
    batch = parse_file(report(MON, ["Total", *MON[1:]], ["Impreso el 12/10/2026 09:00"]))
    assert batch.totals.lines == 1


def test_days_after_total_are_not_dropped_silently() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(MON, ["Total", *MON[1:]], TUE))
    assert "después de la fila" in e.value.message_es


def test_food_and_drinks_minus_discounts_off_net_is_a_warning() -> None:
    row = [*MON[:6], 1800, *MON[7:]]  # Venta neta 1800 instead of 1793
    row[9] = 634.5  # keep the payment mix on 1800
    batch = parse_file(report(row))
    assert [(i.severity, i.code, i.row_ref) for i in batch.issues] == [
        ("warning", "sr.ventas_mismatch", "6")
    ]
    assert batch.daily_sales[0].net_sales == 180000


def test_an_odd_food_amount_is_only_a_warning() -> None:
    row = [*MON[:3], "n/d", *MON[4:]]
    assert [i.code for i in parse_file(report(row)).issues] == ["sr.ventas_mismatch"]


def test_a_payment_mix_off_net_is_a_warning() -> None:
    row = [*MON[:9], 600, *MON[10:]]
    batch = parse_file(report(row))
    assert [(i.severity, i.code, i.row_ref) for i in batch.issues] == [
        ("warning", "sr.payment_mix_mismatch", "6")
    ]


# --- wrong files: a clear Spanish message, never a crash ----------------------------------


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (report(MON, MON), "Las filas 6 y 7 repiten la fecha 05/10/2026"),
        (report(["12/10/2026", *MON[1:]]), "fuera del periodo"),
        (report(["31/02/2026", *MON[1:]]), "no es válida"),
        (report(["el lunes", *MON[1:]]), "dd/mm/aaaa"),
        (report([None, *MON[1:]]), "fecha"),
        (report([*MON[:6], None, *MON[7:]]), "Venta neta"),
        (report([*MON[:6], 1793.001, *MON[7:]]), "dos decimales"),
        (report([MON[0], 63.5, *MON[2:]]), "entero"),
        (report([MON[0], -1, *MON[2:]]), "entero"),
        (report(MON, header=[*HEADER[:-1], "Efectivo"]), "repite la columna"),
        (report(header=HEADER), "ningún día"),
        (report(MON, period="Semana 41"), "periodo"),
    ],
    ids=[
        "duplicate-date",
        "date-outside-period",
        "bad-date",
        "text-date",
        "no-date",
        "no-venta-neta",
        "three-decimals",
        "fractional-count",
        "negative-count",
        "repeated-column",
        "no-days",
        "no-period",
    ],
)
def test_malformed_reports_say_why(data: bytes, fragment: str) -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(data)
    assert fragment in e.value.message_es


@pytest.mark.parametrize(
    "header",
    [
        ["Fecha", "Cuentas", "Personas"],  # no Venta neta
        ["Día", "Venta neta"],  # no Fecha
    ],
    ids=["no-venta-neta", "no-fecha"],
)
def test_a_header_without_the_required_columns_is_not_recognized(header: list[str]) -> None:
    with pytest.raises(UnknownReport):
        parse_file(report(["05/10/2026", 1793], header=header))


def test_another_title_is_not_recognized() -> None:
    data = xlsx(["X - Centro"], ["Formas de pago"], ["Del 05/10/2026 al 11/10/2026"], HEADER, MON)
    with pytest.raises(UnknownReport) as e:
        parse_file(data)
    assert "Ventas por día" in e.value.message_es


@pytest.mark.parametrize("name", ["Ventas por día por mesero", "Ventas por día por forma de pago"])
def test_a_longer_report_name_is_not_recognized(name: str) -> None:
    data = xlsx(["X - Centro"], [name], ["Del 05/10/2026 al 11/10/2026"], HEADER, MON)
    with pytest.raises(UnknownReport):
        parse_file(data)


def test_a_sheet_with_too_many_rows_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from mermia_api.ingestion.parsers import sr_ventas_por_dia

    monkeypatch.setattr(sr_ventas_por_dia, "MAX_ROWS", 1)
    with pytest.raises(MalformedReport) as e:
        parse_file(report(MON, TUE))
    assert "renglones" in e.value.message_es


@pytest.mark.parametrize("label", ["Total:", "TOTAL:", "Totales:", "Total general :"])
def test_a_total_label_with_a_trailing_colon_is_a_total(label: str) -> None:
    batch = parse_file(report(MON, TUE, [label, 131, 290, 2942.5, 865.5, 40.95, 3767.05]))
    assert (batch.totals.net_sales, batch.totals.lines) == (376705, 2)


def test_a_dated_row_with_a_blank_net_after_total_is_refused() -> None:
    blank_net = [*TUE[:6], None, *TUE[7:]]
    with pytest.raises(MalformedReport) as e:
        parse_file(report(MON, ["Total", *MON[1:]], blank_net))
    assert "después de la fila" in e.value.message_es


# --- review on #72: footers without a Total row, a Total row without a number ---------------


@pytest.mark.parametrize(
    "footer",
    [["Impreso el 12/10/2026 09:00"], ["Página 1 de 1", None, None, None, None, None, "  "]],
    ids=["printed-on", "page-number"],
)
def test_a_text_footer_without_a_total_row_is_skipped(footer: list[Any]) -> None:
    batch = parse_file(report(MON, TUE, footer))
    assert (batch.totals.net_sales, batch.totals.lines) == (376705, 2)
    assert batch.issues == []


def test_a_dated_row_with_a_blank_net_before_total_is_still_refused() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(MON, [*TUE[:6], None, *TUE[7:]]))
    assert "Venta neta" in e.value.message_es


def test_a_total_row_with_a_blank_net_counts_as_no_total_row() -> None:
    batch = parse_file(report(MON, TUE, ["Total", 131, 290, 2942.5, 865.5, 40.95, None]))
    assert (batch.totals.net_sales, batch.totals.lines) == (376705, 2)


def test_days_after_a_total_row_with_a_blank_net_are_not_dropped_silently() -> None:
    with pytest.raises(MalformedReport) as e:
        parse_file(report(MON, ["Total", *MON[1:6], None], TUE))
    assert "después de la fila" in e.value.message_es
