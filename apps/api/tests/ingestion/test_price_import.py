"""MR-36: CFDI invoices become ingredient_price.set pending changes, on the El Güero seed.

The loader never writes ingredient_price, purchase_doc or purchase_line: every price it can match
is compared with the price of record and, when it moved, proposed for a person to approve
(app.apply_pending_change writes it). Each test runs in one transaction that is rolled back.
Needs MERMIA_DB_URL and the seed. The per-rule tests are in test_price_rules.py.

The synthetic invoice (2026-10-08, Carnes Selectas del Bajío) against the seed:
pastor 212/kg (record 0.195/g, alias) -> proposed; bistec 210/kg -> unchanged; cebolla 26/kg
(record 0.024/g; the alias is another supplier's) -> proposed by name; queso 150/kg less a 40
discount on 4 kg = 140/kg -> unchanged; huevo by the kilo (a pieces ingredient, no conversion)
-> held; carbón -> unmatched.
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

from mermia_api.confirm.apply import apply_pending_change
from mermia_api.ingestion.loader import LoadResult, load
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import NormalizedBatch
from mermia_contracts.pending import ApplyPendingChangeArgs, IngredientPriceSet

pytestmark = pytest.mark.db

INVOICE = Path(__file__).parents[4] / "fixtures" / "cfdi" / "synthetic"
FILE = INVOICE / "factura_carnes_selectas_2026-10-08.xml"
TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
OWNER = UUID("eb52f6ad-4d75-5b06-9881-9f68f4fb05a0")
LUPITA = UUID("240e45f0-ef48-5654-a835-8fbc70de15bc")  # manager: may not approve prices
CARNE = UUID("356dfff4-d912-542b-b8b0-8ae42068eb7e")
CEBOLLA = UUID("9342bb49-51d8-55b9-843f-f010e898da4f")
RFCS = ("CSB150301AB1", "TEG190415MX2")
DAY = dt.date(2026, 10, 8)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        yield c


@pytest.fixture
def source(conn: psycopg.Connection[Any]) -> UUID:
    """A tenant-level CFDI source (the email inbox; the seed has none)."""
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


def pending(conn: psycopg.Connection[Any], batch_id: UUID) -> dict[UUID, dict[str, Any]]:
    cur = conn.execute(
        """select id, kind, target_type, target_id, base_version, payload, diff,
                  proposed_via::text, required_role::text, status::text,
                  expires_at - created_at as ttl
           from public.pending_change where diff ->> 'batch_id' = %s""",
        (str(batch_id),),
    )
    names = [d.name for d in cur.description or []]
    rows = [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
    return {r["target_id"]: r for r in rows}


def count(conn: psycopg.Connection[Any], sql: str, *args: Any) -> int:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return int(row[0])


def codes(r: LoadResult) -> list[str]:
    return [i.code for i in r.issues]


def test_the_invoice_proposes_the_two_prices_that_moved(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    r = load(conn, invoice, source_id=source, proposed_by=OWNER)
    assert r.status == "parsed" and not r.duplicate
    found = pending(conn, r.batch_id)
    assert set(found) == {CARNE, CEBOLLA}
    assert set(r.pending_change_ids) == {p["id"] for p in found.values()}
    stats = conn.execute(
        "select stats from public.import_batch where id = %s", (r.batch_id,)
    ).fetchone()
    assert stats is not None
    assert {k: stats[0][k] for k in ("proposed", "unchanged", "already_pending", "held")} == {
        "proposed": 2,
        "unchanged": 2,
        "already_pending": 0,
        "held": 2,
    }
    assert codes(r) == ["cfdi.unit_mismatch", "cfdi.line_unmatched"]
    (unmatched,) = [i for i in r.issues if i.code == "cfdi.line_unmatched"]
    assert "«CARBÓN VEGETAL»" in unmatched.message_es


def test_the_payload_is_flat_as_apply_ingredient_price_reads_it(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    r = load(conn, invoice, source_id=source)
    carne = pending(conn, r.batch_id)[CARNE]
    assert carne["payload"] == {
        "unit_price": "0.212000",
        "effective_from": "2026-10-08",
        "source": "cfdi",
    }
    assert IngredientPriceSet.model_validate(carne["payload"]).unit_price == Decimal("0.212")
    assert (carne["kind"], carne["target_type"]) == ("ingredient_price.set", "ingredient")
    assert (carne["proposed_via"], carne["required_role"], carne["status"]) == (
        "import",
        "manager",
        "pending",
    )
    assert carne["ttl"] == dt.timedelta(hours=24)
    assert carne["base_version"] == count(
        conn, "select count(*) from public.ingredient_price where ingredient_id = %s", CARNE
    )


def test_the_diff_carries_the_invoice_for_the_confirmation(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    r = load(conn, invoice, source_id=source)
    found = pending(conn, r.batch_id)
    carne, cebolla = found[CARNE]["diff"], found[CEBOLLA]["diff"]
    assert carne["batch_id"] == str(r.batch_id)
    assert carne["cfdi_uuid"] == "5d3e8a1c-7b2f-4e9a-9c61-0f4a2b7d8e13"
    assert carne["supplier_name"] == "Carnes Selectas del Bajío"
    assert carne["ingredient"] == {
        "id": str(CARNE),
        "name": "Carne al pastor (adobada)",
        "base_unit": "g",
    }
    assert (carne["matched_by"], carne["match_label"]) == ("alias", None)
    assert carne["before"] == {
        "unit_price_net": "0.195000",
        "effective_from": "2026-09-21",
        "source": "cfdi",
    }
    assert carne["after"] == {
        "unit_price_net": "0.212000",
        "effective_from": "2026-10-08",
        "source": "cfdi",
    }
    assert carne["change_pct"] == "8.72"
    assert carne["lines"] == [
        {
            "row": 1,
            "description": "CARNE AL PASTOR (ADOBADA)",
            "qty": "10.000000",
            "unit": "KGM",
            "unit_price_net": "212.000000",
            "base_per_unit": "1000",
            "ieps_excluded": False,
        }
    ]
    assert (cebolla["matched_by"], cebolla["match_label"]) == ("name", "(por nombre)")
    assert (cebolla["after"]["unit_price_net"], cebolla["change_pct"]) == ("0.026000", "8.33")


def test_no_rfc_reaches_the_diff_the_audit_or_the_notes(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    r = load(conn, invoice, source_id=source)
    texts = [
        json.dumps(p["diff"]) + json.dumps(p["payload"]) for p in pending(conn, r.batch_id).values()
    ]
    texts += [
        json.dumps(row)
        for row in conn.execute(
            "select before, after from public.audit_log where batch_id = %s", (r.batch_id,)
        ).fetchall()
    ]
    texts += [
        row[0]
        for row in conn.execute(
            "select message_es from public.import_issue where batch_id = %s", (r.batch_id,)
        ).fetchall()
    ]
    assert texts and not [t for t in texts for rfc in RFCS if rfc in t.upper()]


def test_each_proposal_has_its_audit_row(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    r = load(conn, invoice, source_id=source, proposed_by=OWNER)
    rows = conn.execute(
        """select entity_type, entity_id, actor_user_id, pending_change_id,
                  after ->> 'unit_price_net'
           from public.audit_log where batch_id = %s and action = 'pending_change.propose'""",
        (r.batch_id,),
    ).fetchall()
    found = pending(conn, r.batch_id)
    assert sorted(rows, key=str) == sorted(
        [
            ("ingredient", CARNE, OWNER, found[CARNE]["id"], "0.212000"),
            ("ingredient", CEBOLLA, OWNER, found[CEBOLLA]["id"], "0.026000"),
        ],
        key=str,
    )


def test_load_never_writes_prices_or_purchase_rows(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    tables = ("ingredient_price", "purchase_doc", "purchase_line", "supplier", "ingredient_alias")
    before = {t: count(conn, f"select count(*) from public.{t}") for t in tables}
    load(conn, invoice, source_id=source)
    assert {t: count(conn, f"select count(*) from public.{t}") for t in tables} == before


def tap(conn: psycopg.Connection[Any], change: UUID, user: UUID) -> str:
    return apply_pending_change(conn, ApplyPendingChangeArgs(id=change, user_id=user)).code


def test_approving_the_proposal_writes_the_price(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    r = load(conn, invoice, source_id=source)
    change = pending(conn, r.batch_id)[CARNE]["id"]
    assert tap(conn, change, LUPITA) == "forbidden_role"  # the seed's managers can't approve prices
    assert tap(conn, change, OWNER) == "applied"
    row = conn.execute(
        """select unit_price_net, effective_from, source::text, pending_change_id
           from public.ingredient_price where ingredient_id = %s
           order by created_at desc limit 1""",
        (CARNE,),
    ).fetchone()
    assert row == (Decimal("0.212000"), DAY, "cfdi", change)
    record = conn.execute(
        "select unit_price_net from app.price_of_record(%s, %s)", (CARNE, DAY)
    ).fetchone()
    assert record == (Decimal("0.212000"),)


def test_the_same_invoice_twice_is_a_duplicate(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    first = load(conn, invoice, source_id=source)
    again = load(conn, invoice, source_id=source)
    assert (again.duplicate, again.batch_id) == (True, first.batch_id)
    imports = "select count(*) from public.pending_change where proposed_via = 'import'"
    assert count(conn, imports) == 2


def test_a_resend_after_its_proposals_were_rejected_proposes_again(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    first = load(conn, invoice, source_id=source)
    conn.execute(
        "update public.pending_change set status = 'rejected' where id = any(%s)",
        (list(first.pending_change_ids),),
    )
    again = load(conn, invoice, source_id=source)
    assert not again.duplicate and len(again.pending_change_ids) == 2


def test_after_approval_the_invoice_finds_the_price_unchanged(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    first = load(conn, invoice, source_id=source)
    for change in first.pending_change_ids:
        assert tap(conn, change, OWNER) == "applied"
    again = load(conn, invoice, source_id=source)
    assert (again.duplicate, again.pending_change_ids) == (False, ())


def test_an_invoice_for_another_buyer_is_rejected_without_naming_the_rfc(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    (doc,) = invoice.purchases
    other = invoice.model_copy(
        update={"purchases": [doc.model_copy(update={"buyer_rfc": "XAXX010101000"})]}
    )
    r = load(conn, other, source_id=source)
    assert (r.status, r.pending_change_ids) == ("rejected", ())
    assert "cfdi.buyer_mismatch" in codes(r)
    assert not [i for i in r.issues if "XAXX" in i.message_es or "TEG" in i.message_es]


def test_a_tenant_without_an_rfc_gets_a_warning_and_the_proposals(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    conn.execute("update public.tenant set rfc = null where id = %s", (TENANT,))
    r = load(conn, invoice, source_id=source)
    assert r.status == "parsed" and len(r.pending_change_ids) == 2
    assert "cfdi.tenant_rfc_missing" in codes(r)


def test_an_invoice_without_a_buyer_rfc_gets_a_warning_and_the_proposals(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    (doc,) = invoice.purchases
    unaddressed = invoice.model_copy(
        update={"purchases": [doc.model_copy(update={"buyer_rfc": None})]}
    )
    r = load(conn, unaddressed, source_id=source)
    assert r.status == "parsed" and len(r.pending_change_ids) == 2
    assert "cfdi.buyer_rfc_missing" in codes(r)


def test_a_purchase_load_holds_a_tenant_wide_prices_lock(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    load(conn, invoice, source_id=source)
    with psycopg.connect(os.environ["MERMIA_DB_URL"], autocommit=True) as other:
        row = other.execute(
            "select pg_try_advisory_lock(hashtextextended(%s, 0))", (f"{TENANT}:prices",)
        ).fetchone()
        assert row == (False,), "another invoice load waits for this one"
