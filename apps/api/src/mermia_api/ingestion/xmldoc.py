"""Reading XML files (CFDI invoices) safely: bounded size, UTF-8 only, no DTD, no entities.

An uploaded XML is untrusted. defusedxml refuses any DOCTYPE, so entity expansion (billion laughs),
external entities (file:///etc/passwd, http://...) and external DTDs never reach the parser, and
nothing is ever fetched. The SAT requires CFDI files in UTF-8, so any other encoding is refused
instead of guessed. A small file can still build a huge tree (a megabyte of nested or empty
elements takes hundreds of MB), so the tree is built incrementally and the parse stops as soon as
it has too many elements or nests too deep.

Any file that starts with "<" comes here, so an HTML ".xls" or an Excel 2003 XML export does too:
every refusal also says to send a Soft Restaurant report as .xlsx.
"""

from __future__ import annotations

import io
import re
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import iterparse

from mermia_api.ingestion.errors import UnreadableFile
from mermia_api.ingestion.safe_text import shown

MAX_BYTES = 1024 * 1024  # a CFDI with 500 conceptos is well under 1 MiB
# A 500-concepto invoice has about 4,000 elements (Concepto, Impuestos, Traslados, Traslado ...)
# and nests 6 deep; both limits leave room and keep the tree a few MB at most.
MAX_ELEMENTS = 20_000
MAX_DEPTH = 32
BOM = b"\xef\xbb\xbf"
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
SNIFF_BYTES = 1024  # leading whitespace before the first "<" that still counts as XML
# The encoding named in the XML declaration, if any: only UTF-8 is accepted.
DECLARED = re.compile(rb"""^\s*<\?xml[^>]*?\sencoding\s*=\s*["']([^"']*)["']""")
SR_HINT = "Si es un reporte de Soft Restaurant, envíamelo en Excel (.xlsx)."


def looks_like_xml(data: bytes) -> bool:
    """Whether the file starts like XML (after a BOM and whitespace). UTF-16 files count as XML,
    so the refusal names the encoding instead of asking for an Excel file."""
    if data.startswith(UTF16_BOMS):
        return True
    return data[:SNIFF_BYTES].removeprefix(BOM).lstrip().startswith(b"<")


def _unreadable(message_es: str, detail: str) -> UnreadableFile:
    return UnreadableFile(f"{message_es} {SR_HINT}", detail)


def _not_utf8(detail: str) -> UnreadableFile:
    return _unreadable(
        "El XML no está en UTF-8, como lo pide el SAT. Descarga de nuevo la factura desde el "
        "portal del SAT o pídele a tu proveedor el XML original.",
        detail,
    )


def _too_big(detail: str) -> UnreadableFile:
    return _unreadable(
        "El XML es demasiado grande para una factura. Envíame una factura por archivo.", detail
    )


def _utf8_body(data: bytes) -> bytes:
    """The bytes without a BOM or leading whitespace (which would put the XML declaration out of
    place), checked to be UTF-8 and to declare no other encoding. A NUL byte is valid UTF-8 but
    never in XML: it means UTF-16 or UTF-32 without a BOM, or a binary file."""
    if len(data) > MAX_BYTES:
        raise _too_big(f"{len(data)} bytes > {MAX_BYTES}")
    if data.startswith(UTF16_BOMS):
        raise _not_utf8("UTF-16 byte order mark")
    nul = data.find(b"\x00")
    if nul >= 0:
        raise _not_utf8(f"NUL byte at {nul}")
    body = data.removeprefix(BOM).lstrip()
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as e:
        raise _not_utf8(f"invalid UTF-8 at byte {e.start}") from e
    declared = DECLARED.match(body)
    if declared and declared[1].lower() not in (b"utf-8", b"utf8"):
        name = declared[1].decode("utf-8", "replace")
        raise _not_utf8(f"declared encoding {shown(name)!r}")
    return body


def _bounded_tree(body: bytes) -> Element:
    """The root, built while the file is read in chunks; stops at MAX_ELEMENTS or MAX_DEPTH."""
    root: Element | None = None
    depth = count = 0
    events = iterparse(
        io.BytesIO(body),
        events=("start", "end"),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )
    for event, el in events:
        if event == "end":
            depth -= 1
            continue
        root = el if root is None else root
        count, depth = count + 1, depth + 1
        if count > MAX_ELEMENTS or depth > MAX_DEPTH:
            raise _too_big(f"more than {MAX_ELEMENTS} elements or {MAX_DEPTH} levels")
    if root is None:  # expat raises first ("no element found"); kept for the type checker
        raise ParseError("no root element")
    return root


def parse_xml(data: bytes) -> Element:
    """The root element of an XML file. Raises UnreadableFile (Spanish message) for anything we
    will not read: too big or too complex, not UTF-8, broken, or with a DTD or entities."""
    body = _utf8_body(data)
    try:
        return _bounded_tree(body)
    except DefusedXmlException as e:
        raise _unreadable(
            "No puedo abrir este XML: trae declaraciones internas (DTD o entidades) que no "
            "acepto por seguridad. Una factura CFDI no las lleva; pídele a tu proveedor el XML "
            "original.",
            f"{type(e).__name__}",
        ) from e
    except ParseError as e:
        raise _unreadable(
            "No pude leer el XML: parece dañado o incompleto. Descarga de nuevo la factura desde "
            "el portal del SAT o pídele a tu proveedor el XML original.",
            f"ParseError: {e}",  # expat names a line and column, never the data
        ) from e
