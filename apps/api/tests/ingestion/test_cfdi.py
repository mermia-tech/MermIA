"""MR-36: the CFDI 4.0 supplier invoice parser and the registry's XML route.

The golden test for the synthetic invoice is in test_golden.py; the XML safety tests are in
test_xmldoc.py. Every refusal is a ReportError with a Spanish message, never a crash.
"""

import datetime as dt
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from _cfdi_builder import UUID_, cfdi, concepto, traslado

from mermia_api.ingestion.errors import MalformedReport, UnknownReport
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import Grain
from mermia_contracts.db.models import IssueSeverity, PurchaseDocKind, SourceKind, SupplierKind


def malformed(data: bytes) -> str:
    with pytest.raises(MalformedReport) as e:
        parse_file(data)
    return e.value.message_es


# --- a good invoice ----------------------------------------------------------------------


def test_a_small_invoice() -> None:
    batch = parse_file(cfdi())
    assert (batch.parser, batch.source_kind, batch.grain) == (
        "cfdi.factura@v1",
        SourceKind.cfdi,
        Grain.purchase,
    )
    assert batch.location_hint is None
    assert (batch.totals.lines, batch.totals.net_sales) == (1, None)
    (doc,) = batch.purchases
    assert doc.kind == PurchaseDocKind.cfdi
    assert doc.supplier.rfc == "CSB150301AB1"
    assert doc.buyer_rfc == "TEG190415MX2"
    assert doc.supplier.kind == SupplierKind.cfdi
    assert doc.cfdi_uuid == UUID(UUID_)
    assert (doc.subtotal, doc.total) == (13000, 13000)
    (line,) = doc.lines
    assert (line.description, line.qty, line.unit, line.unit_price_net) == (
        "CEBOLLA BLANCA",
        Decimal(5),
        "KGM",
        Decimal(26),
    )
    assert batch.issues == []


def test_fecha_gets_the_mexico_city_time_zone() -> None:
    batch = parse_file(cfdi(fecha="2026-10-08T23:30:00"))
    issued = batch.purchases[0].issued_at
    assert issued == dt.datetime(2026, 10, 8, 23, 30, tzinfo=ZoneInfo("America/Mexico_City"))
    assert issued.utcoffset() == dt.timedelta(hours=-6)
    assert (batch.period.from_, batch.period.to) == (dt.date(2026, 10, 8), dt.date(2026, 10, 8))


@pytest.mark.parametrize("fecha", ["2026-10-08T09:15:00-06:00", "2026-10-08", "08/10/2026"])
def test_fecha_in_another_format_is_refused(fecha: str) -> None:
    assert "Fecha" in malformed(cfdi(fecha=fecha))


def test_a_discount_is_netted_into_the_unit_price() -> None:
    line = concepto("QUESO OAXACA", "4", "150.00", "600.00", descuento="40.00")
    batch = parse_file(cfdi(line, subtotal="600.00", descuento="40.00", total="560.00"))
    assert batch.purchases[0].lines[0].unit_price_net == Decimal("140.000000")


def test_a_netted_price_is_rounded_once_to_six_decimals() -> None:
    line = concepto("QUESO OAXACA", "3", "100.00", "300.00", descuento="10.00")
    batch = parse_file(cfdi(line, subtotal="300.00", descuento="10.00", total="290.00"))
    assert batch.purchases[0].lines[0].unit_price_net == Decimal("96.666667")


def test_the_price_is_importe_over_cantidad_even_without_a_discount() -> None:
    line = concepto("HUEVO", "3", "26.00", "78.01")
    batch = parse_file(cfdi(line, subtotal="78.01", total="78.01"))
    assert batch.purchases[0].lines[0].unit_price_net == Decimal("26.003333")
    assert batch.issues == []


def test_a_six_decimal_unit_value_gives_way_to_the_importe() -> None:
    line = concepto("HUEVO", "1", "45.123456", "45.12")
    batch = parse_file(cfdi(line, subtotal="45.12", total="45.12"))
    assert batch.purchases[0].lines[0].unit_price_net == Decimal("45.120000")
    assert batch.issues == []


