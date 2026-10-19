"""Parser registry: picks the parser for a file by fingerprint (09 section 3, D2).

A parser is a pure function from file bytes to one NormalizedBatch. Transports (WhatsApp, email,
push) call `parse_file` and never a parser directly, so a new report type only needs a new entry
here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import UnknownReport
from mermia_api.ingestion.parsers import sr_productos_vendidos
from mermia_api.ingestion.xlsx import open_workbook
from mermia_contracts.batch import NormalizedBatch


@dataclass(frozen=True)
class XlsxParser:
    name: str  # the batch's `parser`, e.g. "sr.productos_vendidos@v1"
    report_es: str  # how the manager calls the report
    matches: Callable[[Workbook], bool]
    parse: Callable[[Workbook], NormalizedBatch]


XLSX_PARSERS: tuple[XlsxParser, ...] = (
    XlsxParser(
        sr_productos_vendidos.PARSER,
        "Productos vendidos",
        sr_productos_vendidos.matches,
        sr_productos_vendidos.parse,
    ),
)


def parse_file(data: bytes) -> NormalizedBatch:
    """The NormalizedBatch for an SR export. Raises a ReportError (with a Spanish message) when
    the file cannot be read, matches no parser, or does not add up."""
    wb = open_workbook(data)
    try:
        for parser in XLSX_PARSERS:
            if parser.matches(wb):
                return parser.parse(wb)
    finally:
        wb.close()
    known = ", ".join(f"«{p.report_es}»" for p in XLSX_PARSERS)
    raise UnknownReport(
        f"No reconocí este reporte. Por ahora puedo leer: {known} de Soft Restaurant.",
        "no parser fingerprint matched",
    )
