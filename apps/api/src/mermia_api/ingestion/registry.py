"""Parser registry: picks the parser for a file by fingerprint (09 section 3, D2).

A parser is a pure function from file bytes to one NormalizedBatch. Transports (WhatsApp, email,
push) call `parse_file` and never a parser directly, so a new report type only needs a new entry
here. A file that starts like XML (a CFDI invoice) goes to the XML parsers; anything else is opened
as an Excel workbook.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import ReportError, UnknownReport, UnreadableFile
from mermia_api.ingestion.parsers import (
    cfdi_factura,
    mermia_recetas,
    sr_productos_vendidos,
    sr_recetas,
    sr_ventas_por_dia,
)
from mermia_api.ingestion.xlsx import open_workbook
from mermia_api.ingestion.xmldoc import SR_HINT, looks_like_xml, parse_xml
from mermia_contracts.batch import NormalizedBatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class XlsxParser:
    name: str  # the batch's `parser`, e.g. "sr.productos_vendidos@v1"
    report_es: str  # how the manager calls the report
    matches: Callable[[Workbook], bool]
    parse: Callable[[Workbook], NormalizedBatch]
    from_sr: bool = True  # a Soft Restaurant report, or a file of ours (the recipe template)


# the template first: its title and Platillo header never appear in an SR report
XLSX_PARSERS: tuple[XlsxParser, ...] = (
    XlsxParser(
        mermia_recetas.PARSER,
        "la plantilla de recetas de MermIA",
        mermia_recetas.matches,
        mermia_recetas.parse,
        from_sr=False,
    ),
    XlsxParser(
        sr_productos_vendidos.PARSER,
        "Productos vendidos",
        sr_productos_vendidos.matches,
        sr_productos_vendidos.parse,
    ),
    XlsxParser(
        sr_ventas_por_dia.PARSER,
        "Ventas por día",
        sr_ventas_por_dia.matches,
        sr_ventas_por_dia.parse,
    ),
    XlsxParser(sr_recetas.PARSER, "Recetas", sr_recetas.matches, sr_recetas.parse),
)


@dataclass(frozen=True)
class XmlParser:
    name: str  # the batch's `parser`, e.g. "cfdi.factura@v1"
    doc_es: str  # how the manager calls the document, after "puedo leer ... o"
    matches: Callable[[Element], bool]
    parse: Callable[[Element], NormalizedBatch]


XML_PARSERS: tuple[XmlParser, ...] = (
    XmlParser(
        cfdi_factura.PARSER,
        "una factura CFDI en XML",
        cfdi_factura.matches,
        cfdi_factura.parse,
    ),
)


def parse_file(data: bytes) -> NormalizedBatch:
    """The NormalizedBatch for an SR export, a MermIA template or a CFDI invoice. Raises a
    ReportError (with a Spanish message) when the file cannot be read, matches no parser, or does
    not add up."""
    if looks_like_xml(data):
        return _parse_xml(data)
    return _parse_xlsx(data)


@contextmanager
def _unexpected_as_unreadable(message_es: str) -> Iterator[None]:
    """A ReportError passes through; anything else becomes an UnreadableFile. A damaged file
    (corrupt sheet XML, bad cell values) fails inside openpyxl while sheets are read lazily, or a
    value breaks a contract limit: never a crash, always a message. It may also be a bug of ours,
    so it is logged with its traceback."""
    try:
        yield
    except ReportError:
        raise
    except Exception as e:
        logger.exception("parse_file: unexpected %s, reported as unreadable", type(e).__name__)
        raise UnreadableFile(message_es, f"{type(e).__name__}: {e}") from e


def _parse_xlsx(data: bytes) -> NormalizedBatch:
    wb = open_workbook(data)
    try:
        with _unexpected_as_unreadable(
            "No pude leer el archivo: parece dañado. Vuelve a exportar el reporte desde Soft "
            "Restaurant y envíamelo de nuevo."
        ):
            for parser in XLSX_PARSERS:
                if parser.matches(wb):
                    return parser.parse(wb)
    finally:
        wb.close()
    raise _unknown()


def _parse_xml(data: bytes) -> NormalizedBatch:
    root = parse_xml(data)
    with _unexpected_as_unreadable(
        "No pude leer la factura: el XML parece dañado. Descárgala de nuevo desde el portal del "
        "SAT o pídele a tu proveedor el XML original."
    ):
        for parser in XML_PARSERS:
            if parser.matches(root):
                return parser.parse(root)
    # an Excel 2003 XML export or an HTML ".xls" lands here
    raise _unknown(f" {SR_HINT}")


def _unknown(hint: str = "") -> UnknownReport:
    ours = "".join(f"{p.report_es}, " for p in XLSX_PARSERS if not p.from_sr)
    known = ", ".join(f"«{p.report_es}»" for p in XLSX_PARSERS if p.from_sr)
    xml = " o ".join(p.doc_es for p in XML_PARSERS)
    return UnknownReport(
        f"No reconocí este reporte. Por ahora puedo leer {ours}estos reportes de Soft "
        f"Restaurant: {known}; o {xml}.{hint}",
        "no parser fingerprint matched",
    )
