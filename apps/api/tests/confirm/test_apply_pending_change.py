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

from mermia_api.confirm import backfill as backfill_module
from mermia_api.confirm.apply import apply_pending_change
from mermia_api.confirm.backfill import (
    MAX_BACKFILL_ATTEMPTS,
    RESUME_BATCH,
    BackfillResult,
    ResumeResult,
    UnfinishedBackfill,
    backfill_dish_costs,
    resume_unfinished_backfills,
    unfinished_backfills,
)
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


def test_a_backdated_price_is_backfilled_in_short_chunks(conn: psycopg.Connection[Any]) -> None:
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.50", "2026-09-22"))
    assert tap(conn, change, OWNER).code is ApplyCode.applied

    assert change in unfinished_ids(conn)

    first = backfill_dish_costs(conn, change)
    again = backfill_dish_costs(conn, change)

    # 2026-09-22 .. 2026-10-11 (today was done by the tap): 20 days in chunks of 7, 7 and 6
    assert first.chunks == 3
    assert first.snapshots > 0
    assert again == BackfillResult(chunks=0, snapshots=0)  # done: a rerun does nothing
    assert change not in unfinished_ids(conn)
    cost = count(
        conn,
        "select cost from public.dish_cost_snapshot where menu_item_id = %s "
        "and location_id = %s and date = '2026-09-23'",
        PASTOR,
        CENTRO,
    )
    assert cost > 0


def test_nothing_to_backfill_for_a_batch(conn: psycopg.Connection[Any]) -> None:
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

    assert backfill_dish_costs(conn, approve) == BackfillResult(chunks=0, snapshots=0)
    assert backfill_record(conn, approve) is None


def unfinished_ids(conn: psycopg.Connection[Any]) -> list[UUID]:
    return [b.pending_change_id for b in unfinished_backfills(conn)]


def backfill_record(conn: psycopg.Connection[Any], change: UUID) -> tuple[Any, ...] | None:
    return conn.execute(
        "select from_date, to_date, next_before, done_at is not null "
        "from public.dish_cost_backfill where pending_change_id = %s",
        (change,),
    ).fetchone()


def test_a_backfill_cut_short_resumes_where_it_stopped(conn: psycopg.Connection[Any]) -> None:
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.50", "2026-09-22"))
    assert tap(conn, change, OWNER).code is ApplyCode.applied
    # one chunk commits, then the process dies (a deploy): the record keeps its place
    conn.execute("select app.backfill_dish_costs(%s)", (change,))
    assert backfill_record(conn, change) == (
        dt.date(2026, 9, 22),
        dt.date(2026, 10, 11),
        dt.date(2026, 10, 5),
        False,
    )

    resumed = resume_unfinished_backfills(conn)

    # the 13 days left, 2026-09-22 .. 2026-10-04, in chunks of 7 and 6
    assert resumed.done[change].chunks == 2
    assert change not in resumed.failed
    assert backfill_record(conn, change) == (
        dt.date(2026, 9, 22),
        dt.date(2026, 10, 11),
        dt.date(2026, 9, 22),
        True,
    )
    assert change not in unfinished_ids(conn)


def test_a_failing_backfill_is_reported_and_left_unfinished(conn: psycopg.Connection[Any]) -> None:
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.50", "2026-09-22"))
    assert tap(conn, change, OWNER).code is ApplyCode.applied
    conn.execute(
        """create function pg_temp.boom() returns trigger language plpgsql as $$
             begin raise exception 'boom' using errcode = 'P0001'; end $$;
           create trigger zz_boom after insert on public.dish_cost_snapshot
             for each row execute function pg_temp.boom()"""
    )

    resumed = resume_unfinished_backfills(conn)

    assert "boom" in resumed.failed[change]
    assert change not in resumed.done
    assert unfinished_backfills(conn)[0] == UnfinishedBackfill(change, 1, "P0001 RaiseException")
    assert backfill_record(conn, change) == (
        dt.date(2026, 9, 22),
        dt.date(2026, 10, 11),
        dt.date(2026, 10, 12),
        False,
    )


def test_a_change_that_is_not_applied_is_not_backfilled(conn: psycopg.Connection[Any]) -> None:
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.50", "2026-09-22"))

    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
        backfill_dish_costs(conn, change)


