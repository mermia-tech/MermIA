"""MR-33: the cost alert rules on the El Güero seed, through the backend's caller.

The seed has two price jumps (fixtures/README.md): carne al pastor $170 -> $195/kg on 2026-09-21
and aguacate $55 -> $89/kg on 2026-09-28. Each test runs in a transaction that is rolled back.
"""

import datetime as dt
import json
import os
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest
from pydantic import TypeAdapter

from mermia_api.costing.alerts import (
    evaluate_cost_alerts,
    evaluate_cost_alerts_range,
    tenant_today,
)
from mermia_contracts.rpc import CostAlertsData, RpcEnvelope

TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
CENTRO = "705e8e51-376b-5785-adbb-405eff4e2a22"
START = dt.date(2026, 9, 12)
TODAY = dt.date(2026, 10, 12)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        c.execute("select app.compute_dish_costs(%s, '2026-08-17', %s)", (TENANT, TODAY))
        c.execute("set local role service_role")
        yield c


@pytest.mark.db
def test_the_seed_jumps_and_breaches_are_alerted_once(conn: psycopg.Connection[Any]) -> None:
    assert evaluate_cost_alerts_range(conn, TENANT, START, TODAY, TODAY) == 19
    assert evaluate_cost_alerts_range(conn, TENANT, START, TODAY, TODAY) == 0
    assert evaluate_cost_alerts(conn, TENANT, TODAY, TODAY) == 0
    jumps = conn.execute(
        """select i.name, a.as_of, a.value, a.urgent from public.alert a
           join public.ingredient i on i.id = a.ingredient_id
           where a.rule = 'price_jump' order by a.as_of"""
    ).fetchall()
    assert jumps == [
        ("Carne al pastor (adobada)", dt.date(2026, 9, 21), Decimal("14.7059"), False),
        # a catch-up on 10-12: the 09-28 jump is 15 days old, so not urgent
        ("Aguacate Hass", dt.date(2026, 9, 28), Decimal("61.8182"), False),
    ]
    breaches = conn.execute(
        "select count(*) from public.alert where rule = 'margin_breach'"
    ).fetchone()
    assert breaches == (17,)


def _avocado_urgent(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute(
        """select a.urgent from public.alert a join public.ingredient i on i.id = a.ingredient_id
           where a.rule = 'price_jump' and i.name = 'Aguacate Hass'"""
    ).fetchone()
    assert row is not None
    return bool(row[0])


@pytest.mark.db
def test_the_daily_run_marks_a_fresh_jump_urgent(conn: psycopg.Connection[Any]) -> None:
    jump_day = dt.date(2026, 9, 28)
    assert evaluate_cost_alerts(conn, TENANT, jump_day, jump_day) > 0
    assert _avocado_urgent(conn)


@pytest.mark.db
def test_the_range_reads_the_business_today_once(conn: psycopg.Connection[Any]) -> None:
    conn.execute("set local app.today = '2026-09-30'")
    assert evaluate_cost_alerts_range(conn, TENANT, START, dt.date(2026, 9, 30)) > 0
    assert _avocado_urgent(conn)  # 3 days old on 09-30
    conn.execute("delete from public.alert")
    conn.execute("set local app.today = '2026-10-12'")
    assert evaluate_cost_alerts_range(conn, TENANT, START, dt.date(2026, 9, 30)) > 0
    assert not _avocado_urgent(conn)  # the same days caught up on 10-12


@pytest.mark.db
def test_nothing_is_applied(conn: psycopg.Connection[Any]) -> None:
    counts = (
        "select (select count(*) from public.pending_change),"
        " (select count(*) from public.menu_item_price)"
    )
    before = conn.execute(counts).fetchone()
    evaluate_cost_alerts_range(conn, TENANT, START, TODAY, TODAY)
    assert conn.execute(counts).fetchone() == before


@pytest.mark.db
def test_get_cost_alerts_keeps_its_contract(conn: psycopg.Connection[Any]) -> None:
    evaluate_cost_alerts_range(conn, TENANT, START, TODAY, TODAY)
    conn.execute("reset role")
    conn.execute("set local role authenticated")
    claims = {"tenant_id": str(TENANT), "location_ids": None}
    conn.execute("select set_config('request.jwt.claims', %s, true)", [json.dumps(claims)])
    conn.execute("set local app.today = '2026-10-12'")
    row = conn.execute(
        "select api.get_cost_alerts('\"last_30d\"'::jsonb, %s::uuid)", [CENTRO]
    ).fetchone()
    assert row is not None
    envelope = TypeAdapter(RpcEnvelope[CostAlertsData]).validate_python(row[0])
    assert envelope.ok
    moves = [(m.ingredient, m.change.raw) for m in envelope.data.price_moves]  # type: ignore[union-attr]
    assert moves == [
        ("Carne al pastor (adobada)", Decimal("14.7059")),
        ("Aguacate Hass", Decimal("61.8182")),
    ]


@pytest.mark.parametrize(
    ("start", "end"),
    [(TODAY, START), (dt.date(2025, 1, 1), TODAY)],
    ids=["reversed", "too long"],
)
def test_a_bad_range_is_refused_before_the_database(start: dt.date, end: dt.date) -> None:
    with pytest.raises(ValueError):
        evaluate_cost_alerts_range(None, TENANT, start, end)  # type: ignore[arg-type]


@pytest.mark.db
def test_the_run_writes_suggestions_the_rpc_returns(conn: psycopg.Connection[Any]) -> None:
    evaluate_cost_alerts(conn, TENANT, TODAY, TODAY)
    evaluate_cost_alerts(conn, TENANT, TODAY, TODAY)  # a rerun refreshes nothing
    rows = conn.execute(
        """select m.name, p.rationale_code, p.suggested_price, p.version
           from public.price_suggestion p join public.menu_item m on m.id = p.menu_item_id
           where p.location_id = %s order by p.value desc""",
        [CENTRO],
    ).fetchall()
    # puzzles and a dog: "revisa porción/costo"; resale and stars get nothing (U2, U4)
    assert rows == [
        ("Torta de pastor", "review_portion_cost", None, 1),
        ("Alambre de res", "review_portion_cost", None, 1),
        ("Volcán de pastor", "review_portion_cost", None, 1),
    ]
    conn.execute("reset role")
    conn.execute("set local role authenticated")
    claims = {"tenant_id": str(TENANT), "location_ids": None}
    conn.execute("select set_config('request.jwt.claims', %s, true)", [json.dumps(claims)])
    conn.execute("set local app.today = '2026-10-12'")
    row = conn.execute("select api.get_cost_alerts(location_id => %s::uuid)", [CENTRO]).fetchone()
    assert row is not None
    envelope = TypeAdapter(RpcEnvelope[CostAlertsData]).validate_python(row[0])
    suggestions = envelope.data.suggestions  # type: ignore[union-attr]
    assert [(s.name, s.target_price.raw) for s in suggestions] == [
        ("Torta de pastor", 12503),
        ("Alambre de res", 22243),
        ("Volcán de pastor", 5300),
    ]


@pytest.mark.db
def test_the_daily_run_looks_up_the_business_date_as_service_role(
    conn: psycopg.Connection[Any],
) -> None:
    conn.execute("reset app.today")
    assert isinstance(tenant_today(conn, TENANT), dt.date)
    assert evaluate_cost_alerts_range(conn, TENANT, START, START) >= 0
