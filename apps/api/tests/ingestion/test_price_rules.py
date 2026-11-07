"""MR-36: the rules that decide which CFDI prices are proposed, on the El Güero seed.

Matching, units, merging, dates and superseding. The main flow and the approval are in
test_price_import.py. Each test runs in one transaction that is rolled back. Needs MERMIA_DB_URL.
"""

import datetime as dt
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

from mermia_api.ingestion.loader import LoadResult, load
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import (
    IssueIn,
    MenuItemIn,
    NormalizedBatch,
    Period,
    PurchaseLineIn,
)
from mermia_contracts.db.models import IssueSeverity

pytestmark = pytest.mark.db

FILE = Path(__file__).parents[4] / "fixtures/cfdi/synthetic/factura_carnes_selectas_2026-10-08.xml"
TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
OWNER = UUID("eb52f6ad-4d75-5b06-9881-9f68f4fb05a0")
CARNE = UUID("356dfff4-d912-542b-b8b0-8ae42068eb7e")
HUEVO = UUID("ee6a58ea-5d52-52f8-8b8a-c4dd42d40664")
CARNES_SELECTAS = UUID("54f37bf2-0d8d-5500-8e6b-69127b7e5362")
PASTOR = "CARNE AL PASTOR (ADOBADA)"


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


def line(description: str, qty: str, unit: str, price: str) -> PurchaseLineIn:
    return PurchaseLineIn(
        description=description, qty=Decimal(qty), unit=unit, unit_price_net=Decimal(price)
    )


def edited(
    batch: NormalizedBatch,
    *lines: PurchaseLineIn,
    day: dt.date | None = None,
    hour: int | None = None,
    issues: list[IssueIn] | None = None,
) -> NormalizedBatch:
    """The invoice with other lines, date, hour or parser issues."""
    (doc,) = batch.purchases
    changes: dict[str, Any] = {"lines": list(lines)}
    update: dict[str, Any] = {"totals": batch.totals.model_copy(update={"lines": len(lines)})}
    if day is not None:
        changes["issued_at"] = doc.issued_at.replace(year=day.year, month=day.month, day=day.day)
        update["period"] = Period.model_validate({"from": day, "to": day})
    if hour is not None:
        changes["issued_at"] = changes.get("issued_at", doc.issued_at).replace(hour=hour)
    if issues is not None:
        update["issues"] = issues
    return batch.model_copy(update={**update, "purchases": [doc.model_copy(update=changes)]})


def proposed(conn: psycopg.Connection[Any], r: LoadResult, target: UUID) -> dict[str, Any] | None:
    row = conn.execute(
        """select payload, diff, status::text from public.pending_change
           where diff ->> 'batch_id' = %s and target_id = %s""",
        (str(r.batch_id), target),
    ).fetchone()
    return None if row is None else {"payload": row[0], "diff": row[1], "status": row[2]}


def price(conn: psycopg.Connection[Any], r: LoadResult, target: UUID) -> str | None:
    found = proposed(conn, r, target)
    return None if found is None else str(found["payload"]["unit_price"])


def status(conn: psycopg.Connection[Any], r: LoadResult, target: UUID) -> str | None:
    found = proposed(conn, r, target)
    return None if found is None else str(found["status"])


def codes(r: LoadResult) -> list[str]:
    return [i.code for i in r.issues]


