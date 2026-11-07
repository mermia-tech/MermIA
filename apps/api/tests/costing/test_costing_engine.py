"""MR-25: app.compute_dish_costs against the hand-calculated values in fixtures/el_guero.

expected.json is computed in Python by the fixture generator (packages/fixtures build.py) with
the README Definitions; the engine computes the same figures in SQL from the seeded recipes,
prices and menu prices. Each test runs in a transaction that is rolled back.
"""

import json
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
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


TENANT = "03299e41-28bd-5779-bcc6-0e5e76580fad"
CENTRO = "705e8e51-376b-5785-adbb-405eff4e2a22"
TODAY = "2026-10-12"
LOCK_WAIT_POLLS = 100
LOCK_WAIT_STEP_S = 0.1
Conn = psycopg.Connection[Any]


def one(conn: Conn, sql: str, args: tuple[Any, ...]) -> Any:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def add_ingredient(conn: Conn) -> str:
    """A throwaway ingredient at $1.00/g since January."""
    ingredient = str(
        one(
            conn,
            "insert into public.ingredient (tenant_id, name, base_unit) "
            "values (%s, 'Prueba candado ' || gen_random_uuid(), 'g') returning id",
            (TENANT,),
        )
    )
    conn.execute(
        "insert into public.ingredient_price "
        "(tenant_id, ingredient_id, unit_price_net, effective_from, source) "
        "values (%s, %s, 1.00, '2026-01-01', 'manual')",
        (TENANT, ingredient),
    )
    return ingredient


def add_dish(conn: Conn, ingredient: str) -> str:
    """A throwaway dish at Centro made of 10 g of the ingredient, costed today."""
    item = str(
        one(
            conn,
            "insert into public.menu_item (tenant_id, name) "
            "values (%s, 'Prueba candado ' || gen_random_uuid()) returning id",
            (TENANT,),
        )
    )
    conn.execute(
        "insert into public.menu_item_price (tenant_id, location_id, menu_item_id, price_gross, "
        "tax_rate, effective_from, source) "
        "values (%s, %s, %s, 10000, 0.16, '2026-01-01', 'manual')",
        (TENANT, CENTRO, item),
    )
    recipe = one(
        conn,
        "insert into public.recipe (tenant_id, menu_item_id, recipe_version, effective_from, "
        "yield_qty, status) values (%s, %s, 1, '2026-01-01', 1, 'confirmed') returning id",
        (TENANT, item),
    )
    conn.execute(
        "insert into public.recipe_line (tenant_id, recipe_id, ingredient_id, qty_base) "
        "values (%s, %s, %s, 10)",
        (TENANT, recipe, ingredient),
    )
    conn.execute(
        "select app.compute_dish_costs_for(%s, array[%s]::uuid[], %s, %s)",
        (TENANT, item, TODAY, TODAY),
    )
    return item


def price_tap_cost(url: str, opts: str, ingredient: str, item: str) -> int:
    """The price approval: its price row, then the tap's recompute; rolled back. Returns the
    dish's cost today as the tap left it."""
    with psycopg.connect(url, options=opts) as b, b.transaction(force_rollback=True):
        b.execute(
            "insert into public.ingredient_price "
            "(tenant_id, ingredient_id, unit_price_net, effective_from, source) "
            "values (%s, %s, 3.00, %s, 'manual')",
            (TENANT, ingredient, TODAY),
        )
        b.execute(
            """select app.recompute_after_change(%s, %s, jsonb_populate_record(
                 null::public.pending_change,
                 jsonb_build_object('tenant_id', %s::uuid, 'kind', 'ingredient_price.set',
                                    'target_id', %s::uuid)))""",
            (TENANT, TODAY, TENANT, ingredient),
        )
        return int(
            one(
                b,
                "select cost from public.dish_cost_snapshot where menu_item_id = %s and date = %s",
                (item, TODAY),
            )
        )


def wait_for_a_lock_waiter(url: str) -> None:
    with psycopg.connect(url) as watcher:
        for _ in range(LOCK_WAIT_POLLS):
            sql = "select count(*) from pg_locks where locktype = 'advisory' and not granted"
            if one(watcher, sql, ()) > 0:
                return
            time.sleep(LOCK_WAIT_STEP_S)
    pytest.fail("the price tap never waited for the tenant lock")


def remove(url: str, ingredient: str, item: str | None) -> None:
    with psycopg.connect(url) as c:
        if item:
            c.execute("delete from public.dish_cost_snapshot where menu_item_id = %s", (item,))
            c.execute(
                "delete from public.recipe_line where recipe_id in "
                "(select id from public.recipe where menu_item_id = %s)",
                (item,),
            )
            for table in ("recipe", "menu_item_price"):
                c.execute(f"delete from public.{table} where menu_item_id = %s", (item,))
            c.execute("delete from public.menu_item where id = %s", (item,))
        c.execute("delete from public.ingredient_price where ingredient_id = %s", (ingredient,))
        c.execute("delete from public.ingredient where id = %s", (ingredient,))


def test_a_tap_names_its_dishes_after_taking_the_tenant_lock() -> None:
    """A2: a recipe approval (A) holds the per-tenant costing lock when a price approval (B) on an
    ingredient of that recipe starts its recompute. B must list its dishes after A commits, or the
    new dish keeps A's old cost. Commits throwaway rows (an ingredient, a dish, its price and
    recipe) and removes them at the end; B is rolled back."""
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    opts = "-c lock_timeout=20s -c app.today=" + TODAY
    with psycopg.connect(url, options=opts) as c:
        ingredient = add_ingredient(c)
    item: str | None = None
    a = psycopg.connect(url, options=opts)
    try:
        # A: the recipe approval, its tap still open (it holds the lock)
        a.execute("select app.lock_dish_costs(%s)", (TENANT,))
        item = add_dish(a, ingredient)
        with ThreadPoolExecutor(1) as pool:
            cost = pool.submit(price_tap_cost, url, opts, ingredient, item)
            wait_for_a_lock_waiter(url)
            a.commit()
            assert cost.result(timeout=30) == 3000  # 10 g at $3.00, not A's $1.00
    finally:
        a.rollback()
        a.close()
        remove(url, ingredient, item)
