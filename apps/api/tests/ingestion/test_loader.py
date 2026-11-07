"""MR-16: the batch loader with apply_batch / rollback_batch, on the El Güero seed.

Each test runs in one transaction that is rolled back, as a service-role-like connection
(postgres). Needs MERMIA_DB_URL and the seed (supabase db start / db reset load it).
"""

import datetime as dt
import io
import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from openpyxl import Workbook

from mermia_api.ingestion.loader import approve, load, rollback
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import Grain, NormalizedBatch

pytestmark = pytest.mark.db

SR = Path(__file__).parents[4] / "fixtures" / "sr" / "synthetic"
CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")
CENTRO_ITEMS = UUID("4d2c8a0d-96ed-5ce6-b52b-ec0b79c1d57e")
CENTRO_DAILY = UUID("1ae50354-9849-54d8-a23b-313b5019ce19")
POLANCO_ITEMS = UUID("fa8c2869-6189-5a6b-bbf3-ed0381d8a2bf")
OWNER = UUID("eb52f6ad-4d75-5b06-9881-9f68f4fb05a0")
LUPITA = UUID("240e45f0-ef48-5654-a835-8fbc70de15bc")  # manager, Centro
IVAN = UUID("23f18862-2ab3-5684-be6f-db47265e5ff9")  # manager, Polanco
DAY = dt.date


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        yield c


def report(day: str, *lines: list[Any]) -> NormalizedBatch:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for row in [
        ["Taquería El Güero - Centro"],
        ["Productos vendidos en general"],
        [f"Del {day} al {day}"],
        ["Clave", "Descripción", "Grupo", "Cantidad", "Precio", "Importe", "Descuento", "Total"],
        *lines,
        [
            None,
            "Total",
            None,
            sum(x[3] for x in lines),
            None,
            sum(x[5] for x in lines),
            sum(x[6] for x in lines),
            sum(x[7] for x in lines),
        ],
    ]:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return parse_file(out.getvalue())


PASTOR = ["P001", "Tacos al pastor (orden de 3)", "Tacos", 10, 65, 650, 0, 650]
COCA = ["P043", "Coca-Cola", "Bebidas", 4, 30, 120, 0, 120]


def item_net(conn: psycopg.Connection[Any], day: str, location: UUID = CENTRO) -> int | None:
    row = conn.execute(
        "select sum(net) from app.v_item_sales_daily where location_id = %s and business_date = %s",
        (location, day),
    ).fetchone()
    assert row is not None
    return None if row[0] is None else int(row[0])


