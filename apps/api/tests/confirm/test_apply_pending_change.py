"""MR-32: apply_pending_change through the Python seam, on the El Güero seed.

Each test runs in one transaction that is rolled back, as a service-role-like connection
(postgres), except the concurrent double tap, which commits and cleans up after itself.
Needs MERMIA_DB_URL and the seed (supabase db start / db reset load it).
"""

import datetime as dt
import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

from mermia_api.confirm.apply import apply_pending_change
from mermia_contracts.db.models import PendingChangeStatus
from mermia_contracts.pending import (
    TARGET_TYPE,
    ApplyCode,
    ApplyPendingChangeArgs,
    ApplyResult,
    PendingKind,
)

pytestmark = pytest.mark.db

TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")
OWNER = UUID("eb52f6ad-4d75-5b06-9881-9f68f4fb05a0")
LUPITA = UUID("240e45f0-ef48-5654-a835-8fbc70de15bc")  # manager, Centro, imports only
PASTOR = UUID("f496f051-9f85-5f8a-a4b6-c1a814d37c73")  # menu item P001
CARNE = UUID("356dfff4-d912-542b-b8b0-8ae42068eb7e")  # ingredient "Carne al pastor"
SEEDED_CENTRO = UUID("18005b12-2cda-54d0-a6d4-08900bd031ae")
TODAY = "2026-10-12"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        c.execute(f"set local app.today = '{TODAY}'")
        yield c


