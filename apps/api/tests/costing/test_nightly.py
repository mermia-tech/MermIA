"""MR-100: the nightly dish-cost job, on the El Güero seed and a tenant in two time zones.

Each db test runs in one transaction that is rolled back (the job's per-chunk transactions are
savepoints in it). Needs MERMIA_DB_URL and the seed (supabase db reset loads it).
"""

import datetime as dt
import itertools
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from mermia_api.costing import nightly
from mermia_api.costing.nightly import (
    JOB_LOCK_KEY,
    MAX_CHUNK_DAYS,
    NightlyResult,
    ServiceRoleError,
    TenantFailure,
    TenantRun,
    UnknownTenantError,
    become_service_role,
    main,
    plan_chunks,
    refresh_tenant,
    run_job,
    run_nightly_dish_costs,
    try_job_lock,
)

SEED = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
SEED_TODAY = "2026-10-12"

Row = tuple[Any, ...]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        c.execute("delete from public.dish_cost_snapshot")  # a day nobody approved anything
        yield c


@pytest.fixture
def job_conn(conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> str:
    """run_job and refresh_tenant connect to the test's rolled-back transaction; returns the URL.

    The job lock is a session lock: it is released when the fixture's connection closes."""

    @contextmanager
    def connect(_url: str) -> Iterator[psycopg.Connection[Any]]:
        yield conn

    monkeypatch.setattr(nightly, "_connect", connect)
    return os.environ["MERMIA_DB_URL"]


def summary_lines(caplog: pytest.LogCaptureFixture, prefix: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


def add_two_zone_tenant(conn: psycopg.Connection[Any]) -> tuple[UUID, UUID]:
    """A tenant at UTC+14 and UTC-11 (always on different days): two active dishes and one inactive
    one, each with a recipe and a menu price at both locations. Returns (tenant, inactive dish)."""
    tenant, ingredient = uuid4(), uuid4()
    dishes = [uuid4(), uuid4(), uuid4()]
    conn.execute("insert into public.tenant (id, name) values (%s, 'two zones')", (tenant,))
    conn.execute(
        """insert into public.location (tenant_id, name, timezone)
           values (%s, 'Kiritimati', 'Pacific/Kiritimati'),
                  (%s, 'Pago Pago', 'Pacific/Pago_Pago')""",
        (tenant, tenant),
    )
    conn.execute(
        "insert into public.ingredient (id, tenant_id, name, base_unit) "
        "values (%s, %s, 'harina', 'g')",
        (ingredient, tenant),
    )
    conn.execute(
        """insert into public.ingredient_price
             (tenant_id, ingredient_id, unit_price_net, effective_from, source)
           values (%s, %s, 0.1, current_date - 60, 'cfdi')""",
        (tenant, ingredient),
    )
    for n, dish in enumerate(dishes):
        conn.execute(
            "insert into public.menu_item (id, tenant_id, name, is_active) values (%s, %s, %s, %s)",
            (dish, tenant, f"plato {n}", n < 2),
        )
        recipe = conn.execute(
            """insert into public.recipe
                 (tenant_id, menu_item_id, recipe_version, status, yield_qty)
               values (%s, %s, 1, 'confirmed', 1) returning id""",
            (tenant, dish),
        ).fetchone()
        assert recipe is not None
        conn.execute(
            """insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base)
               values (%s, %s, %s, 100)""",
            (tenant, recipe[0], ingredient),
        )
        conn.execute(
            """insert into public.menu_item_price
                 (tenant_id, location_id, menu_item_id, price_gross, tax_rate, effective_from)
               select %s, l.id, %s, 5000, 0.16, current_date - 60
               from public.location l where l.tenant_id = %s""",
            (tenant, dish, tenant),
        )
    return tenant, dishes[2]


def today_rows(conn: psycopg.Connection[Any], tenant: UUID) -> set[Row]:
    """Each location's rows on its own business today."""
    rows = conn.execute(
        """select s.menu_item_id, s.location_id, s.date, s.cost, s.price_net, s.margin,
                  s.food_cost_pct, s.confidence::text
           from public.dish_cost_snapshot s
           where s.tenant_id = %s and s.date = app.business_today(s.location_id)""",
        (tenant,),
    ).fetchall()
    return set(rows)


def engine_today_rows(conn: psycopg.Connection[Any], tenant: UUID) -> set[Row]:
    """What app.compute_dish_costs writes on each location's today (its rows are then dropped)."""
    conn.execute("reset role")  # the job's `set local role` outlives its savepoint in a test
    conn.execute("savepoint engine")
    conn.execute(
        "select app.compute_dish_costs(%s, t.first_day, t.last_day) from app.tenant_days(%s) t",
        (tenant, tenant),
    )
    rows = today_rows(conn, tenant)
    conn.execute("rollback to savepoint engine")
    return rows


def snapshot_ids(conn: psycopg.Connection[Any], tenant: UUID) -> set[UUID]:
    rows = conn.execute(
        "select id from public.dish_cost_snapshot where tenant_id = %s", (tenant,)
    ).fetchall()
    return {r[0] for r in rows}


def boom_for(conn: psycopg.Connection[Any], tenant: UUID, errcode: str = "P0001") -> None:
    """Every snapshot insert for `tenant` raises `errcode`."""
    conn.execute(
        f"""create function pg_temp.boom() returns trigger language plpgsql as $$
              begin raise exception 'boom' using errcode = '{errcode}'; end $$;
            create trigger zz_boom before insert on public.dish_cost_snapshot
              for each row when (new.tenant_id = '{tenant}')
              execute function pg_temp.boom()"""
    )


# --- db ---------------------------------------------------------------------------------------


@pytest.mark.db
def test_the_seed_gets_today_s_rows_as_the_engine_writes_them(
    conn: psycopg.Connection[Any],
) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")

    result = run_nightly_dish_costs(conn, only=[SEED])

    run = result.done[SEED]
    assert result.failed == {}
    assert (run.from_date, run.to_date) == (dt.date(2026, 10, 11), dt.date(2026, 10, 12))
    assert run.chunks == 1
    assert run.snapshots == result.snapshots > 0
    got = today_rows(conn, SEED)
    assert len(got) > 0
    assert got == engine_today_rows(conn, SEED)


@pytest.mark.db
def test_today_comes_from_the_argument(conn: psycopg.Connection[Any]) -> None:
    result = run_nightly_dish_costs(conn, today=dt.date(2026, 10, 12), days=1, only=[SEED])

    assert (result.done[SEED].from_date, result.done[SEED].to_date) == (
        dt.date(2026, 10, 12),
        dt.date(2026, 10, 12),
    )
    dates = conn.execute(
        "select distinct date from public.dish_cost_snapshot where tenant_id = %s", (SEED,)
    ).fetchall()
    assert dates == [(dt.date(2026, 10, 12),)]


@pytest.mark.db
def test_each_location_gets_its_own_today_in_two_time_zones(
    conn: psycopg.Connection[Any],
) -> None:
    tenant, _ = add_two_zone_tenant(conn)
    days = conn.execute(
        "select t.first_day, t.last_day from app.tenant_days(%s) t", (tenant,)
    ).fetchone()
    assert days is not None
    assert days[1] > days[0]  # the two locations are on different days

    result = run_nightly_dish_costs(conn, only=[tenant])

    got = today_rows(conn, tenant)
    assert len(got) == 4  # two active dishes at two locations
    assert {(r[1], r[2]) for r in got} == {
        (loc, today)
        for loc, today in conn.execute(
            "select id, app.business_today(id) from public.location where tenant_id = %s",
            (tenant,),
        ).fetchall()
    }
    assert got == engine_today_rows(conn, tenant)
    assert result.done[tenant].snapshots > 0
    beyond = conn.execute(
        """select count(*) from public.dish_cost_snapshot s
           where s.tenant_id = %s and s.date > app.business_today(s.location_id)""",
        (tenant,),
    ).fetchone()
    assert beyond == (0,)  # never past a location's own today


@pytest.mark.db
def test_an_inactive_dish_gets_no_row(conn: psycopg.Connection[Any]) -> None:
    tenant, inactive = add_two_zone_tenant(conn)

    run_nightly_dish_costs(conn, days=5, only=[tenant])

    rows = conn.execute(
        "select count(*) from public.dish_cost_snapshot where menu_item_id = %s", (inactive,)
    ).fetchone()
    assert rows == (0,)


@pytest.mark.db
def test_a_rerun_is_a_no_op_that_keeps_row_ids(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")
    first = run_nightly_dish_costs(conn, days=7, only=[SEED])
    ids = snapshot_ids(conn, SEED)

    again = run_nightly_dish_costs(conn, days=7, only=[SEED])

    assert first.snapshots > 0
    assert again.snapshots == 0
    assert again.done[SEED].chunks == 1
    assert snapshot_ids(conn, SEED) == ids


@pytest.mark.db
def test_rows_a_tap_wrote_are_kept(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")
    conn.execute("select app.compute_dish_costs(%s, %s, %s)", (SEED, SEED_TODAY, SEED_TODAY))
    tapped = snapshot_ids(conn, SEED)

    result = run_nightly_dish_costs(conn, only=[SEED])

    assert snapshot_ids(conn, SEED) >= tapped
    written = conn.execute(
        "select count(*) from public.dish_cost_snapshot where tenant_id = %s and date = %s",
        (SEED, "2026-10-11"),
    ).fetchone()
    assert written == (result.snapshots,)  # only yesterday was missing


@pytest.mark.db
def test_the_job_runs_as_service_role(conn: psycopg.Connection[Any]) -> None:
    tenant, _ = add_two_zone_tenant(conn)
    conn.execute("set local role service_role")

    result = run_nightly_dish_costs(conn, only=[tenant])

    assert result.failed == {}
    assert len(today_rows(conn, tenant)) == 4


@pytest.mark.db
def test_become_service_role_drops_the_superuser(conn: psycopg.Connection[Any]) -> None:
    become_service_role(conn)

    assert conn.execute("select current_user").fetchone() == ("service_role",)


@pytest.mark.db
def test_a_held_tenant_lock_is_transient_and_the_run_goes_on(
    conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")
    tenant, _ = add_two_zone_tenant(conn)
    monkeypatch.setattr(nightly, "LOCK_TIMEOUT", "200ms")
    with psycopg.connect(os.environ["MERMIA_DB_URL"]) as holder:
        holder.execute("select app.lock_dish_costs(%s)", (SEED,))  # held until holder rolls back

        result = run_nightly_dish_costs(conn, only=[SEED, tenant])

        holder.rollback()
    assert result.failed == {SEED: TenantFailure("55P03 LockNotAvailable", is_transient=True)}
    assert result.done[tenant].snapshots > 0


@pytest.mark.db
def test_the_job_lock_admits_one_run_at_a_time(conn: psycopg.Connection[Any]) -> None:
    with psycopg.connect(os.environ["MERMIA_DB_URL"]) as other:
        assert try_job_lock(other) is True
        assert try_job_lock(conn) is False
        other.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (JOB_LOCK_KEY,))
        other.commit()
        assert try_job_lock(conn) is True


@pytest.mark.db
def test_main_exits_0_without_running_when_another_run_holds_the_job_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    called = []
    monkeypatch.setattr(nightly, "run_nightly_dish_costs", lambda *a, **k: called.append(1))
    with psycopg.connect(url) as holder:
        assert try_job_lock(holder) is True

        assert main([]) == 0

    assert called == []


@pytest.mark.db
def test_a_failing_tenant_is_reported_and_the_others_go_on(
    conn: psycopg.Connection[Any],
) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")
    tenant, _ = add_two_zone_tenant(conn)  # created after the seed: runs after it
    boom_for(conn, SEED)

    result = run_nightly_dish_costs(conn, only=[SEED, tenant])

    assert result.failed == {SEED: TenantFailure("P0001 RaiseException", is_transient=False)}
    assert SEED not in result.done
    assert result.done[tenant].snapshots > 0
    assert snapshot_ids(conn, SEED) == set()


@pytest.mark.db
def test_a_transient_error_is_reported_as_such_and_the_others_go_on(
    conn: psycopg.Connection[Any],
) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")
    tenant, _ = add_two_zone_tenant(conn)
    boom_for(conn, SEED, errcode="40P01")

    result = run_nightly_dish_costs(conn, only=[SEED, tenant])

    assert result.failed == {SEED: TenantFailure("40P01 DeadlockDetected", is_transient=True)}
    assert result.done[tenant].snapshots > 0


@pytest.mark.db
def test_a_bug_for_one_tenant_does_not_stop_the_others(
    conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")
    tenant, _ = add_two_zone_tenant(conn)
    real = nightly._fill_chunk

    def flaky(c: psycopg.Connection[Any], t: UUID, lo: dt.date, hi: dt.date, today: Any) -> int:
        if t == SEED:
            raise RuntimeError("bug")
        return real(c, t, lo, hi, today)

    monkeypatch.setattr(nightly, "_fill_chunk", flaky)

    result = run_nightly_dish_costs(conn, only=[SEED, tenant])

    assert result.failed == {SEED: TenantFailure("unknown RuntimeError", is_transient=False)}
    assert tenant in result.done


@pytest.mark.db
def test_a_400_day_window_runs_in_chunks_of_at_most_7_days(
    conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")
    chunks: list[tuple[dt.date, dt.date]] = []
    real = nightly._fill_chunk

    def spy(c: psycopg.Connection[Any], t: UUID, lo: dt.date, hi: dt.date, today: Any) -> int:
        chunks.append((lo, hi))
        return real(c, t, lo, hi, today)

    monkeypatch.setattr(nightly, "_fill_chunk", spy)

    result = run_nightly_dish_costs(conn, days=400, only=[SEED])

    today = dt.date(2026, 10, 12)
    assert result.done[SEED] == TenantRun(
        from_date=today - dt.timedelta(days=399),
        to_date=today,
        chunks=58,  # 57 x 7 + 1
        snapshots=result.snapshots,
        seconds=result.done[SEED].seconds,
    )
    assert all((hi - lo).days < MAX_CHUNK_DAYS for lo, hi in chunks)
    assert chunks[0][1] == today  # today first
    assert chunks[-1][0] == today - dt.timedelta(days=399)
    assert all(a[0] - b[1] == dt.timedelta(days=1) for a, b in itertools.pairwise(chunks))
    oldest = conn.execute(
        "select min(date) from public.dish_cost_snapshot where tenant_id = %s", (SEED,)
    ).fetchone()
    assert oldest is not None
    assert oldest[0] >= today - dt.timedelta(days=399)


@pytest.mark.db
def test_tenants_come_only_from_the_tenant_table(conn: psycopg.Connection[Any]) -> None:
    stranger = uuid4()

    result = run_nightly_dish_costs(conn, only=[stranger])

    assert result.done == {} and result.failed == {}


@pytest.mark.db
def test_a_tenant_without_locations_has_nothing_to_do(conn: psycopg.Connection[Any]) -> None:
    tenant = uuid4()
    conn.execute("insert into public.tenant (id, name) values (%s, 'empty')", (tenant,))

    result = run_nightly_dish_costs(conn, only=[tenant])

    assert result.done[tenant] == TenantRun(None, None, 0, 0, result.done[tenant].seconds)


# --- no db ------------------------------------------------------------------------------------


def test_plan_chunks_walks_back_from_today_in_7_day_steps() -> None:
    to = dt.date(2026, 10, 12)

    chunks = plan_chunks(to - dt.timedelta(days=12), to)

    assert chunks == [
        (to - dt.timedelta(days=6), to),
        (to - dt.timedelta(days=12), to - dt.timedelta(days=7)),
    ]


def test_plan_chunks_of_a_short_window_is_one_chunk() -> None:
    to = dt.date(2026, 10, 12)
    assert plan_chunks(to - dt.timedelta(days=1), to) == [(to - dt.timedelta(days=1), to)]
    assert plan_chunks(to, to) == [(to, to)]


@pytest.mark.parametrize("days", [0, 401])
def test_days_out_of_range_are_refused(days: int) -> None:
    with pytest.raises(ValueError, match="days"):
        run_nightly_dish_costs(None, days=days)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "argv", [["--days", "0"], ["--days", "401"], ["--today", "12/10/2026"], ["--days", "x"]]
)
def test_the_cli_refuses_bad_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(argv)
    assert exit_.value.code == 2


def test_the_cli_needs_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERMIA_DB_URL", raising=False)
    assert main([]) == 2


@pytest.mark.db
def test_every_transaction_runs_as_service_role_with_a_statement_timeout(
    conn: psycopg.Connection[Any],
) -> None:
    assert conn.execute("select current_user").fetchone() != ("service_role",)

    with nightly._transaction(conn, None):
        user = conn.execute("select current_user").fetchone()
        timeout = conn.execute("show statement_timeout").fetchone()

    assert user == ("service_role",)
    assert timeout == (nightly.STATEMENT_TIMEOUT.replace("60s", "1min"),)


@pytest.mark.db
def test_a_statement_timeout_fails_the_tenant_as_permanent_and_the_run_goes_on(
    conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, _ = add_two_zone_tenant(conn)
    real = nightly._fill_chunk

    def slow(c: psycopg.Connection[Any], t: UUID, lo: dt.date, hi: dt.date, today: Any) -> int:
        if t == SEED:
            with nightly._transaction(c, today):
                # only this tenant gets a tight limit; the others keep the normal one
                c.execute("set local statement_timeout = '100ms'")
                c.execute("select pg_sleep(2)")
        return real(c, t, lo, hi, today)

    monkeypatch.setattr(nightly, "_fill_chunk", slow)

    result = run_nightly_dish_costs(conn, only=[SEED, tenant])

    # 57014 is permanent in the backfill sweep's split (it fails the same way every time)
    assert result.failed == {SEED: TenantFailure("57014 QueryCanceled", is_transient=False)}
    assert result.done[tenant].snapshots > 0


# --- run_job and refresh_tenant (MR-102) --------------------------------------------------------


@pytest.mark.db
def test_run_job_runs_nothing_while_another_session_holds_the_job_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    called = []
    monkeypatch.setattr(nightly, "run_nightly_dish_costs", lambda *a, **k: called.append(1))
    with psycopg.connect(url) as holder:
        assert try_job_lock(holder) is True

        assert run_job(url) is None

    assert called == []


@pytest.mark.db
def test_run_job_runs_as_service_role_and_logs_one_summary_line(
    job_conn: str,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    real = nightly.run_nightly_dish_costs
    users: list[Row | None] = []

    def spy(c: psycopg.Connection[Any], **kwargs: Any) -> NightlyResult:
        users.append(c.execute("select current_user").fetchone())
        return real(c, **kwargs)

    monkeypatch.setattr(nightly, "run_nightly_dish_costs", spy)
    caplog.set_level(logging.INFO, logger=nightly.__name__)

    result = run_job(job_conn, today=dt.date(2026, 10, 12))

    assert result is not None
    assert result.failed == {}
    assert result.done[SEED].snapshots > 0
    assert users == [("service_role",)]
    summary = summary_lines(caplog, "nightly dish costs on ")
    assert len(summary) == 1
    assert f"{len(result.done)} tenants, {result.snapshots} rows, 0 failed" in summary[0]


@pytest.mark.db
def test_refresh_tenant_fills_only_that_tenant_and_logs_one_summary_line(
    job_conn: str, conn: psycopg.Connection[Any], caplog: pytest.LogCaptureFixture
) -> None:
    tenant, _ = add_two_zone_tenant(conn)
    caplog.set_level(logging.INFO, logger=nightly.__name__)

    result = refresh_tenant(job_conn, tenant)

    assert set(result.done) == {tenant}
    assert result.failed == {}
    assert len(today_rows(conn, tenant)) == 4
    assert snapshot_ids(conn, SEED) == set()
    summary = summary_lines(caplog, f"dish-cost refresh for tenant {tenant} on ")
    assert len(summary) == 1
    assert f"1 tenants, {result.snapshots} rows, 0 failed" in summary[0]


@pytest.mark.db
def test_refresh_tenant_runs_while_the_hourly_job_holds_the_job_lock(
    job_conn: str, conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, _ = add_two_zone_tenant(conn)
    tried: list[int] = []
    real = nightly.try_job_lock

    def spy(c: psycopg.Connection[Any]) -> bool:
        tried.append(1)
        return real(c)

    monkeypatch.setattr(nightly, "try_job_lock", spy)
    with psycopg.connect(job_conn) as holder:
        assert try_job_lock(holder) is True

        result = refresh_tenant(job_conn, tenant)

    assert tried == []
    assert result.done[tenant].snapshots > 0


@pytest.mark.db
def test_refresh_tenant_reports_a_busy_tenant_lock_as_transient(
    job_conn: str, conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn.execute(f"set local app.today = '{SEED_TODAY}'")
    monkeypatch.setattr(nightly, "LOCK_TIMEOUT", "200ms")
    with psycopg.connect(job_conn) as holder:
        holder.execute("select app.lock_dish_costs(%s)", (SEED,))  # held until holder rolls back

        result = refresh_tenant(job_conn, SEED)

        holder.rollback()
    assert result.failed == {SEED: TenantFailure("55P03 LockNotAvailable", is_transient=True)}
    assert result.done == {}


@pytest.mark.db
def test_refresh_tenant_refuses_a_tenant_not_in_the_tenant_table(job_conn: str) -> None:
    with pytest.raises(UnknownTenantError):
        refresh_tenant(job_conn, uuid4())


def test_refresh_tenant_refuses_anything_but_a_uuid_before_connecting() -> None:
    with pytest.raises(TypeError, match="UUID"):
        refresh_tenant("postgresql://nowhere", str(SEED))  # type: ignore[arg-type]


@pytest.mark.parametrize("days", [0, 401])
def test_run_job_and_refresh_tenant_refuse_days_out_of_range_before_connecting(days: int) -> None:
    with pytest.raises(ValueError, match="days"):
        run_job("postgresql://nowhere", days=days)
    with pytest.raises(ValueError, match="days"):
        refresh_tenant("postgresql://nowhere", SEED, days=days)


@pytest.mark.db
def test_run_job_raises_when_the_session_cannot_become_service_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")

    def refuse(c: psycopg.Connection[Any]) -> None:
        raise psycopg.errors.InsufficientPrivilege("permission denied to set role")

    monkeypatch.setattr(nightly, "become_service_role", refuse)

    with pytest.raises(ServiceRoleError, match="42501 InsufficientPrivilege") as raised:
        run_job(url)

    assert "permission denied" not in str(raised.value)


def fake_run_job(
    monkeypatch: pytest.MonkeyPatch, result: NightlyResult | None
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake(db_url: str, **kwargs: Any) -> NightlyResult | None:
        calls.append(kwargs)
        return result

    monkeypatch.setenv("MERMIA_DB_URL", "postgresql://nowhere")
    monkeypatch.setattr(nightly, "run_job", fake)
    return calls


def test_main_passes_its_arguments_to_run_job_and_exits_0_when_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_run_job(monkeypatch, NightlyResult(done={}, failed={}))

    assert main(["--days", "5", "--today", "2026-10-12"]) == 0
    assert calls == [{"today": dt.date(2026, 10, 12), "days": 5}]


def test_main_exits_0_when_run_job_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run_job(monkeypatch, None)

    assert main([]) == 0


def test_main_exits_1_and_names_the_failed_tenant(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    failure = TenantFailure("55P03 LockNotAvailable", is_transient=True)
    fake_run_job(monkeypatch, NightlyResult(done={}, failed={SEED: failure}))

    assert main([]) == 1
    assert f"failed {SEED}: 55P03 LockNotAvailable (transient)" in capsys.readouterr().err


def test_main_exits_1_when_the_session_cannot_become_service_role(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MERMIA_DB_URL", "postgresql://nowhere")

    def refuse(db_url: str, **kwargs: Any) -> None:
        raise ServiceRoleError("cannot switch to service_role: 42501 InsufficientPrivilege")

    monkeypatch.setattr(nightly, "run_job", refuse)

    assert main([]) == 1
    assert "cannot switch to service_role: 42501" in capsys.readouterr().err