def status(conn: psycopg.Connection[Any], batch_id: UUID) -> str:
    row = conn.execute(
        "select status::text from public.import_batch where id = %s", (batch_id,)
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_a_clean_upload_applies_and_undo_restores(conn: psycopg.Connection[Any]) -> None:
    assert item_net(conn, "2026-10-12") is None
    r = load(
        conn,
        report("12/10/2026", PASTOR, COCA),
        source_id=CENTRO_ITEMS,
        expected_day=DAY(2026, 10, 12),
    )
    assert (r.status, r.duplicate) == ("applied", False)
    assert item_net(conn, "2026-10-12") == 77000
    assert rollback(conn, r.batch_id, LUPITA) == "rolled_back"
    assert item_net(conn, "2026-10-12") is None


def test_the_same_file_twice_loads_one_set_of_rows(conn: psycopg.Connection[Any]) -> None:
    batch = report("12/10/2026", PASTOR, COCA)
    first = load(conn, batch, source_id=CENTRO_ITEMS, expected_day=DAY(2026, 10, 12))
    again = load(conn, batch, source_id=CENTRO_ITEMS, expected_day=DAY(2026, 10, 12))
    assert (again.batch_id, again.status, again.duplicate) == (first.batch_id, "applied", True)
    rows = conn.execute(
        """select count(*) from public.item_sales_agg a
           join public.import_batch b on b.id = a.batch_id
           where b.location_id = %s and a.period_from = '2026-10-12'""",
        (CENTRO,),
    ).fetchone()
    assert rows == (2,)
    assert item_net(conn, "2026-10-12") == 77000


def test_the_same_raw_file_is_a_duplicate_even_if_parsed_differently(
    conn: psycopg.Connection[Any],
) -> None:
    tenant = conn.execute(
        "select tenant_id from public.source where id = %s", (CENTRO_ITEMS,)
    ).fetchone()
    assert tenant is not None
    raw = conn.execute(
        "insert into public.raw_file (tenant_id, storage_path, sha256) "
        "values (%s, 'x', %s) returning id",
        (tenant[0], "a" * 64),
    ).fetchone()
    assert raw is not None
    first = load(conn, report("12/10/2026", PASTOR), source_id=CENTRO_ITEMS, raw_file_id=raw[0])
    again = load(
        conn, report("12/10/2026", PASTOR, COCA), source_id=CENTRO_ITEMS, raw_file_id=raw[0]
    )
    assert again.duplicate and again.batch_id == first.batch_id


def test_a_correction_waits_for_a_manager_then_supersedes(conn: psycopg.Connection[Any]) -> None:
    seeded = item_net(conn, "2026-10-11")
    batch = parse_file((SR / "productos_vendidos_L1_2026-10-11.xlsx").read_bytes())
    r = load(conn, batch, source_id=CENTRO_ITEMS, expected_day=DAY(2026, 10, 11))
    assert r.status == "needs_review"
    assert "batch.correction" in {i.code for i in r.issues}
    assert item_net(conn, "2026-10-11") == seeded, "nothing changes before approval"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        approve(conn, r.batch_id, IVAN)
    assert approve(conn, r.batch_id, LUPITA) == "applied"
    assert item_net(conn, "2026-10-11") == batch.totals.net_sales == seeded
    assert rollback(conn, r.batch_id, OWNER) == "rolled_back"
    previous = conn.execute(
        "select status::text from public.import_batch where slice_key = "
        "(select slice_key from public.import_batch where id = %s) and id <> %s",
        (r.batch_id, r.batch_id),
    ).fetchall()
    assert previous == [("applied",)], "the seeded batch is current again"


def test_an_unsliced_batch_does_not_break_the_correction_check(
    conn: psycopg.Connection[Any],
) -> None:
    """MR-80: a batch with no location gets the slice key `unsliced:<digest>`, which has no dates.
    The correction check casts parts of slice_key to dates; Postgres does not promise to test the
    key's shape first, so the cast must sit inside a CASE. The row passes every other filter (same
    location, applied), so only that guard keeps the cast off it."""
    tenant = conn.execute(
        "select tenant_id from public.source where id = %s", (CENTRO_ITEMS,)
    ).fetchone()
    assert tenant is not None
    conn.execute(
        """insert into public.import_batch (tenant_id, source_id, location_id, parser, slice_key,
                                            status)
           values (%s, %s, %s, 'sr.productos_vendidos@v1', %s, 'applied')""",
        (tenant[0], CENTRO_ITEMS, CENTRO, "unsliced:" + "b" * 64),
    )
    batch = parse_file((SR / "productos_vendidos_L1_2026-10-11.xlsx").read_bytes())
    r = load(conn, batch, source_id=CENTRO_ITEMS, expected_day=DAY(2026, 10, 11))
    assert (r.status, [i.code for i in r.issues]) == ("needs_review", ["batch.correction"])


def test_the_wrong_day_goes_to_review(conn: psycopg.Connection[Any]) -> None:
    r = load(
        conn, report("12/10/2026", PASTOR), source_id=CENTRO_ITEMS, expected_day=DAY(2026, 10, 13)
    )
    assert r.status == "needs_review"
    assert [i.code for i in r.issues] == ["period.unexpected"]
    assert item_net(conn, "2026-10-12") is None


def test_another_location_s_report_goes_to_review(conn: psycopg.Connection[Any]) -> None:
    r = load(conn, report("12/10/2026", PASTOR), source_id=POLANCO_ITEMS)
    assert (r.status, [i.code for i in r.issues]) == ("needs_review", ["location.mismatch"])


def test_totals_that_do_not_add_up_are_rejected_without_rows(conn: psycopg.Connection[Any]) -> None:
    good = report("12/10/2026", PASTOR, COCA)
    bad = good.model_copy(update={"totals": good.totals.model_copy(update={"net_sales": 1})})
    r = load(conn, bad, source_id=CENTRO_ITEMS)
    assert (r.status, [i.code for i in r.issues]) == ("rejected", ["batch.totals_mismatch"])
    assert conn.execute(
        "select count(*) from public.item_sales_agg where batch_id = %s", (r.batch_id,)
    ).fetchone() == (0,)
    issues = conn.execute(
        "select code from public.import_issue where batch_id = %s", (r.batch_id,)
    ).fetchall()
    assert issues == [("batch.totals_mismatch",)]


def test_an_unsupported_grain_is_rejected(conn: psycopg.Connection[Any]) -> None:
    good = report("12/10/2026", PASTOR)
    r = load(conn, good.model_copy(update={"grain": Grain.purchase}), source_id=CENTRO_ITEMS)
    assert r.status == "rejected" and "batch.grain_unsupported" in {i.code for i in r.issues}


def test_new_items_are_created_and_existing_ones_are_not_changed(
    conn: psycopg.Connection[Any],
) -> None:
    new = ["P999", "Taco de canasta", "Tacos", 3, 20, 60, 0, 60]
    r = load(conn, report("12/10/2026", COCA, new), source_id=CENTRO_ITEMS)
    assert r.status == "applied"
    rows = dict(
        conn.execute(
            "select external_id, kind::text from public.menu_item "
            "where external_id in ('P043', 'P999')"
        ).fetchall()
    )
    assert rows == {"P043": "drink", "P999": "dish"}, "Coca-Cola keeps its catalog kind"
    count = conn.execute(
        "select count(*) from public.menu_item where external_id = 'P043'"
    ).fetchone()
    assert count == (1,)


def week_net(conn: psycopg.Connection[Any]) -> tuple[Any, ...] | None:
    return conn.execute(
        """select sum(net_sales), count(*) from app.v_daily_sales where location_id = %s
           and business_date between '2026-10-05' and '2026-10-11'""",
        (CENTRO,),
    ).fetchone()


def test_a_weekly_report_over_loaded_days_waits_for_review(conn: psycopg.Connection[Any]) -> None:
    week = NormalizedBatch.model_validate_json(
        (SR / "ventas_por_dia_L1_2026-10-05.golden.json").read_text()
    )
    first = week.daily_sales[0]
    changed = week.model_copy(
        update={
            "daily_sales": [
                first.model_copy(update={"net_sales": first.net_sales + 100000}),
                *week.daily_sales[1:],
            ],
            "totals": week.totals.model_copy(
                update={"net_sales": (week.totals.net_sales or 0) + 100000}
            ),
        }
    )
    assert week_net(conn) == (Decimal(18432050), 7)
    r = load(conn, changed, source_id=CENTRO_DAILY)
    assert (r.status, [i.code for i in r.issues]) == ("needs_review", ["batch.correction"])
    assert week_net(conn) == (Decimal(18432050), 7), "the overlapping week does not apply alone"
    approve(conn, r.batch_id, LUPITA)
    assert week_net(conn) == (Decimal(18532050), 7), "approved: each day counts once, from it"
    rollback(conn, r.batch_id, LUPITA)
    assert week_net(conn) == (Decimal(18432050), 7), "undone: the daily batches count again"


def test_a_multi_day_item_report_is_rejected(conn: psycopg.Connection[Any]) -> None:
    one = report("12/10/2026", PASTOR)
    rows = [x.model_copy(update={"period_to": dt.date(2026, 10, 18)}) for x in one.item_sales]
    week = one.model_copy(
        update={
            "item_sales": rows,
            "period": one.period.model_copy(update={"to": dt.date(2026, 10, 18)}),
        }
    )
    r = load(conn, week, source_id=CENTRO_ITEMS)
    assert r.status == "rejected" and "batch.items_multi_day" in {i.code for i in r.issues}


def test_another_location_s_code_for_another_dish_is_not_reused(
    conn: psycopg.Connection[Any],
) -> None:
    horchata_p001 = ["P001", "Agua de horchata grande", "Bebidas", 5, 30, 150, 0, 150]
    r = load(conn, report("12/10/2026", horchata_p001), source_id=CENTRO_ITEMS)
    assert r.status == "needs_review"
    assert "item.code_name_mismatch" in {i.code for i in r.issues}
    booked = conn.execute(
        """select m.name from public.item_sales_agg a
           join public.menu_item m on m.id = a.menu_item_id
           where a.batch_id = %s""",
        (r.batch_id,),
    ).fetchall()
    assert booked == [("Agua de horchata grande",)], "not booked to Tacos al pastor"


def test_negative_quantities_wait_for_review(conn: psycopg.Connection[Any]) -> None:
    refund = ["P043", "Coca-Cola", "Bebidas", -1, 30, -30, 0, -30]  # one row per item (MR-15)
    r = load(conn, report("12/10/2026", PASTOR, refund), source_id=CENTRO_ITEMS)
    assert (r.status, [i.code for i in r.issues]) == ("needs_review", ["rows.negative"])


def test_the_same_file_twice_at_once_applies_one_batch() -> None:
    """Two connections load the same file at the same moment (email and WhatsApp): the advisory
    lock in load() serializes them, so the second meets the duplicate check instead of the unique
    index on applied slices. Commits for real, so it undoes its batch at the end."""
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    batch = report("13/10/2026", PASTOR, COCA)
    gate = threading.Barrier(2)

    def upload() -> tuple[UUID, str, bool]:
        # lock_timeout: a deadlock or a stuck lock fails the test instead of hanging it
        with psycopg.connect(url, options="-c lock_timeout=10s") as c:
            gate.wait(timeout=10)
            r = load(c, batch, source_id=CENTRO_ITEMS, expected_day=DAY(2026, 10, 13))
            return r.batch_id, r.status, r.duplicate

    try:
        with ThreadPoolExecutor(2) as pool:
            results = [f.result(timeout=30) for f in [pool.submit(upload) for _ in range(2)]]
        with psycopg.connect(url) as c:
            assert item_net(c, "2026-10-13") == 77000
            applied = c.execute(
                "select id from public.import_batch where source_id = %s and status = 'applied' "
                "and slice_key like %s",
                (CENTRO_ITEMS, "%:2026-10-13:2026-10-13"),
            ).fetchall()
        assert len(applied) == 1
        assert sorted(results, key=lambda r: r[2]) == [
            (applied[0][0], "applied", False),
            (applied[0][0], "applied", True),
        ]
    finally:
        with psycopg.connect(url) as c:
            for (batch_id,) in c.execute(
                "select id from public.import_batch where source_id = %s and status = 'applied' "
                "and slice_key like %s",
                (CENTRO_ITEMS, "%:2026-10-13:2026-10-13"),
            ).fetchall():
                rollback(c, batch_id, LUPITA)
            # the audit log keeps the batches; their rows go so the seed counts (60_seed) hold
            c.execute(
                "delete from public.item_sales_agg where batch_id in (select id from "
                "public.import_batch where source_id = %s and slice_key like %s)",
                (CENTRO_ITEMS, "%:2026-10-13:2026-10-13"),
            )
