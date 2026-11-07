"""MR-36: how a CFDI invoice's issuer is matched to the tenant's suppliers, on the El Güero seed.

An RFC on file is trusted; a name match only counts for a supplier with no RFC on file, so an
invoice from another RFC never borrows a known supplier's name or aliases. An issuer with a
4-letter RFC is a person: their name is masked in the diff and left out of the notes. Each test
runs in one transaction that is rolled back. Needs MERMIA_DB_URL.
"""

import datetime as dt
import json
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest

from mermia_api.ingestion.loader import LoadResult, load
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import NormalizedBatch, Period, PurchaseLineIn, SupplierIn
from mermia_contracts.db.models import SupplierKind

pytestmark = pytest.mark.db

FILE = Path(__file__).parents[4] / "fixtures/cfdi/synthetic/factura_carnes_selectas_2026-10-08.xml"
TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
CARNE = UUID("356dfff4-d912-542b-b8b0-8ae42068eb7e")
PASTOR = PurchaseLineIn(
    description="CARNE AL PASTOR (ADOBADA)",
    qty=Decimal(10),
    unit="KGM",
    unit_price_net=Decimal(212),
)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        yield c


@pytest.fixture
def source(conn: psycopg.Connection[Any]) -> UUID:
    row = conn.execute(
        """insert into public.source (tenant_id, location_id, kind, status)
           values (%s, null, 'cfdi', 'active') returning id""",
        (TENANT,),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


@pytest.fixture(scope="module")
def invoice() -> NormalizedBatch:
    return parse_file(FILE.read_bytes())


def from_issuer(
    batch: NormalizedBatch, supplier: SupplierIn | None, day: dt.date = dt.date(2026, 10, 8)
) -> NormalizedBatch:
    """The invoice with only the pastor line, from another issuer and on another day."""
    (doc,) = batch.purchases
    changes: dict[str, Any] = {
        "lines": [PASTOR],
        "issued_at": doc.issued_at.replace(year=day.year, month=day.month, day=day.day),
    }
    if supplier is not None:
        changes["supplier"] = supplier
    return batch.model_copy(
        update={
            "totals": batch.totals.model_copy(update={"lines": 1}),
            "period": Period.model_validate({"from": day, "to": day}),
            "purchases": [doc.model_copy(update=changes)],
        }
    )


def issuer(name: str, rfc: str) -> SupplierIn:
    return SupplierIn(name=name, rfc=rfc, kind=SupplierKind.cfdi)


def diff(conn: psycopg.Connection[Any], r: LoadResult) -> dict[str, Any]:
    row = conn.execute(
        "select diff from public.pending_change where diff ->> 'batch_id' = %s and target_id = %s",
        (str(r.batch_id), CARNE),
    ).fetchone()
    assert row is not None
    return dict(row[0])


def codes(r: LoadResult) -> list[str]:
    return [i.code for i in r.issues]


def test_a_supplier_is_found_by_rfc(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    found = diff(conn, load(conn, from_issuer(invoice, None), source_id=source))
    assert (found["supplier_matched_by"], found["matched_by"]) == ("rfc", "alias")
    assert found["supplier_name"] == "Carnes Selectas del Bajío"


def test_a_supplier_without_an_rfc_on_file_is_found_by_name(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    abasto = issuer("CENTRAL DE ABASTO, BODEGA 23", "CAB150301AB1")
    r = load(conn, from_issuer(invoice, abasto), source_id=source)
    found = diff(conn, r)
    assert found["supplier_matched_by"] == "name"
    assert found["supplier_name"] == "Central de Abasto, Bodega 23"
    assert "cfdi.supplier_unknown" not in codes(r)


def test_another_rfc_never_borrows_a_known_supplier_name(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    impostor = issuer("Carnes Selectas del Bajio", "CSX150301AB1")
    r = load(conn, from_issuer(invoice, impostor), source_id=source)
    found = diff(conn, r)
    assert (found["supplier_matched_by"], found["matched_by"]) == ("none", "name")  # no aliases
    assert found["supplier_name"] == "Carnes Selectas del Bajio"
    assert "cfdi.supplier_unknown" in codes(r)
    assert conn.execute("select count(*) from public.supplier").fetchone() == (3,)


def test_a_person_issuer_is_masked_in_the_diff_and_left_out_of_the_notes(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    person = issuer("JOSÉ PÉREZ LÓPEZ", "PELJ800101AB1")
    r = load(conn, from_issuer(invoice, person), source_id=source)
    found = diff(conn, r)
    assert (found["supplier_name"], found["supplier_matched_by"]) == ("José P.", "none")
    texts = [json.dumps(found, ensure_ascii=False)] + [i.message_es for i in r.issues]
    texts += [
        row[0]
        for row in conn.execute(
            "select message_es from public.import_issue where batch_id = %s", (r.batch_id,)
        ).fetchall()
    ]
    assert "cfdi.supplier_unknown" in codes(r)
    assert not [t for t in texts for word in ("PÉREZ", "LÓPEZ", "PELJ") if word in t.upper()]
