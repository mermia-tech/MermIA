"""MR-100: the nightly dish-cost job, on the El Güero seed and a tenant in two time zones.

Each db test runs in one transaction that is rolled back (the job's per-chunk transactions are
savepoints in it). Needs MERMIA_DB_URL and the seed (supabase db reset loads it).
"""

import datetime as dt
import itertools
import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from mermia_api.costing import nightly
from mermia_api.costing.nightly import (
    MAX_CHUNK_DAYS,
    TenantFailure,
    TenantRun,
    main,
    plan_chunks,
    run_nightly_dish_costs,
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
def test_a_400_day_window_runs_in_chunks_of_at_most_31_days(
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
        chunks=13,  # 12 x 31 + 28
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


def test_plan_chunks_walks_back_from_today_in_31_day_steps() -> None:
    to = dt.date(2026, 10, 12)

    chunks = plan_chunks(to - dt.timedelta(days=61), to)

    assert chunks == [
        (to - dt.timedelta(days=30), to),
        (to - dt.timedelta(days=61), to - dt.timedelta(days=31)),
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
        main([*argv, "--db-url", "postgresql://nowhere"])
    assert exit_.value.code == 2


def test_the_cli_needs_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERMIA_DB_URL", raising=False)
    assert main([]) == 2
