"""MR-25: recipe batches become recipe.upsert pending changes, on the El Güero seed.

The loader never writes recipe or recipe_line: every recipe it can match is compared with the
recipe of record and, when it differs, proposed for a person to approve (MR-32 applies it). Each
test runs in one transaction that is rolled back. Needs MERMIA_DB_URL and the seed.
"""

import datetime as dt
import os
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest

from mermia_api.ingestion.loader import LoadResult, load
from mermia_api.ingestion.registry import parse_file
from mermia_contracts.batch import NormalizedBatch, RecipeIn, RecipeLineIn
from mermia_contracts.pending import PendingKind, RecipeUpsertProposal

pytestmark = pytest.mark.db

SR = Path(__file__).parents[4] / "fixtures" / "sr" / "synthetic"
TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")
LUPITA = UUID("240e45f0-ef48-5654-a835-8fbc70de15bc")  # manager, Centro
PASTOR_ITEM = UUID("f496f051-9f85-5f8a-a4b6-c1a814d37c73")
CARNE = UUID("356dfff4-d912-542b-b8b0-8ae42068eb7e")
SALSA_RECIPE = UUID("46faac9d-fc08-5876-af8d-6b3b958b52b3")
PASTOR = "Tacos al pastor (orden de 3)"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        yield c