def test_a_transient_error_escapes_and_leaves_the_change_pending(
    conn: psycopg.Connection[Any],
) -> None:
    conn.execute(
        """create function pg_temp.deadlock() returns trigger language plpgsql as $$
           begin raise exception 'deadlock' using errcode = '40P01'; end $$;
           create trigger zz_deadlock after insert on public.ingredient_price
             for each row execute function pg_temp.deadlock()"""
    )
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.30"))

    with pytest.raises(psycopg.errors.DeadlockDetected):
        tap(conn, change, OWNER)

    status = conn.execute(
        "select status::text from public.pending_change where id = %s", (change,)
    ).fetchone()
    assert status == ("pending",)


def test_a_recipe_change_without_resolved_lines_fails(conn: psycopg.Connection[Any]) -> None:
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


def add_poisoned_backfills(
    conn: psycopg.Connection[Any], how_many: int, errcode: str = "P0001"
) -> list[UUID]:
    """Backfill records whose chunk always fails: a trigger raises P0001 when it moves the record
    (only for from_date 2025-01-01, which no healthy backfill here uses)."""
    conn.execute(
        f"""create function pg_temp.poison() returns trigger language plpgsql as $$
             begin raise exception 'poison' using errcode = '{errcode}'; end $$;
           create trigger zz_poison before update on public.dish_cost_backfill
             for each row
             when (old.from_date = date '2025-01-01' and new.next_before <> old.next_before)
             execute function pg_temp.poison()"""
    )
    conn.execute(
        """create temp table poison_ids as
           select app.uuid_v7() as id from generate_series(1, %s)""",
        (how_many,),
    )
    conn.execute(
        """insert into public.pending_change
             (id, tenant_id, kind, proposed_via, status, created_at)
           select id, %s, 'ingredient_price.set', 'agent', 'pending', now() - interval '1 day'
           from poison_ids""",
        (TENANT,),
    )
    rows = conn.execute(
        """insert into public.dish_cost_backfill
             (tenant_id, pending_change_id, from_date, to_date, next_before, created_at)
           select %s, id, '2025-01-01', '2025-01-07', '2025-01-08', now() - interval '1 day'
           from poison_ids returning pending_change_id""",
        (TENANT,),
    ).fetchall()
    return [UUID(str(r[0])) for r in rows]


def test_a_poisoned_backfill_is_given_up_after_five_attempts(
    conn: psycopg.Connection[Any],
) -> None:
    (poisoned,) = add_poisoned_backfills(conn, 1)

    for attempt in range(1, MAX_BACKFILL_ATTEMPTS + 1):
        assert poisoned in resume_unfinished_backfills(conn).failed
        row = conn.execute(
            "select attempts, last_error from public.dish_cost_backfill "
            "where pending_change_id = %s",
            (poisoned,),
        ).fetchone()
        assert row == (attempt, "P0001 RaiseException")

    assert resume_unfinished_backfills(conn) == ResumeResult(done={}, failed={})  # skipped now
    assert unfinished_backfills(conn, include_given_up=False) == []
    (listed,) = unfinished_backfills(conn)  # but still listed, marked
    assert listed.pending_change_id == poisoned
    assert listed.is_given_up


def test_poisoned_backfills_do_not_block_a_newer_healthy_one(
    conn: psycopg.Connection[Any],
) -> None:
    add_poisoned_backfills(conn, RESUME_BATCH + 1)
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.50", "2026-10-05"))
    assert tap(conn, change, OWNER).code is ApplyCode.applied  # created now: newer than the rest

    first = resume_unfinished_backfills(conn)  # the 100 oldest poisoned fill the batch
    assert change not in first.done
    assert len(first.failed) == RESUME_BATCH

    second = resume_unfinished_backfills(conn)  # the failed ones moved behind: the healthy runs
    assert change in second.done
    assert backfill_record(conn, change) is not None
    assert change not in unfinished_ids(conn)

    # 101 records x 5 attempts, 100 per sweep: all are given up within 6 more sweeps
    for _ in range(6):
        resume_unfinished_backfills(conn)
    assert resume_unfinished_backfills(conn) == ResumeResult(done={}, failed={})
    assert all(b.is_given_up for b in unfinished_backfills(conn, limit=500))


