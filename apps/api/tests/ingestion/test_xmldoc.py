"""MR-36: XML is read safely. No DTD, no entities, no external fetches, bounded size, UTF-8 only.

Each hostile file must be refused as an UnreadableFile with a Spanish message, before any parser
sees it, both through `parse_xml` and through the registry.
"""

import tracemalloc

import pytest

from mermia_api.ingestion.errors import UnreadableFile
from mermia_api.ingestion.registry import parse_file
from mermia_api.ingestion.xmldoc import (
    MAX_BYTES,
    MAX_DEPTH,
    MAX_ELEMENTS,
    looks_like_xml,
    parse_xml,
)

SR_HINT = "Soft Restaurant, envíamelo en Excel (.xlsx)"

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<lolz>&lol4;</lolz>"""

EXTERNAL_ENTITY = b"""<?xml version="1.0"?>
<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<r>&x;</r>"""

EXTERNAL_DTD = b"""<?xml version="1.0"?>
<!DOCTYPE r SYSTEM "http://example.invalid/evil.dtd">
<r/>"""

PLAIN_DTD = b"""<?xml version="1.0"?>
<!DOCTYPE cfdi:Comprobante>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"/>"""

PARAMETER_ENTITY = b"""<?xml version="1.0"?>
<!DOCTYPE r [<!ENTITY % p SYSTEM "http://example.invalid/p.dtd"> %p;]>
<r/>"""


def refused(data: bytes) -> str:
    with pytest.raises(UnreadableFile) as e:
        parse_xml(data)
    with pytest.raises(UnreadableFile):
        parse_file(data)
    return e.value.message_es


@pytest.mark.parametrize(
    "data",
    [BILLION_LAUGHS, EXTERNAL_ENTITY, EXTERNAL_DTD, PLAIN_DTD, PARAMETER_ENTITY],
    ids=["billion_laughs", "external_entity", "external_dtd", "any_dtd", "parameter_entity"],
)
def test_dtds_and_entities_are_refused(data: bytes) -> None:
    message = refused(data)
    assert "seguridad" in message
    assert "passwd" not in message


def test_a_file_over_the_size_cap_is_refused() -> None:
    assert MAX_BYTES == 1024 * 1024
    assert "grande" in refused(b"<r>" + b" " * MAX_BYTES + b"</r>")


def test_too_many_elements_are_refused() -> None:
    assert "grande" in refused(b"<r>" + b"<b/>" * MAX_ELEMENTS + b"</r>")


def test_the_element_limit_is_inclusive() -> None:
    root = parse_xml(b"<r>" + b"<b/>" * (MAX_ELEMENTS - 1) + b"</r>")
    assert len(root) == MAX_ELEMENTS - 1


def test_nesting_too_deep_is_refused() -> None:
    assert "grande" in refused(b"<a>" * (MAX_DEPTH + 1) + b"</a>" * (MAX_DEPTH + 1))


def test_nesting_at_the_limit_is_read() -> None:
    assert parse_xml(b"<a>" * MAX_DEPTH + b"</a>" * MAX_DEPTH).tag == "a"


def test_a_deep_file_under_the_size_cap_is_stopped_early() -> None:
    n = MAX_BYTES // 7
    data = b"<a>" * n + b"</a>" * n
    tracemalloc.start()
    try:
        with pytest.raises(UnreadableFile):
            parse_xml(data)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * MAX_BYTES  # the whole tree would take hundreds of MB


@pytest.mark.parametrize(
    "data",
    [
        "<r>Ñandú</r>".encode("latin-1"),
        '<?xml version="1.0" encoding="ISO-8859-1"?><r>x</r>'.encode("latin-1"),
        "<r>x</r>".encode("utf-16"),
        "<r>x</r>".encode("utf-16-le"),
        b"<r>\x00</r>",
    ],
    ids=["latin1_bytes", "latin1_declared", "utf16", "utf16_without_bom", "nul_byte"],
)
def test_xml_that_is_not_utf8_is_refused(data: bytes) -> None:
    assert "UTF-8" in refused(data)


def test_a_long_declared_encoding_is_not_echoed() -> None:
    data = b'<?xml version="1.0" encoding="' + b"X" * 5000 + b'"?><r/>'
    with pytest.raises(UnreadableFile) as e:
        parse_xml(data)
    assert len(e.value.detail) < 100


def test_broken_xml_is_refused() -> None:
    message = refused(b"<r><a></r>")
    assert "XML" in message
    assert SR_HINT in message


def test_an_html_spreadsheet_is_asked_for_as_xlsx() -> None:
    assert SR_HINT in refused(b"<!DOCTYPE html><html><body><table></table></body></html>")


def test_a_bom_is_stripped() -> None:
    root = parse_xml(b"\xef\xbb\xbf" + '<?xml version="1.0" encoding="utf-8"?><r a="Ñ"/>'.encode())
    assert (root.tag, root.get("a")) == ("r", "Ñ")


@pytest.mark.parametrize(
    ("data", "is_xml"),
    [
        (b"<r/>", True),
        (b"\xef\xbb\xbf\r\n  <r/>", True),
        (b"\xff\xfe<\x00", True),  # UTF-16: sent to the XML path, which refuses it by name
        (b"PK\x03\x04", False),
        (b"%PDF-1.7", False),
        (b"", False),
    ],
)
def test_sniffing_xml(data: bytes, is_xml: bool) -> None:
    assert looks_like_xml(data) is is_xml
