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
from mermia_contracts.batch import IssueIn, NormalizedBatch, RecipeIn, RecipeLineIn
from mermia_contracts.db.models import IssueSeverity
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
    assert diff["report_date"] == "2026-10-12"
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


POLANCO = UUID("fdda5e3b-6bcd-5c48-a6de-f524be37463e")


def next_day(batch: NormalizedBatch, days: int = 1) -> NormalizedBatch:
    """The same recipes as a later report (another slice: not a duplicate by content)."""
    day = batch.period.from_ + dt.timedelta(days=days)
    return batch.model_copy(
        update={"period": batch.period.model_copy(update={"from_": day, "to": day})}
    )


def source_at(conn: psycopg.Connection[Any], location_id: UUID) -> UUID:
    row = conn.execute(
        """insert into public.source (tenant_id, location_id, kind, config, status)
           values (%s, %s, 'sr_report', '{"report": "recetas"}', 'active') returning id""",
        (TENANT, location_id),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def pastor_line(conn: psycopg.Connection[Any], name: str) -> tuple[UUID, UUID]:
    """(recipe_line id, recipe id) of the pastor recipe of record's line for `name`."""
    row = conn.execute(
        """select rl.id, rl.recipe_id from public.recipe_line rl
           join public.recipe r on r.id = rl.recipe_id
           left join public.recipe sr on sr.id = rl.sub_recipe_id
           join public.ingredient i on i.id = coalesce(rl.ingredient_id, sr.produces_ingredient_id)
           where r.menu_item_id = %s and i.name = %s""",
        (PASTOR_ITEM, name),
    ).fetchone()
    assert row is not None, name
    return UUID(str(row[0])), UUID(str(row[1]))


def statuses(conn: psycopg.Connection[Any], *loads: LoadResult) -> list[tuple[str, str | None]]:
    """(status, resolved_via) of the pastor change each load filed, in the order given."""
    found = []
    for r in loads:
        row = conn.execute(
            """select status::text, resolved_via from public.pending_change
               where id = any(%s) and target_id = %s""",
            (list(r.pending_change_ids), PASTOR_ITEM),
        ).fetchone()
        assert row is not None
        found.append((row[0], row[1]))
    total = conn.execute(
        "select count(*) from public.pending_change where target_id = %s", (PASTOR_ITEM,)
    ).fetchone()
    assert total == (len(loads),)
    return found


def less_meat(batch: NormalizedBatch) -> NormalizedBatch:
    meat = set_line("Carne al pastor (adobada)", qty_base=Decimal("55.000000"))
    return edit(batch, "P001", lambda r: lines(r, meat))


def test_a_stored_recipe_with_a_repeated_ingredient_is_compared_without_crashing(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    line_id, recipe_id = pastor_line(conn, "Cilantro")
    conn.execute(
        """insert into public.recipe_line
             (tenant_id, recipe_id, ingredient_id, qty_base, yield_override_pct)
           select tenant_id, recipe_id, ingredient_id, qty_base, 75 from public.recipe_line
           where id = %s""",
        (line_id,),
    )
    r = load(conn, sample, source_id=source)
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 1,
        "unchanged": 14,
        "held": 0,
    }
    (change,) = pending(conn, r.batch_id)
    diff = change["diff"]
    assert (diff["added"], diff["removed"], diff["changed"]) == ([], ["Cilantro"], [])
    assert len(diff["before"]["lines"]) == 8 and recipe_id == UUID(diff["before"]["recipe_id"])


def test_a_stored_override_equal_to_the_default_is_not_a_change(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    carne, _ = pastor_line(conn, "Carne al pastor (adobada)")
    salsa, _ = pastor_line(conn, "Salsa verde (preparada)")
    conn.execute("update public.recipe_line set yield_override_pct = 92 where id = %s", (carne,))
    conn.execute("update public.recipe_line set yield_override_pct = 80 where id = %s", (salsa,))
    r = load(conn, sample, source_id=source)
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 15,
        "held": 0,
    }


def test_a_catalog_load_holds_a_tenant_wide_recipe_lock(
    conn: psycopg.Connection[Any], sample: NormalizedBatch
) -> None:
    # a Polanco and a Centro file at once would both file the same tenant-wide proposal
    load(conn, sample, source_id=source_at(conn, POLANCO))
    url = os.environ["MERMIA_DB_URL"]
    with psycopg.connect(url, autocommit=True) as other:
        row = other.execute(
            "select pg_try_advisory_lock(hashtextextended(%s, 0))", (f"{TENANT}:recipes",)
        ).fetchone()
        assert row == (False,), "the other location's load waits for this one"


def test_recipes_the_parser_held_count_as_held(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    parser_held = IssueIn(
        severity=IssueSeverity.warning,
        code="sr.recipe_held",
        message_es="No tomé la receta de «Pozole» porque tiene errores en la fila 9.",
        row_ref="9",
    )
    r = load(conn, sample.model_copy(update={"issues": [parser_held]}), source_id=source)
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 15,
        "held": 1,
    }


def test_a_new_ingredient_in_two_units_holds_every_recipe_that_uses_it(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    def epazote(unit: str) -> Callable[[RecipeIn], RecipeIn]:
        line = RecipeLineIn(ingredient_name="Epazote", qty_base=Decimal(2), unit=unit)
        return lambda r: lines(r, lambda ls: [*ls, line])

    batch = edit(
        edit(edit(sample, "P001", epazote("g")), "P002", epazote("pza")), "P003", epazote("g")
    )
    r = load(conn, batch, source_id=source)
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 12,
        "held": 3,
    }
    held = [i for i in r.issues if i.code == "recipe.new_ingredient_units"]
    assert len(held) == 3 and all(i.severity.value == "error" for i in held)
    assert "Epazote" in held[0].message_es
    assert pending(conn, r.batch_id) == []


def test_a_different_proposal_for_the_same_dish_supersedes_the_pending_one(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    first = load(conn, edited_pastor(sample), source_id=source, proposed_by=LUPITA)
    later = load(conn, next_day(less_meat(sample)), source_id=source, proposed_by=LUPITA)
    (old,) = first.pending_change_ids
    (new,) = later.pending_change_ids
    assert statuses(conn, first, later) == [("expired", "superseded"), ("pending", None)]
    resolved = conn.execute(
        "select resolved_at is not null from public.pending_change where id = %s", (old,)
    ).fetchone()
    assert resolved == (True,)
    audit = conn.execute(
        """select actor_user_id, action, entity_type, entity_id, batch_id, before, after
           from public.audit_log where pending_change_id = %s and action <> %s""",
        (old, "pending_change.propose"),
    ).fetchall()
    assert audit == [
        (
            LUPITA,
            "pending_change.supersede",
            "pending_change",
            old,
            later.batch_id,
            {"status": "pending"},
            {"status": "expired", "resolved_via": "superseded", "superseded_by": str(new)},
        )
    ]
    (note,) = [i for i in later.issues if i.code == "recipe.pending_replaced"]
    assert PASTOR in note.message_es


def test_a_resend_after_its_proposal_was_rejected_proposes_again(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    batch = edited_pastor(sample)
    first = load(conn, batch, source_id=source)
    conn.execute(
        "update public.pending_change set status = 'rejected' where id = any(%s)",
        (list(first.pending_change_ids),),
    )
    again = load(conn, batch, source_id=source)
    assert (again.duplicate, again.status) == (False, "parsed")
    assert again.batch_id != first.batch_id and len(again.pending_change_ids) == 1
    assert statuses(conn, first, again) == [("rejected", None), ("pending", None)]


def pastor_states(conn: psycopg.Connection[Any]) -> list[tuple[str, str | None]]:
    return [
        (r[0], r[1])
        for r in conn.execute(
            """select status::text, resolved_via from public.pending_change
               where target_id = %s order by id""",
            (PASTOR_ITEM,),
        ).fetchall()
    ]


def test_an_older_report_does_not_replace_a_newer_pending_change(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    older = edited_pastor(sample)
    load(conn, older, source_id=source)
    load(conn, next_day(less_meat(sample)), source_id=source)
    again = load(conn, older, source_id=source)
    assert (again.duplicate, again.pending_change_ids) == (False, ())
    assert pastor_states(conn) == [("expired", "superseded"), ("pending", None)]
    (warning,) = [i for i in again.issues if i.code == "recipe.newer_pending"]
    day = sample.period.to + dt.timedelta(days=1)
    assert warning.severity.value == "warning"
    assert PASTOR in warning.message_es and f"{day:%d/%m/%Y}" in warning.message_es


def test_a_resend_with_the_same_report_date_replaces_the_pending_change(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    first = load(conn, edited_pastor(sample), source_id=source)
    again = load(conn, less_meat(sample), source_id=source)
    assert len(again.pending_change_ids) == 1 and "recipe.newer_pending" not in codes(again)
    assert statuses(conn, first, again) == [("expired", "superseded"), ("pending", None)]


def test_a_lapsed_pending_change_is_ignored_by_a_newer_report_and_an_older_one(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    first = load(conn, next_day(edited_pastor(sample)), source_id=source)
    conn.execute(
        "update public.pending_change set expires_at = now() - interval '1 minute' "
        "where id = any(%s)",
        (list(first.pending_change_ids),),
    )
    older = load(conn, less_meat(sample), source_id=source)
    assert len(older.pending_change_ids) == 1
    assert codes(older).isdisjoint({"recipe.newer_pending", "recipe.pending_replaced"})
    assert "recipe.chain_location_differs" in codes(older)  # only for the seed, not the lapsed
    assert pastor_states(conn) == [("pending", None), ("pending", None)]
    assert conn.execute(
        "select count(*) from public.audit_log where action = 'pending_change.supersede'"
    ).fetchone() == (0,)


def test_a_sales_file_twice_is_still_a_duplicate(conn: psycopg.Connection[Any]) -> None:
    batch = parse_file((SR / "ventas_por_dia_L1_2026-10-05.xlsx").read_bytes())
    row = conn.execute(
        """insert into public.source (tenant_id, location_id, kind, config, status)
           values (%s, %s, 'sr_report', '{"report": "ventas_por_dia"}', 'active') returning id""",
        (TENANT, CENTRO),
    ).fetchone()
    assert row is not None
    first = load(conn, batch, source_id=UUID(str(row[0])))
    again = load(conn, batch, source_id=UUID(str(row[0])))
    assert (again.duplicate, again.batch_id) == (True, first.batch_id)


def test_a_recipe_change_in_a_chain_is_a_warning_not_a_hold(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    # the seed recipe has no file behind it, and El Güero has two locations
    r = load(conn, edited_pastor(sample), source_id=source)
    (warning,) = [i for i in r.issues if i.code == "recipe.chain_location_differs"]
    assert warning.severity.value == "warning"
    assert PASTOR in warning.message_es and "todas tus sucursales" in warning.message_es
    assert (r.status, len(r.pending_change_ids)) == ("parsed", 1)


@pytest.mark.parametrize(("origin", "warned"), [(POLANCO, True), (CENTRO, False)])
def test_the_chain_warning_follows_the_location_the_current_recipe_came_from(
    conn: psycopg.Connection[Any],
    source: UUID,
    sample: NormalizedBatch,
    origin: UUID,
    warned: bool,
) -> None:
    first = load(conn, next_day(less_meat(sample), -1), source_id=source_at(conn, origin))
    conn.execute(  # as MR-32 will leave it once the change is approved and applied
        "update public.pending_change set status = 'applied' where id = any(%s)",
        (list(first.pending_change_ids),),
    )
    r = load(conn, edited_pastor(sample), source_id=source)
    assert ("recipe.chain_location_differs" in codes(r)) is warned


# --- review on #74: unsliced batches, a file equal to the recipe of record ------------------


def test_an_unsliced_batch_in_the_tenant_does_not_break_the_newer_pending_check(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    first = load(conn, edited_pastor(sample), source_id=source)
    conn.execute(  # the loader writes this slice_key for a batch with no location
        """insert into public.import_batch (tenant_id, source_id, parser, slice_key, status)
           values (%s, %s, 'sr.recetas@v1', 'unsliced:abc', 'rejected')""",
        (TENANT, source),
    )
    later = load(conn, next_day(less_meat(sample)), source_id=source)
    assert statuses(conn, first, later) == [("expired", "superseded"), ("pending", None)]


def test_a_file_equal_to_the_recipe_of_record_supersedes_an_older_pending_change(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    first = load(conn, edited_pastor(sample), source_id=source, proposed_by=LUPITA)
    later = load(conn, next_day(sample), source_id=source, proposed_by=LUPITA)
    (old,) = first.pending_change_ids
    assert later.pending_change_ids == ()
    assert stats(conn, later.batch_id)["unchanged"] == 15
    assert pastor_states(conn) == [("expired", "superseded")]
    audit = conn.execute(
        """select actor_user_id, action, entity_type, entity_id, batch_id, before, after
           from public.audit_log where pending_change_id = %s and action <> %s""",
        (old, "pending_change.propose"),
    ).fetchall()
    assert audit == [
        (
            LUPITA,
            "pending_change.supersede",
            "pending_change",
            old,
            later.batch_id,
            {"status": "pending"},
            {"status": "expired", "resolved_via": "superseded", "superseded_by": None},
        )
    ]
    (note,) = [i for i in later.issues if i.code == "recipe.pending_replaced"]
    assert PASTOR in note.message_es


def test_a_file_equal_to_the_recipe_of_record_keeps_a_newer_pending_change(
    conn: psycopg.Connection[Any], source: UUID, sample: NormalizedBatch
) -> None:
    load(conn, next_day(edited_pastor(sample)), source_id=source)
    older = load(conn, sample, source_id=source)
    assert older.pending_change_ids == () and "recipe.pending_replaced" not in codes(older)
    assert pastor_states(conn) == [("pending", None)]
