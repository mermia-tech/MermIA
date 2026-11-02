"""Pieces every Soft Restaurant report shares: the title block and bounded sheet reading.

PROVISIONAL like the layouts themselves (01 section 3, SR 8 manual; MR-5 decides): a title block
of "<restaurant> - <location>", the report name and "Del dd/mm/yyyy al dd/mm/yyyy", then a header
row and one table.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import MalformedReport
from mermia_api.ingestion.xlsx import Row, norm, rows, text
from mermia_contracts.batch import Period

SEARCH_ROWS = 15  # the header sits in the title block at the top of the sheet
DATE = r"(\d{1,2})/(\d{1,2})/(\d{4})"
PERIOD = re.compile(r"del\s+(\d{1,2}/\d{1,2}/\d{4})\s+al\s+(\d{1,2}/\d{1,2}/\d{4})")


def sr_date(value: str, where: str = "del encabezado") -> dt.date:
    """A dd/mm/yyyy date as SR prints it."""
    m = re.fullmatch(DATE, value.strip())
    if m is None:
        raise MalformedReport(
            f"La fecha «{value}» {where} no tiene el formato dd/mm/aaaa.", f"bad date {value!r}"
        )
    day, month, year = (int(x) for x in m.groups())
    try:
        return dt.date(year, month, day)
    except ValueError as e:
        raise MalformedReport(
            f"La fecha {value} {where} no es válida.", f"bad date {value!r}"
        ) from e


def period(title: list[Row]) -> Period:
    """The "Del ... al ..." line of the title block."""
    for row in title:
        for cell in row:
            m = PERIOD.search(norm(cell))
            if m:
                start, end = sr_date(m[1]), sr_date(m[2])
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


def location_hint(title: list[Row]) -> str | None:
    """The location after the last " - " of the first title line ("El Güero - Centro")."""
    first = text(title[0][0]) if title and title[0] else None
    if first and " - " in first:
        return first.rsplit(" - ", 1)[1].strip() or None
    return None


def is_number(value: object) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def has_title(top: list[Row], header_at: int, title: str) -> bool:
    """Whether the report name appears in the rows above the header."""
    return any(title in norm(c) for row in top[:header_at] for c in row)


def read_table(wb: Workbook, sheet: str, header_at: int, max_rows: int) -> list[Row]:
    """The sheet down to at most `max_rows` rows below the header (one more is read to know
    there are too many), so a small zip cannot unpack into a huge sheet."""
    sheet_rows = rows(wb, sheet, max_row=header_at + 1 + max_rows + 1)
    if len(sheet_rows) > header_at + 1 + max_rows:
        raise MalformedReport(
            f"El reporte tiene más de {max_rows:,} renglones; envíame un periodo más corto.",
            f"more than {max_rows} rows below the header",
        )
    return sheet_rows
