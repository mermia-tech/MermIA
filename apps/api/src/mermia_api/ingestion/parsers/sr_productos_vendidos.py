"""Soft Restaurant "Productos vendidos" (items sold) report, xlsx export.

PROVISIONAL layout (01 section 3, SR 8 manual; the pilot's real export decides, MR-5): a title
block ("<restaurant> - <location>", "Productos vendidos ...", "Del dd/mm/yyyy al dd/mm/yyyy"), a
header row Clave | Descripción | Grupo | Cantidad | Precio | Importe | Descuento | Total in
pesos, one row per item, and a closing Total row.

Output: one item_daily batch. Money is centavos; Total = Importe - Descuento is the line's net
(IVA included, fixtures/README.md Definitions). The Total row becomes `totals`, which the loader
checks against the lines (03 B.5). The report has no item kind, so items keep the contract default
and the catalog decides.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import MalformedReport
from mermia_api.ingestion.xlsx import Row, centavos, norm, number, rows, text
from mermia_contracts.batch import (
    Grain,
    IssueIn,
    ItemSalesIn,
    MenuItemIn,
    NormalizedBatch,
    Period,
    Totals,
)
from mermia_contracts.db.models import IssueSeverity, SourceKind

PARSER = "sr.productos_vendidos@v1"
HEADER = ("clave", "descripcion", "grupo", "cantidad", "precio", "importe", "descuento", "total")
TITLE = "productos vendidos"
SEARCH_ROWS = 15  # the header sits in the title block at the top of the sheet
PERIOD = re.compile(r"del\s+(\d{1,2}/\d{1,2}/\d{4})\s+al\s+(\d{1,2}/\d{1,2}/\d{4})")
UNITS = Decimal("0.000001")


def _header_at(sheet_rows: list[Row]) -> int | None:
    for i, row in enumerate(sheet_rows[:SEARCH_ROWS]):
        if tuple(norm(c) for c in row[: len(HEADER)]) == HEADER:
            return i
    return None


def _sheet_name(wb: Workbook) -> str | None:
    """The sheet with the title and header in its first rows (only those rows are read)."""
    for name in wb.sheetnames:
        top = rows(wb, name, max_row=SEARCH_ROWS)
        h = _header_at(top)
        if h is not None and any(TITLE in norm(c) for row in top[:h] for c in row):
            return name
    return None


def matches(wb: Workbook) -> bool:
    return _sheet_name(wb) is not None


def _date(value: str) -> dt.date:
    day, month, year = (int(x) for x in value.split("/"))
    try:
        return dt.date(year, month, day)
    except ValueError as e:
        raise MalformedReport(
            f"La fecha {value} del encabezado no es válida.", f"bad date {value!r}"
        ) from e


def _period(title: list[Row]) -> Period:
    for row in title:
        for cell in row:
            m = PERIOD.search(norm(cell))
            if m:
                start, end = _date(m[1]), _date(m[2])
                if start > end:
                    raise MalformedReport(
                        f"El periodo del reporte empieza ({m[1]}) después de terminar ({m[2]}).",
                        "period from > to",
                    )
                return Period.model_validate({"from": start, "to": end})
    raise MalformedReport(
        "No encontré el periodo del reporte (la línea «Del ... al ...»).",
        "no period line in the title block",
    )


def _location_hint(title: list[Row]) -> str | None:
    """The location after the last " - " of the first title line ("El Güero - Centro")."""
    first = text(title[0][0]) if title and title[0] else None
    if first and " - " in first:
        return first.rsplit(" - ", 1)[1].strip() or None
    return None


def _units(value: object, where: str) -> Decimal:
    units = number(value, where)
    if units != units.quantize(UNITS):
        raise MalformedReport(
            f"La cantidad {value} en {where} tiene más de seis decimales.",
            f"units with more than 6 decimals at {where}",
        )
    return units.quantize(UNITS)


def parse(wb: Workbook) -> NormalizedBatch:
    name = _sheet_name(wb)
    if name is None:  # the registry calls parse only after matches
        raise MalformedReport("El reporte no tiene el formato esperado.", "header not found")
    sheet_rows = rows(wb, name)
    h = _header_at(sheet_rows)
    assert h is not None
    title = sheet_rows[:h]
    period = _period(title)

    items: list[ItemSalesIn] = []
    menu: dict[str, MenuItemIn] = {}
    issues: list[IssueIn] = []
    totals: Totals | None = None
    for n, row in enumerate(sheet_rows[h + 1 :], start=h + 2):
        cells = (*row, *(None,) * len(HEADER))[: len(HEADER)]
        if all(text(c) is None for c in cells):
            continue
        where = f"la fila {n}"
        clave, desc, grupo, cantidad, precio, importe, descuento, total = cells
        if totals is not None:
            # After Total only a text footer may follow ("Impreso el ..."). Numbers there mean
            # more items or another section, which would be loaded silently short.
            if cantidad is not None or total is not None:
                raise MalformedReport(
                    f"Encontré más datos después de la fila «Total» (en {where}). Envíame el "
                    "reporte con una sola tabla de productos.",
                    f"numeric row after Total at row {n}",
                )
            continue
        if norm(clave) == "total" or norm(desc) == "total":
            totals = Totals(
                net_sales=centavos(total, f"la fila Total ({n})"),
                units=_units(cantidad, f"la fila Total ({n})"),
                lines=len(items),
            )
            continue
        name = text(desc)
        if name is None:
            raise MalformedReport(
                f"Falta la descripción del producto en {where}.", f"no description at row {n}"
            )
        gross = centavos(importe, where)
        discount = centavos(descuento or 0, where)
        net = centavos(total, where)
        if net != gross - discount:
            raise MalformedReport(
                f"En {where}, Total ({total}) no es Importe ({importe}) "
                f"menos Descuento ({descuento}).",
                f"total != importe - descuento at row {n}",
            )
        units = _units(cantidad, where)
        try:
            price_off = precio is not None and centavos(precio, where) * units != gross
        except MalformedReport:  # Precio only feeds this check: an odd price is a warning
            price_off = True
        if price_off:
            issues.append(
                IssueIn(
                    severity=IssueSeverity.warning,
                    code="sr.importe_mismatch",
                    message_es=f"En {where}, Cantidad por Precio no coincide con Importe.",
                    row_ref=str(n),
                )
            )
        key = text(clave) or name
        menu.setdefault(key, MenuItemIn(external_id=text(clave), name=name, category=text(grupo)))
        items.append(
            ItemSalesIn(
                item_external_id=text(clave),
                item_name=name,
                period_from=period.from_,
                period_to=period.to,
                units=units,
                gross=gross,
                discount=discount,
                net=net,
            )
        )
    if totals is None:
        raise MalformedReport(
            "El reporte parece incompleto: no encontré la fila «Total».", "no Total row"
        )

    return NormalizedBatch(
        parser=PARSER,
        source_kind=SourceKind.sr_report,
        location_hint=_location_hint(title),
        period=period,
        grain=Grain.item_daily,
        totals=totals,
        menu_items=list(menu.values()),
        item_sales=items,
        issues=issues,
    )