def test_two_lines_of_one_ingredient_merge_weighted_by_quantity(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    batch = edited(invoice, line(PASTOR, "10", "KGM", "212"), line(PASTOR, "5", "KGM", "200"))
    r = load(conn, batch, source_id=source)
    assert price(conn, r, CARNE) == "0.208000"  # (2120 + 1000) / 15000 g
    found = proposed(conn, r, CARNE)
    assert found is not None and [x["row"] for x in found["diff"]["lines"]] == [1, 2]


def test_the_price_is_rounded_once_to_six_decimals_half_up(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    r = load(conn, edited(invoice, line(PASTOR, "3", "KGM", "200.0005")), source_id=source)
    assert price(conn, r, CARNE) == "0.200001"  # 0.2000005 rounds up


def test_kilos_of_eggs_are_proposed_with_a_conversion(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    conn.execute(
        """insert into public.unit_conversion (tenant_id, ingredient_id, from_unit, to_unit, factor)
           values (%s, %s, 'kg', 'pza', 16)""",
        (TENANT, HUEVO),
    )
    r = load(conn, edited(invoice, line("HUEVO", "2", "KGM", "45")), source_id=source)
    assert price(conn, r, HUEVO) == "2.812500"  # 45 / 16 eggs


def test_a_box_needs_the_alias_pack_size(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    box = edited(invoice, line("HUEVO", "1", "XBX", "720"))
    r = load(conn, box, source_id=source)
    assert price(conn, r, HUEVO) is None and codes(r) == ["cfdi.unit_pack_unknown"]
    conn.execute(
        """update public.ingredient_alias set pack_qty = 180, pack_unit = 'pza'
           where supplier_id = %s and source_text = 'HUEVO'""",
        (CARNES_SELECTAS,),
    )
    r = load(conn, box, source_id=source)  # filed nothing before: not a duplicate
    assert price(conn, r, HUEVO) == "4.000000"  # 720 / 180 eggs


def test_a_piece_uses_the_alias_pack_size(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    conn.execute(
        """update public.ingredient_alias set pack_qty = 180, pack_unit = 'pza'
           where supplier_id = %s and source_text = 'HUEVO'""",
        (CARNES_SELECTAS,),
    )
    r = load(conn, edited(invoice, line("HUEVO", "1", "H87", "720")), source_id=source)
    found = proposed(conn, r, HUEVO)
    assert found is not None and found["payload"]["unit_price"] == "4.000000"  # not 720 an egg
    assert Decimal(found["diff"]["lines"][0]["base_per_unit"]) == 180


def test_two_ingredients_with_the_line_name_hold_it(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    conn.execute(
        """insert into public.ingredient
             (tenant_id, name, base_unit, default_yield_pct, yield_source)
           values (%s, 'Cebolla  Blanca', 'g', 100, 'default')""",
        (TENANT,),
    )
    r = load(conn, edited(invoice, line("CEBOLLA BLANCA", "5", "KGM", "26")), source_id=source)
    assert (r.pending_change_ids, codes(r)) == ((), ["cfdi.ingredient_ambiguous"])


def test_an_ieps_line_is_proposed_without_the_ieps_and_marked(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    ieps = IssueIn(
        severity=IssueSeverity.warning, code="cfdi.ieps_listed", message_es="IEPS", row_ref="1"
    )
    r = load(
        conn, edited(invoice, line(PASTOR, "10", "KGM", "212"), issues=[ieps]), source_id=source
    )
    found = proposed(conn, r, CARNE)
    assert found is not None and found["diff"]["lines"][0]["ieps_excluded"] is True
    assert found["payload"]["unit_price"] == "0.212000"


def test_an_invoice_older_than_the_price_of_record_is_skipped(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    old = edited(invoice, line(PASTOR, "10", "KGM", "180"), day=dt.date(2026, 9, 1))
    r = load(conn, old, source_id=source)
    assert (r.status, r.pending_change_ids, codes(r)) == ("parsed", (), ["cfdi.price_older"])
    assert "21/09/2026" in r.issues[0].message_es


def test_a_newer_invoice_supersedes_an_older_pending_one_but_not_the_reverse(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    first = load(conn, edited(invoice, line(PASTOR, "10", "KGM", "212")), source_id=source)
    newer = edited(invoice, line(PASTOR, "10", "KGM", "220"), day=dt.date(2026, 10, 12))
    second = load(conn, newer, source_id=source)
    assert status(conn, first, CARNE) == "expired"
    assert "cfdi.pending_replaced" in codes(second)
    older = edited(invoice, line(PASTOR, "10", "KGM", "215"), day=dt.date(2026, 10, 10))
    third = load(conn, older, source_id=source)
    assert (third.pending_change_ids, codes(third)) == ((), ["cfdi.newer_pending"])
    assert status(conn, second, CARNE) == "pending"


def test_on_the_same_day_the_later_invoice_time_wins(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    late = load(conn, edited(invoice, line(PASTOR, "10", "KGM", "220"), hour=18), source_id=source)
    found = proposed(conn, late, CARNE)
    assert found is not None and found["diff"]["issued_at"] == "2026-10-08T18:15:00-06:00"
    early = edited(invoice, line(PASTOR, "10", "KGM", "215"), hour=8)
    r = load(conn, early, source_id=source)  # loaded last, but issued earlier that day
    assert (r.pending_change_ids, codes(r)) == ((), ["cfdi.newer_pending"])
    assert "18:15" in r.issues[0].message_es
    assert status(conn, late, CARNE) == "pending"


def test_a_second_invoice_with_the_same_price_is_already_pending(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    first = load(conn, edited(invoice, line(PASTOR, "10", "KGM", "212")), source_id=source)
    other = edited(invoice, line(PASTOR, "4", "KGM", "212"), hour=11)
    r = load(conn, other, source_id=source)
    assert (r.duplicate, r.pending_change_ids, codes(r)) == (False, (), [])
    stats = conn.execute(
        "select stats ->> 'already_pending' from public.import_batch where id = %s", (r.batch_id,)
    )
    assert stats.fetchone() == ("1",)
    assert status(conn, first, CARNE) == "pending"


def test_only_cfdi_imports_count_as_newer_or_are_superseded(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    payload = {"unit_price": "0.300000", "effective_from": "2026-10-20", "source": "manual"}
    diff = {"parser": "otro.reporte@v1", "issued_at": "2026-10-20T10:00:00-06:00"}
    row = conn.execute(
        """insert into public.pending_change
             (tenant_id, kind, target_type, target_id, base_version, payload, diff, proposed_via,
              expires_at)
           values (%s, 'ingredient_price.set', 'ingredient', %s, 2, %s, %s, 'import',
                   now() + interval '1 day') returning id""",
        (TENANT, CARNE, Jsonb(payload), Jsonb(diff)),
    ).fetchone()
    assert row is not None
    r = load(conn, edited(invoice, line(PASTOR, "10", "KGM", "212")), source_id=source)
    assert status(conn, r, CARNE) == "pending" and "cfdi.newer_pending" not in codes(r)
    other = conn.execute("select status::text from public.pending_change where id = %s", row)
    assert other.fetchone() == ("pending",)


def test_an_agent_proposal_is_never_superseded(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    payload = {"unit_price": "0.300000", "effective_from": "2026-10-08", "source": "manual"}
    row = conn.execute(
        """insert into public.pending_change
             (tenant_id, kind, target_type, target_id, base_version, payload, proposed_via,
              expires_at)
           values (%s, 'ingredient_price.set', 'ingredient', %s, 2, %s, 'agent',
                   now() + interval '1 day') returning id""",
        (TENANT, CARNE, Jsonb(payload)),
    ).fetchone()
    assert row is not None
    load(conn, edited(invoice, line(PASTOR, "10", "KGM", "212")), source_id=source)
    status = conn.execute("select status::text from public.pending_change where id = %s", row)
    assert status.fetchone() == ("pending",)


def test_an_unchanged_price_expires_an_older_pending_import(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    first = load(conn, edited(invoice, line(PASTOR, "10", "KGM", "212")), source_id=source)
    same = edited(invoice, line(PASTOR, "10", "KGM", "195"), day=dt.date(2026, 10, 9))
    second = load(conn, same, source_id=source)
    assert status(conn, first, CARNE) == "expired"
    assert (second.pending_change_ids, codes(second)) == ((), ["cfdi.pending_replaced"])


def test_a_purchase_batch_with_menu_items_is_rejected(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    mixed = invoice.model_copy(update={"menu_items": [MenuItemIn(name="Taco")]})
    r = load(conn, mixed, source_id=source)
    assert r.status == "rejected" and "batch.grain_mismatch" in codes(r)


def test_purchase_totals_must_match_the_invoice_lines(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    bad = invoice.model_copy(update={"totals": invoice.totals.model_copy(update={"lines": 5})})
    r = load(conn, bad, source_id=source)
    assert r.status == "rejected" and "batch.totals_mismatch" in codes(r)


def test_an_invoice_dated_outside_the_period_is_rejected(
    conn: psycopg.Connection[Any], source: UUID, invoice: NormalizedBatch
) -> None:
    day = dt.date(2026, 10, 9)
    shifted = invoice.model_copy(update={"period": Period.model_validate({"from": day, "to": day})})
    r = load(conn, shifted, source_id=source)
    assert r.status == "rejected" and "batch.rows_outside_period" in codes(r)
