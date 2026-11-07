"""MR-36: the importer's Spanish notes and the supplier name it shows. No database."""

from mermia_api.ingestion import price_issues as notes
from mermia_api.ingestion.price_match import PERSON_LABEL, invoice_supplier_name, is_person
from mermia_contracts.batch import SupplierIn
from mermia_contracts.db.models import SupplierKind


def supplier(name: str, rfc: str | None) -> SupplierIn:
    return SupplierIn(name=name, rfc=rfc, kind=SupplierKind.cfdi)


def test_unmatched_lists_at_most_five_lines_then_counts_the_rest() -> None:
    message = notes.unmatched([f"CONCEPTO {n}" for n in range(1, 9)]).message_es
    assert "estos 8 conceptos" in message
    assert "«CONCEPTO 5» y 3 más" in message
    assert "CONCEPTO 6" not in message


def test_unmatched_lists_a_few_lines_in_full() -> None:
    message = notes.unmatched(["A", "B"]).message_es
    assert "«A» y «B»" in message and "más" not in message


def test_a_four_letter_rfc_is_a_person() -> None:
    assert is_person("PELJ800101AB1") and is_person(" pelj800101ab1 ")
    assert not is_person("CSB150301AB1") and not is_person(None)


def test_a_person_supplier_shows_first_word_and_initial() -> None:
    assert invoice_supplier_name(supplier("JOSÉ PÉREZ LÓPEZ", "PELJ800101AB1")) == "José P."
    assert invoice_supplier_name(supplier("PEREZ", "PELJ800101AB1")) == PERSON_LABEL


def test_a_company_supplier_keeps_its_invoice_name() -> None:
    name = "Carnes Selectas del Bajío"
    assert invoice_supplier_name(supplier(name, "CSB150301AB1")) == name


def test_an_unknown_person_supplier_is_not_named_in_the_note() -> None:
    message = notes.supplier_unknown(None).message_es
    assert "persona física" in message and "«" not in message
    assert "«Otro Proveedor»" in notes.supplier_unknown("Otro Proveedor").message_es


def test_a_missing_buyer_rfc_is_a_warning() -> None:
    issue = notes.buyer_rfc_missing()
    assert (issue.code, issue.severity.value) == ("cfdi.buyer_rfc_missing", "warning")
