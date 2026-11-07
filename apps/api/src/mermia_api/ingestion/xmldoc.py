"""Reading XML files (CFDI invoices) safely: bounded size, UTF-8 only, no DTD, no entities.

An uploaded XML is untrusted. defusedxml refuses any DOCTYPE, so entity expansion (billion laughs),
external entities (file:///etc/passwd, http://...) and external DTDs never reach the parser, and
nothing is ever fetched. The SAT requires CFDI files in UTF-8, so any other encoding is refused
instead of guessed.
"""

from __future__ import annotations

import re
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from mermia_api.ingestion.errors import UnreadableFile

MAX_BYTES = 2 * 1024 * 1024  # a CFDI with 500 conceptos is well under 1 MiB
BOM = b"\xef\xbb\xbf"
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
SNIFF_BYTES = 1024  # leading whitespace before the first "<" that still counts as XML
# The encoding named in the XML declaration, if any: only UTF-8 is accepted.
DECLARED = re.compile(rb"""^\s*<\?xml[^>]*?\sencoding\s*=\s*["']([^"']*)["']""")


def looks_like_xml(data: bytes) -> bool:
    """Whether the file starts like XML (after a BOM and whitespace). UTF-16 files count as XML,
    so the refusal names the encoding instead of asking for an Excel file."""
    if data.startswith(UTF16_BOMS):
        return True
    return data[:SNIFF_BYTES].removeprefix(BOM).lstrip().startswith(b"<")


def _not_utf8(detail: str) -> UnreadableFile:
    return UnreadableFile(
        "El XML no está en UTF-8, como lo pide el SAT. Descarga de nuevo la factura desde el "
        "portal del SAT o pídele a tu proveedor el XML original.",
        detail,
    )


def _utf8_body(data: bytes) -> bytes:
    """The bytes without a BOM or leading whitespace (which would put the XML declaration out of
    place), checked to be UTF-8 and to declare no other encoding."""
    if len(data) > MAX_BYTES:
        raise UnreadableFile(
            "El XML es demasiado grande para una factura. Envíame una factura por archivo.",
            f"{len(data)} bytes > {MAX_BYTES}",
        )
    if data.startswith(UTF16_BOMS):
        raise _not_utf8("UTF-16 byte order mark")
    body = data.removeprefix(BOM).lstrip()
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as e:
        raise _not_utf8(f"invalid UTF-8 at byte {e.start}") from e
    declared = DECLARED.match(body)
    if declared and declared[1].lower() not in (b"utf-8", b"utf8"):
        raise _not_utf8(f"declared encoding {declared[1]!r}")
    return body


def parse_xml(data: bytes) -> Element:
    """The root element of an XML file. Raises UnreadableFile (Spanish message) for anything we
    will not read: too big, not UTF-8, broken, or with a DTD or entities."""
    body = _utf8_body(data)
    try:
        return fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as e:
        raise UnreadableFile(
            "No puedo abrir este XML: trae declaraciones internas (DTD o entidades) que no "
            "acepto por seguridad. Una factura CFDI no las lleva; pídele a tu proveedor el XML "
            "original.",
            f"{type(e).__name__}",
        ) from e
    except ParseError as e:
        raise UnreadableFile(
            "No pude leer el XML: parece dañado o incompleto. Descarga de nuevo la factura desde "
            "el portal del SAT o pídele a tu proveedor el XML original.",
            f"ParseError: {e}",
        ) from e
