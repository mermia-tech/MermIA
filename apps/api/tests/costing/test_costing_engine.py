"""MR-25: app.compute_dish_costs against the hand-calculated values in fixtures/el_guero.

expected.json is computed in Python by the fixture generator (packages/fixtures build.py) with
the README Definitions; the engine computes the same figures in SQL from the seeded recipes,
prices and menu prices. Each test runs in a transaction that is rolled back.
"""

import json
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest

pytestmark = pytest.mark.db

EXPECTED = json.loads(
    (Path(__file__).parents[4] / "fixtures" / "el_guero" / "expected.json").read_text()
)
LOCATIONS = {"L1": "Centro", "L2": "Polanco"}


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        yield c


def compute(conn: psycopg.Connection[Any], start: str, end: str) -> int:
    row = conn.execute(
        "select app.compute_dish_costs((select id from public.tenant), %s, %s)", (start, end)
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_the_top_15_dishes_match_the_hand_calculated_costs(conn: psycopg.Connection[Any]) -> None:
    assert compute(conn, EXPECTED["today"], EXPECTED["today"]) == len(EXPECTED["dish_costs_today"])
    rows = conn.execute(
        """select m.external_id, l.name, s.cost, s.price_net, s.margin, s.food_cost_pct
           from public.dish_cost_snapshot s
           join public.menu_item m on m.id = s.menu_item_id
           join public.location l on l.id = s.location_id
           where s.date = %s""",
        (EXPECTED["today"],),
    ).fetchall()
    got = {
        (code, loc): (cost, net, margin, round(pct, 1))
        for code, loc, cost, net, margin, pct in rows
    }
    want = {
        (d["code"], LOCATIONS[d["location"]]): (
            d["cost"],
            d["net_price"],
            d["margin"],
            Decimal(d["food_cost_pct"]),
        )
        for d in EXPECTED["dish_costs_today"]
    }
    assert got == want


def test_yesterday_s_food_cost_is_37_5_percent_through_the_rpc(
    conn: psycopg.Connection[Any],
) -> None:
    """13 H3 example 6: the theoretical food cost of Centro on 2026-10-11, end to end."""
    compute(conn, "2026-10-11", "2026-10-11")
    expected = EXPECTED["food_cost_yesterday"]["L1"]
    conn.execute("set local role authenticated")
    conn.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (json.dumps({"tenant_id": "03299e41-28bd-5779-bcc6-0e5e76580fad", "location_ids": None}),),
    )
    conn.execute("set local app.today = '2026-10-12'")
    row = conn.execute(
        "select api.compare_periods('food_cost_pct', '\"yesterday\"', '\"yesterday\"', "
        "'705e8e51-376b-5785-adbb-405eff4e2a22')"
    ).fetchone()
    assert row is not None
    a = row[0]["data"]["a"]
    assert a["text"] == "37.5%"
    assert Decimal(str(a["raw"])) == round(
        Decimal(100 * expected["numerator_cost"]) / Decimal(expected["denominator_net_ex_iva"]), 4
    )
