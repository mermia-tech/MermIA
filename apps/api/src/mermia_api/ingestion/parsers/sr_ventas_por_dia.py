"""Soft Restaurant "Ventas por día" (sales by day) report, xlsx export.

PROVISIONAL layout (01 section 3, SR 8 manual; the pilot's real export decides, MR-5): the SR
title block (_sr_common), a header row with Fecha and Venta neta plus any of the columns below in
any order, one row per business day, and an optional closing Total row.

Output: one daily batch. Money is centavos. Columns are found by name; a column the report does
not have stays None (an empty payment mix), since "not reported" is not zero. 01 section 3 also
lists courtesies (Cortesías); the contract has no field for them, so that column is ignored like
any other unknown one. The Total row, when present, becomes `totals`, which the loader checks
against the days (03 B.5); without it the totals are the sum of the days.

"Otros" is the sales category (Alimentos, Bebidas, Otros); other payments are "Otras formas de
pago", so the two never share a header.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import MalformedReport
from mermia_api.ingestion.parsers._sr_common import (
    SEARCH_ROWS,
    Line,
    columns,
    has_title,
    location_hint,
    period,
    read_table,
    sr_date,
)
from mermia_api.ingestion.xlsx import Row, centavos, norm, number, rows, text
from mermia_contracts.batch import (
    DailySalesIn,
    Grain,
    IssueIn,
    NormalizedBatch,
    Period,
    Totals,
)
from mermia_contracts.db.models import IssueSeverity, PaymentMethod, SourceKind

PARSER = "sr.ventas_por_dia@v1"
TITLE = "ventas por dia"
MAX_ROWS = 1_000  # almost three years of days; a small zip cannot unpack into a huge sheet
TOTAL_LABELS = frozenset({"total", "totales", "total general"})
MAX_COUNT = 2**31 - 1  # the contract's Count (an int column)

DATE = "fecha"
NET = "venta neta"
DISCOUNTS = "descuentos"
SALES = ("alimentos", "bebidas", "otros")  # their sum minus Descuentos should be Venta neta
PAYMENTS = {
    "efectivo": PaymentMethod.cash,
    "tarjeta": PaymentMethod.card,
    "transferencia": PaymentMethod.transfer,
    "vales": PaymentMethod.voucher,
    "otras formas de pago": PaymentMethod.other,
}
KNOWN = {
    DATE,
    NET,
    DISCOUNTS,
    *SALES,
    *PAYMENTS,
    "cuentas",
    "personas",
    "iva",
    "propinas",
    "cancelaciones",
    "importe cancelado",
}


def _header_at(sheet_rows: list[Row]) -> int | None:
    for i, row in enumerate(sheet_rows[:SEARCH_ROWS]):
        if {DATE, NET} <= {norm(c) for c in row}:
            return i
    return None


def _sheet_name(wb: Workbook) -> str | None:
    """The sheet with the title and header in its first rows (only those rows are read)."""
    for name in wb.sheetnames:
        top = rows(wb, name, max_row=SEARCH_ROWS)
        h = _header_at(top)
        if h is not None and has_title(top, h, TITLE):
            return name
    return None


def matches(wb: Workbook) -> bool:
    return _sheet_name(wb) is not None


def _count(value: Any, where: str) -> int:
    d = number(value, where)
    if d != d.to_integral_value() or not 0 <= d <= MAX_COUNT:
        raise MalformedReport(
            f"En {where} esperaba un número entero (sin decimales ni signo menos) y encontré "
            f"{value}.",
            f"not a count at {where}: {value!r}",
        )
    return int(d)


def _business_date(line: Line) -> dt.date:
    value = line.raw(DATE)
    if isinstance(value, dt.datetime):  # an Excel date cell
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = text(value)
    if s is None:
        raise MalformedReport(f"Falta la fecha en la fila {line.n}.", f"no date at row {line.n}")
    return sr_date(s, f"de la fila {line.n}")


def _has_day_date(line: Line) -> bool:
    """Whether the Fecha cell is a day (a text footer such as "Impreso el ..." is not)."""
    try:
        _business_date(line)
    except MalformedReport:
        return False
    return True


def _warning(code: str, message_es: str, n: int) -> IssueIn:
    return IssueIn(severity=IssueSeverity.warning, code=code, message_es=message_es, row_ref=str(n))


def _checks(line: Line, day: DailySalesIn) -> list[IssueIn]:
    """Warnings, never a rejection: SR may round or leave a category out (MR-5 decides)."""
    issues: list[IssueIn] = []
    sales = [s for s in SALES if line.has(s)]
    if sales:
        try:
            expected: int | None = sum(line.cents(s) or 0 for s in sales) - (day.discounts or 0)
        except MalformedReport:  # these columns only feed this check: an odd value is a warning
            expected = None
        if expected != day.net_sales:
            labels = " + ".join(line.cols[s][1] for s in sales)
            if line.has(DISCOUNTS):
                labels += f" menos {line.cols[DISCOUNTS][1]}"
            issues.append(
                _warning(
                    "sr.ventas_mismatch",
                    f"En la fila {line.n}, {labels} no coincide con Venta neta.",
                    line.n,
                )
            )
    if day.payment_mix and sum(day.payment_mix.values()) != day.net_sales:
        issues.append(
            _warning(
                "sr.payment_mix_mismatch",
                f"En la fila {line.n}, la suma de las formas de pago no coincide con Venta neta.",
                line.n,
            )
        )
    return issues


def _day(line: Line) -> DailySalesIn:
    net = line.cents(NET)
    if net is None:
        raise MalformedReport(
            f"Falta un número en {line.where(NET)}.", f"no Venta neta at row {line.n}"
        )
    mix = {m: line.cents(name) for name, m in PAYMENTS.items()}
    return DailySalesIn(
        business_date=_business_date(line),
        net_sales=net,
        tax=line.cents("iva"),
        tickets=line.read("cuentas", _count),
        guests=line.read("personas", _count),
        discounts=line.cents(DISCOUNTS),
        cancellations_amount=line.cents("importe cancelado"),
        cancellations_count=line.read("cancelaciones", _count),
        payment_mix={m: c for m, c in mix.items() if c is not None},
        tips=line.cents("propinas"),
    )


def _in_period(day: DailySalesIn, n: int, p: Period, seen: dict[dt.date, int]) -> None:
    shown = f"{day.business_date:%d/%m/%Y}"
    if day.business_date in seen:
        raise MalformedReport(
            f"Las filas {seen[day.business_date]} y {n} repiten la fecha {shown}. Envíame el "
            "reporte con una fila por día.",
            f"date {day.business_date} repeated at rows {seen[day.business_date]} and {n}",
        )
    if not p.from_ <= day.business_date <= p.to:
        raise MalformedReport(
            f"La fecha {shown} de la fila {n} está fuera del periodo del reporte "
            f"(del {p.from_:%d/%m/%Y} al {p.to:%d/%m/%Y}).",
            f"date {day.business_date} at row {n} outside the period",
        )


def parse(wb: Workbook) -> NormalizedBatch:
    sheet_name = _sheet_name(wb)
    if sheet_name is None:  # the registry calls parse only after matches
        raise MalformedReport("El reporte no tiene el formato esperado.", "header not found")
    h = _header_at(rows(wb, sheet_name, max_row=SEARCH_ROWS))
    assert h is not None
    sheet_rows = read_table(wb, sheet_name, h, MAX_ROWS)
    title = sheet_rows[:h]
    batch_period = period(title)
    cols = columns(sheet_rows[h], KNOWN)

    days: list[DailySalesIn] = []
    issues: list[IssueIn] = []
    total_net: int | None = None
    seen: dict[dt.date, int] = {}  # business date -> first row, to refuse repeated days
    for n, cells in enumerate(sheet_rows[h + 1 :], start=h + 2):
        if all(text(c) is None for c in cells):
            continue
        line = Line(cells, n, cols)
        if total_net is not None:
            # After Total only a text footer may follow ("Impreso el ..."). A Venta neta or a day
            # date there means more days or another section, which would be loaded silently short.
            if text(line.raw(NET)) is not None or _has_day_date(line):
                raise MalformedReport(
                    f"Encontré más datos después de la fila «Total» (en la fila {n}). Envíame "
                    "el reporte con una sola tabla de días.",
                    f"Venta neta after Total at row {n}",
                )
            continue
        if norm(line.raw(DATE)).rstrip(" :") in TOTAL_LABELS:
            total_net = centavos(line.raw(NET), f"la fila Total ({n})")
            continue
        day = _day(line)
        _in_period(day, n, batch_period, seen)
        seen[day.business_date] = n
        days.append(day)
        issues.extend(_checks(line, day))
    if not days:
        raise MalformedReport(
            "El reporte no tiene ningún día con ventas; revisa el periodo que exportaste.",
            "no day rows",
        )

    net = total_net if total_net is not None else sum(d.net_sales for d in days)
    return NormalizedBatch(
        parser=PARSER,
        source_kind=SourceKind.sr_report,
        location_hint=location_hint(title),
        period=batch_period,
        grain=Grain.daily,
        totals=Totals(net_sales=net, lines=len(days)),
        daily_sales=days,
        issues=issues,
    )