def test_a_unit_value_rounded_to_centavos_is_not_an_outlier() -> None:
    # 3.5 kg at 33.3343 a kilo: ValorUnitario is written 33.33, so 3.5 x 33.33 = 116.655
    line = concepto("QUESO", "3.5", "33.33", "116.67")
    batch = parse_file(cfdi(line, subtotal="116.67", total="116.67"))
    assert batch.purchases[0].lines[0].unit_price_net == Decimal("33.334286")
    assert batch.issues == []


def test_a_seven_decimal_unit_value_is_refused() -> None:
    line = concepto("HUEVO", "1", "45.1234567", "45.12")
    assert "decimales" in malformed(cfdi(line, subtotal="45.12", total="45.12"))


@pytest.mark.parametrize("valor", ["26,00", "2.6e1", "$26.00", "-26.00", " 26.00", ""])
def test_a_number_not_written_plainly_is_refused(valor: str) -> None:
    message = malformed(cfdi(concepto(valor=valor)))
    assert "ValorUnitario" in message


def test_a_line_whose_importe_is_off_is_a_warning() -> None:
    batch = parse_file(cfdi(concepto(importe="131.00"), subtotal="131.00", total="131.00"))
    (issue,) = batch.issues
    assert (issue.severity, issue.code, issue.row_ref) == (
        IssueSeverity.warning,
        "cfdi.importe_mismatch",
        "1",
    )
    assert "En el concepto 1 (CEBOLLA BLANCA)" in issue.message_es
    assert batch.purchases[0].lines[0].unit_price_net == Decimal("26.200000")


def test_a_line_warning_shows_a_long_description_cut_short() -> None:
    line = concepto("Q" * 300, importe="131.00")
    (issue,) = parse_file(cfdi(line, subtotal="131.00", total="131.00")).issues
    assert "Q" * 39 + "…" in issue.message_es
    assert "Q" * 41 not in issue.message_es


def test_ieps_on_a_line_is_a_warning_and_iva_is_not() -> None:
    iva = concepto("CEBOLLA", impuestos=traslado("002"))
    ieps = concepto("REFRESCO", impuestos=traslado("003", importe="10.40"))
    batch = parse_file(cfdi(iva, ieps, subtotal="260.00", total="270.40"))
    assert [(i.code, i.row_ref) for i in batch.issues] == [("cfdi.ieps_listed", "2")]
    assert "(REFRESCO)" in batch.issues[0].message_es


# --- refusals ----------------------------------------------------------------------------


def test_cfdi_3_3_asks_for_version_4() -> None:
    message = malformed(cfdi(ns="3", version="3.3"))
    assert "3.3" in message and "4.0" in message


def test_a_wrong_version_in_the_cfdi_4_namespace_is_refused() -> None:
    assert "4.0" in malformed(cfdi(version="4.1"))


@pytest.mark.parametrize(
    ("tipo", "word"), [("E", "crédito"), ("P", "pago"), ("T", "traslado"), ("N", "nómina")]
)
def test_only_income_invoices_are_read(tipo: str, word: str) -> None:
    assert word in malformed(cfdi(tipo=tipo))


def test_another_currency_is_refused() -> None:
    assert "USD" in malformed(cfdi(moneda="USD"))


def test_an_invoice_without_a_timbre_is_refused() -> None:
    assert "timbrada" in malformed(cfdi(uuid=None))


def test_a_bad_uuid_is_refused() -> None:
    assert "UUID" in malformed(cfdi(uuid="not-a-uuid"))


def test_subtotal_must_be_the_sum_of_the_lines() -> None:
    assert "SubTotal" in malformed(cfdi(subtotal="131.00", total="131.00"))


def test_subtotal_within_half_a_centavo_per_line_is_a_warning() -> None:
    # each Importe of 10.005 rounded up by the issuer: 20.02 against a sum of 20.01
    lines = [concepto("A", "1", "10.005", "10.005"), concepto("B", "1", "10.005", "10.005")]
    batch = parse_file(cfdi(*lines, subtotal="20.02", total="20.02"))
    (issue,) = batch.issues
    assert (issue.severity, issue.code, issue.row_ref) == (
        IssueSeverity.warning,
        "cfdi.sum_gap",
        None,
    )
    assert "SubTotal" in issue.message_es
    assert "$0.01" in issue.message_es
    assert "centavos" not in issue.message_es
    assert batch.purchases[0].subtotal == 2002


