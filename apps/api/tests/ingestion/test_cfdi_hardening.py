"""MR-36 review: invoice text is untrusted. Values echoed in a refusal are cut short and cleaned,
names and descriptions are capped, and RFCs must have the SAT's format.

Each case edits one attribute of the synthetic invoice in fixtures/cfdi/synthetic/.
"""

import unicodedata
from pathlib import Path

import pytest
from _cfdi_builder import cfdi, concepto

from mermia_api.ingestion.errors import MalformedReport, ReportError
from mermia_api.ingestion.parsers.cfdi_factura import MAX_TEXT
from mermia_api.ingestion.registry import parse_file
from mermia_api.ingestion.safe_text import ECHO_CHARS, clean, shown

INVOICE = (
    Path(__file__).parents[4] / "fixtures/cfdi/synthetic/factura_carnes_selectas_2026-10-08.xml"
).read_bytes()
EMISOR_RFC = b'Rfc="CSB150301AB1"'
RECEPTOR_RFC = b'Rfc="TEG190415MX2"'
NOMBRE = b'Nombre="CARNES SELECTAS DEL BAJIO"'
DESCRIPCION = b'Descripcion="HUEVO"'
HIDDEN = "\u202e\u2066\u200b\u200f"  # bidi overrides and isolates, zero-width space, RLM
LONG_ECHO = 3 * ECHO_CHARS + 60  # quotes, the repr and a short label around the shown value


def edited(old: bytes, new: str) -> bytes:
    assert INVOICE.count(old) >= 1
    return INVOICE.replace(old, new.encode(), 1)


def refusal(data: bytes) -> ReportError:
    with pytest.raises(ReportError) as e:
        parse_file(data)
    return e.value