@pytest.fixture
def source(conn: psycopg.Connection[Any]) -> UUID:
    """A Centro source for the SR Recetas report (the seed has none)."""
    row = conn.execute(
        """insert into public.source (tenant_id, location_id, kind, config, status)
           values (%s, %s, 'sr_report', '{"report": "recetas"}', 'active') returning id""",
        (TENANT, CENTRO),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


@pytest.fixture(scope="module")
def sample() -> NormalizedBatch:
    return parse_file((SR / "recetas_L1_2026-10-12.xlsx").read_bytes())


def with_recipes(batch: NormalizedBatch, recipes: list[RecipeIn]) -> NormalizedBatch:
    return batch.model_copy(
        update={
            "recipes": recipes,
            "totals": batch.totals.model_copy(update={"lines": len(recipes)}),
        }
    )


def edit(
    batch: NormalizedBatch, code: str, change: Callable[[RecipeIn], RecipeIn | None]
) -> NormalizedBatch:
    """The batch with the recipe of `code` changed (or removed, when `change` gives None)."""
    recipes = [r if r.menu_item_external_id != code else change(r) for r in batch.recipes]
    return with_recipes(batch, [r for r in recipes if r is not None])


def lines(recipe: RecipeIn, change: Callable[[list[RecipeLineIn]], list[RecipeLineIn]]) -> RecipeIn:
    return recipe.model_copy(update={"lines": change(list(recipe.lines))})


def set_line(name: str, **values: Any) -> Callable[[list[RecipeLineIn]], list[RecipeLineIn]]:
    def change(ls: list[RecipeLineIn]) -> list[RecipeLineIn]:
        assert any(x.ingredient_name == name for x in ls), name
        return [x.model_copy(update=values) if x.ingredient_name == name else x for x in ls]

    return change


def edited_pastor(batch: NormalizedBatch) -> NormalizedBatch:
    """More meat, a measured cilantro yield, no lime, and chile serrano added."""

    def change(ls: list[RecipeLineIn]) -> list[RecipeLineIn]:
        ls = set_line("Carne al pastor (adobada)", qty_base=Decimal("70.000000"))(ls)
        ls = set_line("Cilantro", yield_override_pct=Decimal("75.0000"))(ls)
        serrano = RecipeLineIn(
            ingredient_name="Chile serrano",
            ingredient_external_id="I023",
            qty_base=Decimal("5.000000"),
            unit="g",
            yield_override_pct=Decimal("100.0000"),
        )
        return [x for x in ls if x.ingredient_name != "Limón"] + [serrano]

    return edit(batch, "P001", lambda r: lines(r, change))


def pending(conn: psycopg.Connection[Any], batch_id: UUID) -> list[dict[str, Any]]:
    cur = conn.execute(
        """select id, kind, target_type, target_id, base_version, payload, diff, proposed_by_user,
                  proposed_via::text, required_role::text, status::text,
                  expires_at - created_at as ttl
           from public.pending_change where diff ->> 'batch_id' = %s order by created_at""",
        (str(batch_id),),
    )
    names = [d.name for d in cur.description or []]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def stats(conn: psycopg.Connection[Any], batch_id: UUID) -> dict[str, Any]:
    row = conn.execute(
        "select status::text, stats from public.import_batch where id = %s", (batch_id,)
    ).fetchone()
    assert row is not None
    return {"status": row[0], **{k: row[1].get(k) for k in ("proposed", "unchanged", "held")}}


def codes(r: LoadResult) -> set[str]:
    return {i.code for i in r.issues}


def test_the_sr_sample_gives_15_unchanged_recipes(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    r = load(conn, sample, source_id=source, proposed_by=LUPITA)
    assert (r.status, r.duplicate, r.pending_change_ids, r.issues) == ("parsed", False, (), ())
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 15,
        "held": 0,
    }
    assert pending(conn, r.batch_id) == []


def test_an_edit_to_pastor_gives_one_pending_change_with_its_diff_and_audit_row(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    r = load(conn, edited_pastor(sample), source_id=source, proposed_by=LUPITA)
    assert r.status == "parsed"
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 1,
        "unchanged": 14,
        "held": 0,
    }
    (change,) = pending(conn, r.batch_id)
    assert r.pending_change_ids == (change["id"],)
    assert (
        change["kind"],
        change["target_type"],
        change["target_id"],
        change["base_version"],
        change["proposed_by_user"],
        change["proposed_via"],
        change["required_role"],
        change["status"],
        change["ttl"],
    ) == (
        "recipe.upsert",
        "menu_item",
        PASTOR_ITEM,
        1,
        LUPITA,
        "import",
        "manager",
        "pending",
        dt.timedelta(hours=24),
    )

    proposal = RecipeUpsertProposal.model_validate(change["payload"])
    assert (proposal.kind, proposal.target_id) == (PendingKind.recipe_upsert, PASTOR_ITEM)
    by_name = {x.ingredient_name: x for x in proposal.values.lines}
    assert len(by_name) == 7
    assert by_name["Carne al pastor (adobada)"].qty_base == Decimal(70)
    assert by_name["Carne al pastor (adobada)"].yield_override_pct is None, "92 is the default"
    assert by_name["Cilantro"].yield_override_pct == Decimal(75)

    diff = change["diff"]
    assert (diff["batch_id"], diff["parser"]) == (str(r.batch_id), "sr.recetas@v1")
    assert diff["menu_item"] == {"id": str(PASTOR_ITEM), "name": PASTOR, "external_id": "P001"}
    assert diff["added"] == ["Chile serrano"]
    assert diff["removed"] == ["Limón"]
    assert diff["changed"] == [
        {
            "ingredient": "Carne al pastor (adobada)",
            "before": {"qty_base": "63.850000", "yield_override_pct": None},
            "after": {"qty_base": "70.000000", "yield_override_pct": None},
        },
        {
            "ingredient": "Cilantro",
            "before": {"qty_base": "5.000000", "yield_override_pct": None},
            "after": {"qty_base": "5.000000", "yield_override_pct": "75.0000"},
        },
    ]
    assert diff["before"]["recipe_version"] == 1
    assert len(diff["before"]["lines"]) == len(diff["after"]["lines"]) == 7
    after = {x["ingredient_name"]: x for x in diff["after"]["lines"]}
    assert after["Carne al pastor (adobada)"]["ingredient_id"] == str(CARNE)
    assert not any(x["new_ingredient"] for x in after.values())

    audit = conn.execute(
        """select actor_user_id, actor_kind::text, action, entity_type, entity_id, batch_id,
                  after = %s::jsonb
           from public.audit_log where pending_change_id = %s""",
        (psycopg.types.json.Jsonb(diff["after"]), change["id"]),
    ).fetchall()
    assert audit == [
        (LUPITA, "user", "pending_change.propose", "menu_item", PASTOR_ITEM, r.batch_id, True)
    ]


def test_salsa_verde_becomes_a_sub_recipe_line_without_a_yield(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    salsa = set_line(
        "Salsa verde (preparada)", qty_base=Decimal("40.000000"), yield_override_pct=Decimal(80)
    )
    batch = edit(sample, "P001", lambda r: lines(r, salsa))
    r = load(conn, batch, source_id=source)
    (change,) = pending(conn, r.batch_id)
    after = {x["ingredient_name"]: x for x in change["diff"]["after"]["lines"]}
    line = after["Salsa verde (preparada)"]
    assert (line["sub_recipe_id"], line["yield_override_pct"]) == (str(SALSA_RECIPE), None)
    payload = RecipeUpsertProposal.model_validate(change["payload"])
    (salsa_line,) = [x for x in payload.values.lines if x.ingredient_name.startswith("Salsa")]
    assert salsa_line.yield_override_pct is None
    assert change["diff"]["changed"][0]["ingredient"] == "Salsa verde (preparada)"
    assert change["proposed_by_user"] is None
    actor = conn.execute(
        "select actor_kind::text from public.audit_log where pending_change_id = %s",
        (change["id"],),
    ).fetchone()
    assert actor == ("system",)


def test_an_override_equal_to_the_default_is_stored_as_null(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    more = set_line("Piña", qty_base=Decimal("30.000000"))
    r = load(conn, edit(sample, "P001", lambda r: lines(r, more)), source_id=source)
    (change,) = pending(conn, r.batch_id)
    payload = RecipeUpsertProposal.model_validate(change["payload"])
    assert all(x.yield_override_pct is None for x in payload.values.lines)
    assert [c["ingredient"] for c in change["diff"]["changed"]] == ["Piña"]


@pytest.mark.parametrize(
    ("code", "change", "issue"),
    [
        (
            "P040",
            lambda r: lines(r, set_line("Leche entera", unit="g")),
            "recipe.unit_mismatch",
        ),
        (
            "P040",
            lambda r: lines(r, set_line("Leche entera", unit="taza")),
            "recipe.unit_unknown",
        ),
        (
            "P001",
            lambda r: r.model_copy(update={"menu_item_name": "Tacos árabes"}),
            "recipe.item_code_mismatch",
        ),
        (
            "P001",
            lambda r: r.model_copy(
                update={"menu_item_external_id": None, "menu_item_name": "Pozole rojo grande"}
            ),
            "recipe.item_unknown",
        ),
    ],
    ids=["unit-mismatch", "unit-unknown", "dish-by-code-only", "dish-unknown"],
)
def test_a_recipe_that_cannot_be_matched_is_held(
    conn: psycopg.Connection[Any],
    source: UUID,
    sample: NormalizedBatch,
    code: str,
    change: Callable[[RecipeIn], RecipeIn],
    issue: str,
) -> None:
    r = load(conn, edit(sample, code, change), source_id=source)
    assert r.status == "parsed"
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 14,
        "held": 1,
    }
    assert issue in codes(r)
    assert pending(conn, r.batch_id) == []
    stored = conn.execute(
        "select code, severity::text from public.import_issue where batch_id = %s",
        (r.batch_id,),
    ).fetchall()
    assert (issue, "error") in stored


def test_two_ingredients_with_the_same_name_hold_the_recipe(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    conn.execute(
        "insert into public.ingredient (tenant_id, name, base_unit) values (%s, 'CILANTRO', 'g')",
        (TENANT,),
    )
    r = load(conn, sample, source_id=source)
    assert "recipe.ingredient_ambiguous" in codes(r)
    held = stats(conn, r.batch_id)["held"]
    assert held == 5, "every recipe with cilantro (P001 to P005)"
    assert pending(conn, r.batch_id) == []


def test_an_unknown_ingredient_is_proposed_as_new(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    epazote = RecipeLineIn(
        ingredient_name="Epazote",
        qty_base=Decimal("2.000000"),
        unit="g",
        yield_override_pct=Decimal(90),
    )
    r = load(
        conn,
        edit(sample, "P001", lambda r: lines(r, lambda ls: [*ls, epazote])),
        source_id=source,
    )
    (change,) = pending(conn, r.batch_id)
    after = {x["ingredient_name"]: x for x in change["diff"]["after"]["lines"]}
    assert after["Epazote"]["new_ingredient"] is True
    assert (after["Epazote"]["ingredient_id"], after["Epazote"]["sub_recipe_id"]) == (None, None)
    assert after["Epazote"]["yield_override_pct"] == "90.0000"
    assert change["diff"]["added"] == ["Epazote"]
    assert conn.execute(
        "select count(*) from public.ingredient where name = 'Epazote'"
    ).fetchone() == (0,), "MR-32 creates it on approval"


def test_an_unknown_ingredient_with_a_unit_that_is_not_a_base_unit_is_held(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    odd = RecipeLineIn(ingredient_name="Epazote", qty_base=Decimal(2), unit="manojo")
    r = load(
        conn, edit(sample, "P001", lambda r: lines(r, lambda ls: [*ls, odd])), source_id=source
    )
    assert "recipe.unit_unknown" in codes(r)
    assert pending(conn, r.batch_id) == []


def test_one_ingredient_code_under_two_names_is_a_warning(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    recode = set_line("Cilantro", ingredient_external_id="I018")  # cebolla blanca's code
    r = load(conn, edit(sample, "P001", lambda r: lines(r, recode)), source_id=source)
    (warning,) = [i for i in r.issues if i.code == "recipe.ingredient_code_names"]
    assert warning.severity.value == "warning"
    assert "I018" in warning.message_es
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 15,
        "held": 0,
    }


def test_two_recipes_for_one_dish_are_both_held(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    twin = sample.recipes[0].model_copy(update={"menu_item_external_id": None})
    r = load(conn, with_recipes(sample, [*sample.recipes, twin]), source_id=source)
    assert [i.code for i in r.issues] == ["recipe.item_repeated"], "one issue per dish"
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 14,
        "held": 2,
    }


def test_a_batch_whose_every_recipe_is_held_is_rejected(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    unknown = [
        r.model_copy(update={"menu_item_external_id": None, "menu_item_name": f"Platillo {i}"})
        for i, r in enumerate(sample.recipes[:2])
    ]
    r = load(conn, with_recipes(sample, unknown), source_id=source)
    assert (r.status, stats(conn, r.batch_id)["held"]) == ("rejected", 2)


def test_catalog_totals_that_do_not_match_the_recipes_are_rejected(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    bad = sample.model_copy(update={"totals": sample.totals.model_copy(update={"lines": 14})})
    r = load(conn, bad, source_id=source)
    assert (r.status, codes(r)) == ("rejected", {"batch.totals_mismatch"})
    assert pending(conn, r.batch_id) == []


def test_the_same_file_twice_is_a_duplicate(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    batch = edited_pastor(sample)
    first = load(conn, batch, source_id=source)
    again = load(conn, batch, source_id=source)
    assert (again.duplicate, again.batch_id, again.status) == (True, first.batch_id, "parsed")
    assert len(pending(conn, first.batch_id)) == 1


def test_an_identical_pending_proposal_is_not_filed_twice(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    first = load(conn, edited_pastor(sample), source_id=source)
    next_day = sample.period.model_copy(
        update={"from_": dt.date(2026, 10, 13), "to": dt.date(2026, 10, 13)}
    )
    later = load(
        conn, edited_pastor(sample).model_copy(update={"period": next_day}), source_id=source
    )
    assert not later.duplicate and later.batch_id != first.batch_id
    assert later.status == "parsed"
    assert (later.pending_change_ids, pending(conn, later.batch_id)) == ((), [])
    row = conn.execute(
        "select stats -> 'already_pending' from public.import_batch where id = %s",
        (later.batch_id,),
    ).fetchone()
    assert row == (1,)
    total = conn.execute(
        "select count(*) from public.pending_change where target_id = %s and status = 'pending'",
        (PASTOR_ITEM,),
    ).fetchone()
    assert total == (1,)


def test_load_never_writes_recipe_tables(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    # any write to the recipe tables inside this (rolled back) transaction fails the load
    conn.execute(
        """create function pg_temp.no_recipe_writes() returns trigger language plpgsql as $$
           begin raise exception 'the loader wrote %', tg_table_name; end $$"""
    )
    for table in ("recipe", "recipe_line"):
        conn.execute(
            f"""create trigger no_loader_writes before insert or update or delete on public.{table}
                for each statement execute function pg_temp.no_recipe_writes()"""
        )
    r = load(conn, edited_pastor(sample), source_id=source, proposed_by=LUPITA)
    assert (r.status, len(r.pending_change_ids)) == ("parsed", 1)
    applied = conn.execute(
        "select count(*) from public.audit_log where batch_id = %s and action = %s",
        (r.batch_id, "import_batch.apply"),
    ).fetchone()
    assert applied == (0,), "apply_batch is never called for a catalog batch"
