"""MR-63: the per-tenant `recipe_structure` advisory lock, proven with two real connections.

pgTAP runs in one transaction, so it cannot show that two concurrent writers are serialized.
Here A holds an open transaction (and so the lock) while B starts; the test waits until B is
visibly blocked on an advisory lock (`pg_locks`, B's own pid), then commits A. There is no
sleep-based race: if the lock is missing, B never blocks, finishes by itself, and the test
fails at once. Waits are polls with generous deadlines, so runner speed does not matter.

Commits throwaway rows (ingredients, recipes, a dish) and removes them at the end.
"""

import os
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from uuid import UUID

import psycopg
import pytest

pytestmark = pytest.mark.db

TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
LOCK_TIMEOUT = "-c lock_timeout=60s"  # a stuck lock fails the test instead of hanging it
BLOCKED_POLLS = 600
BLOCKED_STEP_S = 0.1
RESULT_TIMEOUT_S = 90
CHECK_VIOLATION = "23514"

Conn = psycopg.Connection[Any]


def one(conn: Conn, sql: str, args: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


class Scratch:
    """Throwaway committed rows for one test, removed in `cleanup`."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.ingredients: list[str] = []
        self.recipes: list[str] = []
        self.items: list[str] = []

    def ingredient(self, c: Conn) -> str:
        ing = str(
            one(
                c,
                "insert into public.ingredient (tenant_id, name, base_unit) "
                "values (%s, 'Prueba estructura ' || gen_random_uuid(), 'g') returning id",
                (TENANT,),
            )
        )
        self.ingredients.append(ing)
        return ing

    def sub_recipe(self, c: Conn) -> tuple[str, str]:
        """A recipe that produces a fresh ingredient: (recipe id, ingredient id)."""
        ing = self.ingredient(c)
        rec = str(
            one(
                c,
                "insert into public.recipe (tenant_id, produces_ingredient_id, recipe_version) "
                "values (%s, %s, 1) returning id",
                (TENANT, ing),
            )
        )
        self.recipes.append(rec)
        return rec, ing

    def menu_item(self, c: Conn) -> str:
        item = str(
            one(
                c,
                "insert into public.menu_item (tenant_id, name) "
                "values (%s, 'Prueba estructura ' || gen_random_uuid()) returning id",
                (TENANT,),
            )
        )
        self.items.append(item)
        return item

    def cleanup(self) -> None:
        with psycopg.connect(self.url) as c:
            for rec in self.recipes:
                c.execute("delete from public.recipe_line where recipe_id = %s", (rec,))
            for rec in self.recipes:
                c.execute("delete from public.recipe where id = %s", (rec,))
            for table, ids in (("menu_item", self.items), ("ingredient", self.ingredients)):
                for row_id in ids:
                    c.execute(f"delete from public.{table} where id = %s", (row_id,))


@pytest.fixture
def url() -> str:
    value = os.environ.get("MERMIA_DB_URL")
    if not value:
        pytest.skip("MERMIA_DB_URL is not set")
    return value


@pytest.fixture
def scratch(url: str) -> Iterator[Scratch]:
    s = Scratch(url)
    try:
        yield s
    finally:
        s.cleanup()


def wait_until_blocked_on_advisory_lock(url: str, pid: int, outcome: Future[Any]) -> None:
    """Return once backend `pid` waits for an advisory lock. Fails if B finishes first, which
    means it was never serialized behind A."""
    with psycopg.connect(url) as watcher:
        for _ in range(BLOCKED_POLLS):
            waiting = one(
                watcher,
                "select count(*) from pg_locks "
                "where pid = %s and locktype = 'advisory' and not granted",
                (pid,),
            )
            if waiting > 0:
                return
            if outcome.done():
                pytest.fail(f"B finished without waiting for the recipe_structure lock: {outcome}")
            time.sleep(BLOCKED_STEP_S)
    pytest.fail("B never waited for the recipe_structure lock")


def run_b_behind_a(url: str, a: Conn, b_sql: str, b_args: tuple[Any, ...]) -> psycopg.Error | None:
    """Run B's statement on its own connection while A (open transaction) holds the lock; commit
    A once B is blocked; return the error B ended with, or None if it succeeded."""
    b = psycopg.connect(url, options=LOCK_TIMEOUT)
    pid = b.info.backend_pid

    def work() -> psycopg.Error | None:
        try:
            b.execute(b_sql, b_args)
            b.commit()
            return None
        except psycopg.Error as err:
            b.rollback()
            return err

    try:
        with ThreadPoolExecutor(1) as pool:
            outcome = pool.submit(work)
            wait_until_blocked_on_advisory_lock(url, pid, outcome)
            a.commit()
            return outcome.result(timeout=RESULT_TIMEOUT_S)
    finally:
        b.close()


def test_concurrent_lines_cannot_close_a_cycle(url: str, scratch: Scratch) -> None:
    """check_recipe_line: A adds "X's recipe uses Y's", B adds "Y's recipe uses X's". Each is
    valid alone; B must wait for A and then fail with 23514 instead of storing the cycle."""
    with psycopg.connect(url) as setup:
        rx, _ = scratch.sub_recipe(setup)
        ry, _ = scratch.sub_recipe(setup)
    a = psycopg.connect(url, options=LOCK_TIMEOUT)
    try:
        a.execute(
            "insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base) "
            "values (%s, %s, %s, 1)",
            (TENANT, rx, ry),
        )
        err = run_b_behind_a(
            url,
            a,
            "insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base) "
            "values (%s, %s, %s, 1)",
            (TENANT, ry, rx),
        )
    finally:
        a.rollback()
        a.close()
    assert isinstance(err, psycopg.errors.CheckViolation), err
    assert err.sqlstate == CHECK_VIOLATION
    with psycopg.connect(url) as check:
        lines = one(
            check,
            "select count(*) from public.recipe_line where recipe_id = any(%s::uuid[])",
            ([rx, ry],),
        )
    assert lines == 1  # only A's line


def test_a_recipe_in_use_cannot_turn_into_a_dish_concurrently(url: str, scratch: Scratch) -> None:
    """check_recipe_kind: A adds a sub-recipe line that uses recipe R, B turns R into a dish
    recipe. B must wait for A and then fail with 23514, not leave a dish used as a sub-recipe."""
    with psycopg.connect(url) as setup:
        r, _ = scratch.sub_recipe(setup)
        parent, _ = scratch.sub_recipe(setup)
        item = scratch.menu_item(setup)
    a = psycopg.connect(url, options=LOCK_TIMEOUT)
    try:
        a.execute(
            "insert into public.recipe_line (tenant_id, recipe_id, sub_recipe_id, qty_base) "
            "values (%s, %s, %s, 1)",
            (TENANT, parent, r),
        )
        err = run_b_behind_a(
            url,
            a,
            "update public.recipe set produces_ingredient_id = null, menu_item_id = %s "
            "where id = %s",
            (item, r),
        )
    finally:
        a.rollback()
        a.close()
    assert isinstance(err, psycopg.errors.CheckViolation), err
    assert err.sqlstate == CHECK_VIOLATION
    with psycopg.connect(url) as check:
        produces = one(
            check, "select produces_ingredient_id from public.recipe where id = %s", (r,)
        )
    assert produces is not None  # R still produces its ingredient