def test_a_transient_error_in_the_sweep_does_not_count_an_attempt(
    conn: psycopg.Connection[Any],
) -> None:
    change = propose(conn, PendingKind.ingredient_price_set, CARNE, price("0.50", "2026-09-22"))
    assert tap(conn, change, OWNER).code is ApplyCode.applied
    conn.execute(
        """create function pg_temp.deadlock() returns trigger language plpgsql as $$
             begin raise exception 'deadlock' using errcode = '40P01'; end $$;
           create trigger zz_deadlock after insert on public.dish_cost_snapshot
             for each row execute function pg_temp.deadlock()"""
    )

    with pytest.raises(psycopg.errors.DeadlockDetected):
        resume_unfinished_backfills(conn)

    assert unfinished_backfills(conn)[0] == UnfinishedBackfill(change, 0, None)


def test_a_non_transient_operational_error_is_counted_and_the_sweep_goes_on(
    conn: psycopg.Connection[Any],
) -> None:
    """54001 (recipe nested too deep) is an OperationalError, but retrying never fixes it."""
    first, second = add_poisoned_backfills(conn, 2, errcode="54001")

    result = resume_unfinished_backfills(conn)

    assert set(result.failed) == {first, second}
    rows = conn.execute(
        "select attempts, last_error from public.dish_cost_backfill "
        "where pending_change_id = any(%s)",
        ([first, second],),
    ).fetchall()
    assert rows == [(1, "54001 StatementTooComplex")] * 2


def test_a_non_database_error_is_counted_and_the_sweep_goes_on(
    conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = add_poisoned_backfills(conn, 2)
    real = backfill_module.backfill_dish_costs

    def flaky(c: psycopg.Connection[Any], change: UUID, **kw: Any) -> BackfillResult:
        if change == first:
            raise RuntimeError("bug")
        return real(c, change, **kw)

    monkeypatch.setattr(backfill_module, "backfill_dish_costs", flaky)

    result = resume_unfinished_backfills(conn, only=[first, second])

    assert set(result.failed) == {first, second}
    row = conn.execute(
        "select attempts, last_error from public.dish_cost_backfill where pending_change_id = %s",
        (first,),
    ).fetchone()
    assert row == (1, "unknown RuntimeError")


@pytest.mark.parametrize(
    ("sqlstate", "is_transient"),
    [("53100", True), ("58030", True), ("53200", False), ("54001", False), ("08006", True)],
)
def test_sqlstate_classification(
    conn: psycopg.Connection[Any], sqlstate: str, is_transient: bool
) -> None:
    error = psycopg.errors.lookup(sqlstate)("x")
    assert backfill_module._is_transient(conn, error) is is_transient


def test_a_failure_count_survives_the_chunk_rollback_on_a_real_connection() -> None:
    """Commits for real. A trigger (only for from_date 2024-02-02, which nothing else uses) makes
    the chunk fail inside its transaction, which rolls back; the attempt count is still there
    afterwards. The trigger, its function and the record are dropped at the end (the pending
    change stays: the audit log is append-only)."""
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c:
        change = propose(c, PendingKind.ingredient_price_set, CARNE, price("0.32", "2099-01-01"))
        c.execute("drop trigger if exists zz_test_poison on public.dish_cost_backfill")
        c.execute("delete from public.dish_cost_backfill where from_date = date '2024-02-02'")
        c.execute(
            """create or replace function public.zz_test_poison()
                 returns trigger language plpgsql as $$
                 begin raise exception 'poison' using errcode = 'P0001'; end $$;
               create trigger zz_test_poison before update on public.dish_cost_backfill
                 for each row when (old.from_date = date '2024-02-02'
                                  and new.next_before <> old.next_before)
                 execute function public.zz_test_poison()"""
        )
        c.execute(
            """insert into public.dish_cost_backfill
                 (tenant_id, pending_change_id, from_date, to_date, next_before)
               values (%s, %s, '2024-02-02', '2024-02-08', '2024-02-09')""",
            (TENANT, change),
        )
    try:
        with psycopg.connect(url) as c:
            assert change in resume_unfinished_backfills(c, only=[change]).failed
        with psycopg.connect(url) as c:
            row = c.execute(
                "select attempts, last_error from public.dish_cost_backfill "
                "where pending_change_id = %s",
                (change,),
            ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == "P0001 RaiseException"
    finally:
        with psycopg.connect(url) as c:
            c.execute(
                "delete from public.dish_cost_backfill where pending_change_id = %s", (change,)
            )
            c.execute("drop trigger zz_test_poison on public.dish_cost_backfill")
            c.execute("drop function public.zz_test_poison()")