def has_hidden_characters(text: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Cf") for c in text)


# --- the shared helper -------------------------------------------------------------------


def test_clean_drops_control_and_bidi_characters_and_collapses_spaces() -> None:
    assert clean(f" A{HIDDEN}B\t\n C\u2028D ", 40) == "AB C D"


def test_clean_cuts_long_text_with_an_ellipsis() -> None:
    assert clean("x" * 50, 10) == "x" * 9 + "…"
    assert clean("x" * 10, 10) == "x" * 10


def test_shown_is_cut_to_the_echo_limit() -> None:
    assert len(shown("y" * 10_000)) == ECHO_CHARS


# --- S1: refusals never echo a whole value -----------------------------------------------


@pytest.mark.parametrize(
    ("old", "value"),
    [
        (b'Version="4.0"', "V" * 200_000),
        (b'TipoDeComprobante="I"', "Z" * 200_000),
        (b'Moneda="MXN"', "U" * 200_000),
        (b'Fecha="2026-10-08T09:15:00"', "2" * 200_000),
        (b'SubTotal="5160.00"', "9" * 200_000),
        (b'SubTotal="5160.00"', "1." + "1" * 200_000),
        (b'SubTotal="5160.00"', "x" * 200_000),
        (b'UUID="5D3E8A1C-7B2F-4E9A-9C61-0F4A2B7D8E13"', "A" * 200_000),
    ],
    ids=["version", "tipo", "moneda", "fecha", "huge", "decimals", "not_plain", "uuid"],
)
def test_a_huge_value_is_never_echoed_in_full(old: bytes, value: str) -> None:
    attribute = old.split(b"=")[0].decode()
    error = refusal(edited(old, f'{attribute}="{value}"'))
    assert len(error.message_es) < LONG_ECHO + 200
    assert len(error.detail) < LONG_ECHO


@pytest.mark.parametrize(
    ("old", "attribute"),
    [(b'Moneda="MXN"', "Moneda"), (b'TipoDeComprobante="I"', "TipoDeComprobante")],
)
def test_bidi_and_control_characters_are_not_echoed(old: bytes, attribute: str) -> None:
    error = refusal(edited(old, f'{attribute}="US{HIDDEN}&#9;D"'))
    assert not has_hidden_characters(error.message_es)
    assert not has_hidden_characters(error.detail)


# --- S2: RFCs, names and descriptions ----------------------------------------------------


BAD_RFCS = ["CSB150301AB", "csb150301ab1", "CSB15O301AB1", "CSB150301AB1X", "R" * 5000]


@pytest.mark.parametrize("rfc", BAD_RFCS)
@pytest.mark.parametrize(("old", "who"), [(EMISOR_RFC, "Emisor"), (RECEPTOR_RFC, "Receptor")])
def test_an_rfc_without_the_sat_format_is_refused(old: bytes, who: str, rfc: str) -> None:
    error = refusal(edited(old, f'Rfc="{rfc}"'))
    assert isinstance(error, MalformedReport)
    assert "RFC" in error.message_es and who in error.message_es
    assert rfc not in error.message_es and rfc not in error.detail


@pytest.mark.parametrize("old", [EMISOR_RFC, RECEPTOR_RFC])
def test_an_rfc_with_hidden_characters_is_refused(old: bytes) -> None:
    error = refusal(edited(old, f'Rfc="CSB150301AB1{HIDDEN}"'))
    assert not has_hidden_characters(error.message_es + error.detail)


@pytest.mark.parametrize("rfc", ["GOMA850101K12", "Ñ&amp;A950101AB1"])
def test_rfcs_with_four_letters_or_n_tilde_and_ampersand_are_read(rfc: str) -> None:
    batch = parse_file(edited(EMISOR_RFC, f'Rfc="{rfc}"'))
    assert batch.purchases[0].supplier.rfc == rfc.replace("&amp;", "&")


def test_a_long_supplier_name_is_capped() -> None:
    name = parse_file(edited(NOMBRE, f'Nombre="{"N" * 5000}"')).purchases[0].supplier.name
    assert name == "N" * (MAX_TEXT - 1) + "…"


def test_a_long_description_is_capped() -> None:
    batch = parse_file(edited(DESCRIPCION, f'Descripcion="{"D" * 5000}"'))
    assert batch.purchases[0].lines[4].description == "D" * (MAX_TEXT - 1) + "…"


def test_names_and_descriptions_are_cleaned() -> None:
    data = edited(NOMBRE, f'Nombre="CARNES{HIDDEN}&#9;&#10;SELECTAS"')
    data = data.replace(DESCRIPCION, f'Descripcion="HUE{HIDDEN}VO"'.encode())
    doc = parse_file(data).purchases[0]
    assert doc.supplier.name == "CARNES SELECTAS"
    assert doc.lines[4].description == "HUEVO"


def test_a_description_of_only_hidden_characters_is_refused() -> None:
    error = refusal(edited(DESCRIPCION, f'Descripcion="{HIDDEN}"'))
    assert isinstance(error, MalformedReport)
    assert "Descripcion" in error.message_es


# --- R2: line price bound and subtotal tolerance ------------------------------------------


def malformed(data: bytes) -> str:
    err = refusal(data)
    assert isinstance(err, MalformedReport)
    return err.message_es


def test_a_line_price_beyond_the_contract_is_refused_naming_the_concepto() -> None:
    line = concepto(f"MUY{HIDDEN}CARO", "0.000001", "999999999.99", "999999999.99")
    message = malformed(cfdi(line, subtotal="999999999.99", total="999999999.99"))
    assert "concepto 1" in message
    assert "MUYCARO" in message
    assert "dañado" not in message
    assert not has_hidden_characters(message)


def test_the_subtotal_tolerance_is_half_a_centavo_per_line() -> None:
    lines = [concepto("A", "1", "10.005", "10.005"), concepto("B", "1", "10.005", "10.005")]
    assert "SubTotal" in malformed(cfdi(*lines, subtotal="20.03", total="20.03"))