def test_subtotal_beyond_half_a_centavo_per_line_is_refused() -> None:
    lines = [concepto("A", "1", "10.005", "10.005"), concepto("B", "1", "10.005", "10.005")]
    assert "SubTotal" in malformed(cfdi(*lines, subtotal="20.04", total="20.04"))


def test_descuento_must_be_the_sum_of_the_line_discounts() -> None:
    line = concepto("QUESO OAXACA", "4", "150.00", "600.00", descuento="40.00")
    message = malformed(cfdi(line, subtotal="600.00", descuento="30.00", total="570.00"))
    assert "Descuento" in message


def test_a_line_discount_without_a_total_discount_is_refused() -> None:
    line = concepto("QUESO OAXACA", "4", "150.00", "600.00", descuento="40.00")
    assert "Descuento" in malformed(cfdi(line, subtotal="600.00", total="560.00"))


def test_subtotal_with_more_than_two_decimals_is_refused() -> None:
    line = concepto(importe="130.001", valor="26.0002")
    assert "SubTotal" in malformed(cfdi(line, subtotal="130.001", total="130.00"))


def test_a_zero_quantity_is_refused() -> None:
    assert "Cantidad" in malformed(cfdi(concepto(cantidad="0", importe="0.00"), subtotal="0.00"))


def test_a_discount_above_the_importe_is_refused() -> None:
    line = concepto(descuento="131.00")
    assert "Descuento" in malformed(cfdi(line, descuento="131.00", total="0.00"))


def test_a_blank_description_is_refused() -> None:
    assert "Descripcion" in malformed(cfdi(concepto(desc="   ")))


def test_a_missing_emisor_rfc_is_refused() -> None:
    data = cfdi().replace(b'Rfc="CSB150301AB1" ', b"")
    assert "Emisor" in malformed(data)


def test_a_missing_receptor_rfc_is_refused() -> None:
    data = cfdi().replace(b'Rfc="TEG190415MX2" ', b"")
    assert "Receptor" in malformed(data)


def test_an_invoice_without_lines_is_refused() -> None:
    data = cfdi().replace(concepto().encode(), b"")
    assert "conceptos" in malformed(data)


def test_more_than_500_lines_are_refused() -> None:
    lines = [concepto()] * 501
    total = f"{130 * 501}.00"
    assert "500" in malformed(cfdi(*lines, subtotal=total, total=total))


# --- the registry's XML route ------------------------------------------------------------


def test_xml_after_a_bom_and_whitespace_is_routed_to_the_cfdi_parser() -> None:
    batch = parse_file(b"\xef\xbb\xbf \n\t" + cfdi())
    assert batch.parser == "cfdi.factura@v1"


def test_unrelated_xml_is_an_unknown_report() -> None:
    with pytest.raises(UnknownReport) as e:
        parse_file(b'<?xml version="1.0"?><factura><total>1</total></factura>')
    assert "CFDI" in e.value.message_es


def test_excel_2003_xml_is_asked_for_as_xlsx() -> None:
    data = (
        b'<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>'
        b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet/></Workbook>'
    )
    with pytest.raises(UnknownReport) as e:
        parse_file(data)
    assert "Soft Restaurant, envíamelo en Excel (.xlsx)" in e.value.message_es


def test_the_unknown_report_message_names_the_cfdi() -> None:
    with pytest.raises(UnknownReport) as e:
        parse_file(b"<html><body>hola</body></html>")
    assert "factura CFDI" in e.value.message_es


def test_predefined_entities_in_names_are_read() -> None:
    data = cfdi().replace(b"CARNES SELECTAS DEL BAJIO", b"CARNES P&amp;H")
    assert parse_file(data).purchases[0].supplier.name == "CARNES P&H"
