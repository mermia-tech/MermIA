"""MR-32 part 2: a recipe.upsert filed by the MR-25 importer is applied through the Python seam.

End to end on the El Güero seed: the importer proposes an edited pastor recipe (diff.after holds
the resolved lines), the owner taps Confirmar, and a new confirmed recipe version is written from
the business day of the approval. Each test runs in one transaction that is rolled back. Needs
MERMIA_DB_URL and the seed.
"""

import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest

from mermia_api.confirm.apply import apply_pending_change
from mermia_api.ingestion.loader import load
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import NormalizedBatch, RecipeIn, RecipeLineIn
from mermia_contracts.db.models import PendingChangeStatus
from mermia_contracts.pending import ApplyCode, ApplyPendingChangeArgs, ApplyResult

pytestmark = pytest.mark.db

SR = Path(__file__).parents[4] / "fixtures" / "sr" / "synthetic"
TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")
OWNER = UUID("eb52f6ad-4d75-5b06-9881-9f68f4fb05a0")
LUPITA = UUID("240e45f0-ef48-5654-a835-8fbc70de15bc")  # manager, Centro, imports only
PASTOR = UUID("f496f051-9f85-5f8a-a4b6-c1a814d37c73")
CARNE = UUID("356dfff4-d912-542b-b8b0-8ae42068eb7e")
SALSA_RECIPE = UUID("46faac9d-fc08-5876-af8d-6b3b958b52b3")
TODAY = "2026-10-12"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        c.execute(f"set local app.today = '{TODAY}'")
        yield c


@pytest.fixture(scope="module")
def sample() -> NormalizedBatch:
    return parse_file((SR / "recetas_L1_2026-10-12.xlsx").read_bytes())


def edited_pastor(batch: NormalizedBatch, extra: RecipeLineIn) -> NormalizedBatch:
    """The batch with more meat in the pastor and one more line."""

    def change(r: RecipeIn) -> RecipeIn:
        if r.menu_item_external_id != "P001":
            return r
        ls = [
            x.model_copy(update={"qty_base": Decimal("80.000000")})
            if x.ingredient_name == "Carne al pastor (adobada)"
            else x
            for x in r.lines
        ]
        return r.model_copy(update={"lines": [*ls, extra]})

    return batch.model_copy(update={"recipes": [change(r) for r in batch.recipes]})


def propose(conn: psycopg.Connection[Any], batch: NormalizedBatch) -> UUID:
    row = conn.execute(
        """insert into public.source (tenant_id, location_id, kind, config, status)
           values (%s, %s, 'sr_report', '{"report": "recetas"}', 'active') returning id""",
        (TENANT, CENTRO),
    ).fetchone()
    assert row is not None
    result = load(conn, batch, source_id=UUID(str(row[0])), proposed_by=LUPITA)
    (change,) = result.pending_change_ids
    return change


def tap(conn: psycopg.Connection[Any], change: UUID, user: UUID) -> ApplyResult:
    return apply_pending_change(conn, ApplyPendingChangeArgs(id=change, user_id=user))


def epazote(unit: str = "g") -> RecipeLineIn:
    return RecipeLineIn(
        ingredient_name="Epazote", qty_base=Decimal("2.000000"), unit=unit, yield_override_pct=None
    )


def recipe_of_record(conn: psycopg.Connection[Any]) -> tuple[Any, ...]:
    row = conn.execute(
        """select r.id, r.recipe_version, r.status::text, r.effective_from::text
           from public.recipe r where r.id = app.recipe_of_record(%s, null, %s)""",
        (PASTOR, TODAY),
    ).fetchone()
    assert row is not None
    return tuple(row)


def test_the_owner_applies_an_imported_recipe_with_a_new_ingredient(
    conn: psycopg.Connection[Any], sample: NormalizedBatch
) -> None:
    change = propose(conn, edited_pastor(sample, epazote()))

    result = tap(conn, change, OWNER)

    assert (result.code, result.status) == (ApplyCode.applied, PendingChangeStatus.applied)
    recipe_id, version, status, effective_from = recipe_of_record(conn)
    assert (version, status, effective_from) == (2, "confirmed", TODAY)
    lines = conn.execute(
        """select coalesce(i.name, sr_i.name), rl.ingredient_id, rl.sub_recipe_id, rl.qty_base
           from public.recipe_line rl
           left join public.ingredient i on i.id = rl.ingredient_id
           left join public.recipe sr on sr.id = rl.sub_recipe_id
           left join public.ingredient sr_i on sr_i.id = sr.produces_ingredient_id
           where rl.recipe_id = %s""",
        (recipe_id,),
    ).fetchall()
    by_name = {x[0]: x for x in lines}
    assert len(lines) == 8
    assert by_name["Carne al pastor (adobada)"][1:] == (CARNE, None, Decimal("80.000000"))
    assert by_name["Salsa verde (preparada)"][1:3] == (None, SALSA_RECIPE)
    created = conn.execute(
        """select id, base_unit::text from public.ingredient
           where tenant_id = %s and name = 'Epazote'""",
        (TENANT,),
    ).fetchall()
    assert [(by_name["Epazote"][1], "g")] == created
    audit = conn.execute(
        """select before ->> 'recipe_version', after ->> 'recipe_version',
                  after -> 'created_ingredient_ids'
           from public.audit_log
           where pending_change_id = %s and action = 'pending_change.apply'""",
        (change,),
    ).fetchall()
    assert audit == [("1", "2", [str(created[0][0])])]
    assert tap(conn, change, OWNER).code == ApplyCode.already_applied


def test_a_new_ingredient_whose_name_exists_in_another_unit_fails(
    conn: psycopg.Connection[Any], sample: NormalizedBatch
) -> None:
    change = propose(conn, edited_pastor(sample, epazote("pza")))
    conn.execute(
        "insert into public.ingredient (tenant_id, name, base_unit) values (%s, 'Epazote', 'g')",
        (TENANT,),
    )

    result = tap(conn, change, OWNER)

    assert (result.code, result.status) == (ApplyCode.failed, PendingChangeStatus.failed)
    assert recipe_of_record(conn)[1] == 1
    error = conn.execute(
        """select after ->> 'error' from public.audit_log
           where pending_change_id = %s and action = 'pending_change.fail'""",
        (change,),
    ).fetchone()
    assert error is not None and "Epazote" in error[0] and "pza" in error[0]


def test_the_importer_s_manager_cannot_approve_a_recipe(
    conn: psycopg.Connection[Any], sample: NormalizedBatch
) -> None:
    change = propose(conn, edited_pastor(sample, epazote()))

    result = tap(conn, change, LUPITA)

    assert (result.code, result.status) == (ApplyCode.forbidden_role, PendingChangeStatus.pending)
    assert recipe_of_record(conn)[1] == 1