def propose(
    conn: psycopg.Connection[Any],
    kind: PendingKind,
    target_id: UUID,
    payload: dict[str, Any],
    *,
    expires_in: dt.timedelta = dt.timedelta(days=1),
) -> UUID:
    row = conn.execute(
        """insert into public.pending_change
             (tenant_id, kind, target_type, target_id, base_version, payload,
              proposed_by_user, proposed_via, expires_at)
           values (%s, %s, %s, %s, app.pending_base_version(%s, %s, %s), %s, %s, 'agent',
                   now() + %s)
           returning id""",
        (
            TENANT,
            kind.value,
            TARGET_TYPE[kind],
            target_id,
            kind.value,
            target_id,
            Jsonb(payload),
            Jsonb(payload),
            OWNER,
            expires_in,
        ),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def tap(conn: psycopg.Connection[Any], change: UUID, user: UUID) -> ApplyResult:
    return apply_pending_change(conn, ApplyPendingChangeArgs(id=change, user_id=user))


def price(unit_price: str, effective_from: str = TODAY) -> dict[str, Any]:
    return {"unit_price": unit_price, "effective_from": effective_from, "source": "manual"}


def count(conn: psycopg.Connection[Any], sql: str, *args: Any) -> int:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return int(row[0])


def test_a_price_change_applies_once(conn: psycopg.Connection[Any]) -> None:
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.30"))

    first = tap(conn, change, OWNER)
    second = tap(conn, change, OWNER)

    assert (first.code, first.status, first.ok) == (
        ApplyCode.applied,
        PendingChangeStatus.applied,
        True,
    )
    assert (second.code, second.status, second.ok) == (
        ApplyCode.already_applied,
        PendingChangeStatus.applied,
        True,
    )
    assert (
        count(
            conn,
            "select count(*) from public.ingredient_price where pending_change_id = %s",
            change,
        )
        == 1
    )
    assert (
        count(
            conn,
            "select count(*) from public.audit_log where pending_change_id = %s "
            "and action = 'pending_change.apply'",
            change,
        )
        == 1
    )


def test_a_menu_price_change_writes_the_location_price(conn: psycopg.Connection[Any]) -> None:
    change = propose(
        conn,
        PendingKind.menu_item_price_set,
        PASTOR,
        {"price_gross": 9000, "location_id": str(CENTRO), "effective_from": TODAY},
    )

    assert tap(conn, change, OWNER).code is ApplyCode.applied
    assert (
        count(
            conn,
            "select price_gross from public.menu_item_price where menu_item_id = %s "
            "and location_id = %s and effective_from = %s",
            PASTOR,
            CENTRO,
            TODAY,
        )
        == 9000
    )


def test_a_batch_is_approved_and_rolled_back(conn: psycopg.Connection[Any]) -> None:
    batch = conn.execute(
        """insert into public.import_batch
             (tenant_id, source_id, location_id, parser, slice_key, status)
           select tenant_id, source_id, location_id, parser, slice_key, 'needs_review'
           from public.import_batch where id = %s returning id""",
        (SEEDED_CENTRO,),
    ).fetchone()
    assert batch is not None
    approve = propose(conn, PendingKind.import_batch_approve, batch[0], {})

    assert tap(conn, approve, LUPITA).code is ApplyCode.applied
    undo = propose(conn, PendingKind.import_batch_rollback, batch[0], {})
    assert tap(conn, undo, LUPITA).code is ApplyCode.applied

    status = conn.execute(
        "select status::text from public.import_batch where id = %s", batch
    ).fetchone()
    assert status == ("rolled_back",)


def test_a_refusal_changes_nothing(conn: psycopg.Connection[Any]) -> None:
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.30"))

    result = tap(conn, change, LUPITA)  # a manager approves imports only

    assert (result.code, result.status, result.ok) == (
        ApplyCode.forbidden_role,
        PendingChangeStatus.pending,
        False,
    )
    assert (
        count(
            conn,
            "select count(*) from public.ingredient_price where pending_change_id = %s",
            change,
        )
        == 0
    )


def test_a_stranger_or_an_unknown_id_learns_nothing(conn: psycopg.Connection[Any]) -> None:
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.30"))
    stranger = UUID("eeeeeeee-0000-7000-8000-000000000003")
    conn.execute("insert into public.app_user (id, name) values (%s, 'Otro')", (stranger,))
    other = conn.execute("insert into public.tenant (name) values ('Otra') returning id").fetchone()
    assert other is not None
    conn.execute(
        """insert into public.membership
             (tenant_id, user_id, role, location_ids, all_locations, can_approve)
           values (%s, %s, 'owner', null, true, '{ingredient_price.set}')""",
        (other[0], stranger),
    )

    for result in (tap(conn, change, stranger), tap(conn, UUID(int=1), OWNER)):
        assert (result.code, result.status, result.message) == (ApplyCode.not_found, None, None)


@pytest.mark.parametrize(
    ("setup", "code", "status"),
    [
        ("expired", ApplyCode.expired, PendingChangeStatus.expired),
        ("moved", ApplyCode.conflict, PendingChangeStatus.conflict),
        ("rejected", ApplyCode.not_pending, PendingChangeStatus.rejected),
    ],
)
def test_stale_taps_get_a_clear_code(
    conn: psycopg.Connection[Any], setup: str, code: ApplyCode, status: PendingChangeStatus
) -> None:
    expires = dt.timedelta(minutes=-1) if setup == "expired" else dt.timedelta(days=1)
    change = propose(
        conn, PendingKind.ingredient_price_set, CARNE, price("0.30"), expires_in=expires
    )
    if setup == "moved":
        conn.execute(
            """insert into public.ingredient_price
                 (tenant_id, ingredient_id, unit_price_net, effective_from, source)
               values (%s, %s, 0.21, %s, 'cfdi')""",
            (TENANT, CARNE, TODAY),
        )
    if setup == "rejected":
        conn.execute(
            "update public.pending_change set status = 'rejected' where id = %s", (change,)
        )

    result = tap(conn, change, OWNER)

    assert (result.code, result.status) == (code, status)
    assert (
        count(
            conn,
            "select count(*) from public.ingredient_price where pending_change_id = %s",
            change,
        )
        == 0
    )


def test_a_recipe_change_fails_until_part_2(conn: psycopg.Connection[Any]) -> None:
    change = propose(
        conn,
        PendingKind.recipe_upsert,
        PASTOR,
        {"yield_qty": "1", "lines": [{"ingredient_name": "Carne", "qty_base": "120", "unit": "g"}]},
    )

    result = tap(conn, change, OWNER)

    assert (result.code, result.status) == (ApplyCode.failed, PendingChangeStatus.failed)


def test_a_double_tap_at_once_applies_one_change() -> None:
    """Two connections tap Confirmar at the same moment: the row lock serializes them, so exactly
    one applies and the other is already_applied. Commits for real; the price is in the future, so
    no snapshot is recomputed, and the price row is removed at the end (the change and its audit
    rows stay: the audit log is append-only)."""
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c:
        change = propose(c, PendingKind.ingredient_price_set, CARNE, price("0.31", "2099-01-01"))
    gate = threading.Barrier(2)

    def confirm() -> ApplyCode:
        # lock_timeout: a deadlock or a stuck lock fails the test instead of hanging it
        with psycopg.connect(url, options="-c lock_timeout=10s") as c:
            gate.wait(timeout=10)
            return tap(c, change, OWNER).code

    try:
        with ThreadPoolExecutor(2) as pool:
            codes = [f.result(timeout=30) for f in [pool.submit(confirm) for _ in range(2)]]
        assert sorted(codes) == [ApplyCode.already_applied, ApplyCode.applied]
        with psycopg.connect(url) as c:
            assert (
                count(
                    c,
                    "select count(*) from public.ingredient_price where pending_change_id = %s",
                    change,
                )
                == 1
            )
    finally:
        with psycopg.connect(url) as c:
            c.execute("delete from public.ingredient_price where pending_change_id = %s", (change,))
