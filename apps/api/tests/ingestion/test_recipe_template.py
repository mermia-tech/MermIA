"""MR-25: the recipe template writer, and the template round trip on the El Güero seed.

render is pure. build, the CLI and the round trip (generate from the seed, parse, load) need
MERMIA_DB_URL and the seed; those tests are marked db and run in a transaction that is rolled
back. The written template must parse back to the recipes it was prefilled with, carry the
parser's own headers, and offer the Insumo and Unidad dropdowns.
"""

import datetime as dt
import io
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from openpyxl import load_workbook

from mermia_api.ingestion.loader import load
from mermia_api.ingestion.parsers import mermia_recetas as fmt
from mermia_api.ingestion.registry import parse_file
from mermia_api.ingestion.templates import recetas as writer
from mermia_api.ingestion.templates.recetas import (
    BLANK_ROWS,
    Template,
    TemplateDish,
    TemplateIngredient,
    TemplateLine,
    build,
    render,
)
from mermia_contracts.pending import RecipeUpsertProposal

PASTOR = TemplateDish(
    "P001",
    "Tacos al pastor (orden de 3)",
    Decimal(1),
    (
        TemplateLine("Tortilla de maíz", Decimal("75"), "g", None),
        TemplateLine("Carne al pastor (adobada)", Decimal("63.85"), "g", None),
        TemplateLine("Cilantro", Decimal("3.5"), "g", Decimal("75")),
    ),
)
QUESADILLA = TemplateDish("P020", "Quesadilla de queso", None, ())
INGREDIENTS = (
    TemplateIngredient("Carne al pastor (adobada)", "g", Decimal("92.0000"), "carnes"),
    TemplateIngredient("Cilantro", "g", Decimal("60.0000"), "verdura"),
    TemplateIngredient("Tortilla de maíz", "g", Decimal("100.0000"), "tortillería"),
)
DATA = Template(
    "Taquería El Güero", "Centro", dt.date(2026, 10, 12), (PASTOR, QUESADILLA), INGREDIENTS
)
HEADER_ROW = 6


def sheet_rows(data: bytes, sheet: str) -> list[tuple[object, ...]]:
    wb = load_workbook(io.BytesIO(data))
    return [tuple(r) for r in wb[sheet].iter_rows(values_only=True)]


def test_the_sheets_and_the_title_block() -> None:
    wb = load_workbook(io.BytesIO(render(DATA)))
    assert wb.sheetnames == [fmt.SHEET_INSTRUCTIONS, fmt.SHEET_RECIPES, fmt.SHEET_INGREDIENTS]
    recetas = sheet_rows(render(DATA), fmt.SHEET_RECIPES)
    assert [r[0] for r in recetas[:4]] == [
        "Taquería El Güero - Centro",
        "Plantilla de recetas MermIA",
        "Versión 1",
        "Fecha: 12/10/2026",
    ]
    assert recetas[HEADER_ROW - 1] == fmt.HEADER
    instructions = [r[0] for r in sheet_rows(render(DATA), fmt.SHEET_INSTRUCTIONS) if r[0]]
    assert 6 <= len(instructions) <= 10


def test_a_prefilled_dish_is_written_once_with_its_lines_below() -> None:
    recetas = sheet_rows(render(DATA), fmt.SHEET_RECIPES)[HEADER_ROW:]
    assert recetas[0] == ("P001", PASTOR.name, 1, "Tortilla de maíz", 75, "g", None, None)
    assert recetas[1] == (None, None, None, "Carne al pastor (adobada)", 63.85, "g", None, None)
    assert recetas[2] == (None, None, None, "Cilantro", 3.5, "g", 75, None)


def test_a_dish_without_a_recipe_gets_its_row_and_eight_blank_ones() -> None:
    data = Template(DATA.restaurant, DATA.location, DATA.day, (QUESADILLA, PASTOR), INGREDIENTS)
    recetas = sheet_rows(render(data), fmt.SHEET_RECIPES)[HEADER_ROW:]
    assert recetas[0][:4] == ("P020", "Quesadilla de queso", 1, None)
    assert BLANK_ROWS == 8
    assert all(set(r) == {None} for r in recetas[1 : 1 + BLANK_ROWS])
    assert recetas[1 + BLANK_ROWS][:2] == ("P001", PASTOR.name)


def test_the_insumos_sheet_is_a_protected_reference() -> None:
    wb = load_workbook(io.BytesIO(render(DATA)))
    ws = wb[fmt.SHEET_INGREDIENTS]
    rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
    assert rows[0] == fmt.INGREDIENTS_HEADER
    assert rows[1:] == [
        ("Carne al pastor (adobada)", "g", 92, "carnes"),
        ("Cilantro", "g", 60, "verdura"),
        ("Tortilla de maíz", "g", 100, "tortillería"),
    ]
    assert ws.protection.sheet


def test_the_insumo_and_unidad_dropdowns() -> None:
    wb = load_workbook(io.BytesIO(render(DATA)))
    ws = wb[fmt.SHEET_RECIPES]
    by_column = {
        str(v.sqref).split(":")[0].rstrip("0123456789"): v
        for v in ws.data_validations.dataValidation
    }
    insumo, unidad = by_column["D"], by_column["F"]
    assert (insumo.type, insumo.formula1) == ("list", f"{fmt.SHEET_INGREDIENTS}!$A$2:$A$4")
    assert insumo.errorStyle == "warning", "a new ingredient can still be typed"
    assert (unidad.type, unidad.formula1) == ("list", '"g,kg,ml,l,pza"')
    first = HEADER_ROW + 1
    assert str(insumo.sqref).startswith(f"D{first}:D")
    assert str(unidad.sqref).startswith(f"F{first}:F")


def test_the_template_parses_back_to_its_recipes() -> None:
    batch = parse_file(render(DATA))
    assert (batch.parser, batch.location_hint, batch.issues) == (fmt.PARSER, "Centro", [])
    assert (batch.period.from_, batch.totals.lines) == (dt.date(2026, 10, 12), 1)
    (pastor,) = batch.recipes
    assert (pastor.menu_item_external_id, pastor.menu_item_name, pastor.yield_qty) == (
        "P001",
        PASTOR.name,
        Decimal(1),
    )
    assert [
        (x.ingredient_name, x.qty_base, x.unit, x.yield_override_pct) for x in pastor.lines
    ] == [(x.ingredient, x.qty_base, x.unit, x.yield_pct) for x in PASTOR.lines]


def test_rendering_is_deterministic() -> None:
    assert render(DATA) == render(DATA)


def test_a_template_for_the_whole_tenant_has_no_location() -> None:
    data = Template("Taquería El Güero", None, DATA.day, DATA.dishes, ())
    recetas = sheet_rows(render(data), fmt.SHEET_RECIPES)
    assert recetas[0][0] == "Taquería El Güero - Todas las sucursales"
    assert parse_file(render(data)).location_hint is None


@pytest.mark.parametrize(("location", "hint"), [(None, None), ("Centro", "Centro")])
def test_a_restaurant_name_with_a_dash_gives_no_false_location(
    location: str | None, hint: str | None
) -> None:
    data = Template("Tacos - El Güero", location, DATA.day, DATA.dishes, ())
    assert parse_file(render(data)).location_hint == hint


def test_instruction_7_does_not_promise_new_dishes() -> None:
    text = " ".join(str(r[0]) for r in sheet_rows(render(DATA), fmt.SHEET_INSTRUCTIONS) if r[0])
    assert "Para un platillo nuevo, escribe su nombre" not in text
    assert "Solo los platillos de la lista" in text
    assert "Soft Restaurant" in text


FORMULA = '=HYPERLINK("http://example.com","clic")'


@pytest.mark.parametrize("name", [FORMULA, "+52 tacos", "-menos sal", "@pastor"])
def test_a_name_that_looks_like_a_formula_is_written_as_text(name: str) -> None:
    dish = TemplateDish("P009", name, Decimal(1), (TemplateLine(name, Decimal(10), "g", None),))
    ingredient = TemplateIngredient(name, "g", Decimal(100), None)
    data = Template(name, None, DATA.day, (dish,), (ingredient,))
    wb = load_workbook(io.BytesIO(render(data)))
    cells = [
        wb[fmt.SHEET_RECIPES].cell(HEADER_ROW + 1, 2),
        wb[fmt.SHEET_RECIPES].cell(HEADER_ROW + 1, 4),
        wb[fmt.SHEET_INGREDIENTS].cell(2, 1),
    ]
    for cell in cells:
        assert (cell.value, cell.data_type, cell.quotePrefix) == (name, "s", True)
    (recipe,) = parse_file(render(data)).recipes
    assert (recipe.menu_item_name, recipe.lines[0].ingredient_name) == (name, name)


# --- on the seed ----------------------------------------------------------------------------

SAMPLE = Path(__file__).parents[4] / "fixtures" / "templates" / "plantilla_recetas_v1_L1.xlsx"
SR_SAMPLE = (
    Path(__file__).parents[4] / "fixtures" / "sr" / "synthetic" / "recetas_L1_2026-10-12.xlsx"
)
TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")
CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")
LUPITA = UUID("240e45f0-ef48-5654-a835-8fbc70de15bc")  # manager, Centro
GUACAMOLE_ITEM_CODE = "P030"
DAY = dt.date(2026, 10, 12)  # the seed's "today"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        yield c


@pytest.fixture
def source(conn: psycopg.Connection[Any]) -> UUID:
    """Centro's manual source, for files we generate (decision 4; MR-30 creates it)."""
    row = conn.execute(
        """insert into public.source (tenant_id, location_id, kind, config, status)
           values (%s, %s, 'manual', '{"report": "plantilla_recetas"}', 'active') returning id""",
        (TENANT, CENTRO),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def stats(conn: psycopg.Connection[Any], batch_id: UUID) -> dict[str, Any]:
    row = conn.execute(
        "select status::text, stats from public.import_batch where id = %s", (batch_id,)
    ).fetchone()
    assert row is not None
    return {"status": row[0], **{k: row[1].get(k) for k in ("proposed", "unchanged", "held")}}


def edited(data: bytes, edits: dict[tuple[str, str], dict[str, Any]]) -> bytes:
    """The template with cells changed: (dish, ingredient or "") -> {column header: value}.
    An empty ingredient means the dish's own row."""
    wb = load_workbook(io.BytesIO(data))
    ws = wb[fmt.SHEET_RECIPES]
    col = {h: i + 1 for i, h in enumerate(fmt.HEADER)}
    dish = None
    for n in range(HEADER_ROW + 1, ws.max_row + 1):
        dish = ws.cell(n, col[fmt.DISH]).value or dish
        key = (
            dish,
            "" if ws.cell(n, col[fmt.DISH]).value else ws.cell(n, col[fmt.INGREDIENT]).value,
        )
        for name, value in edits.pop(key, {}).items():  # type: ignore[arg-type]
            ws.cell(n, col[name]).value = value
    assert edits == {}, f"not found: {list(edits)}"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.mark.db
def test_the_template_lists_the_menu_by_units_sold_with_the_seed_recipes(
    conn: psycopg.Connection[Any],
) -> None:
    data = build(conn, TENANT, CENTRO, DAY)
    assert (data.restaurant, data.location, data.day) == ("Taquería El Güero", "Centro", DAY)
    assert len(data.dishes) == 39 and len(data.ingredients) == 61
    assert [d.name for d in data.dishes[:3]] == [
        "Tacos al pastor (orden de 3)",
        "Coca-Cola",
        "Tacos de bistec (orden de 3)",
    ]
    assert [bool(d.lines) for d in data.dishes] == [True] * 15 + [False] * 24
    sr = {r.menu_item_external_id: r for r in parse_file(SR_SAMPLE.read_bytes()).recipes}
    for d in data.dishes[:15]:  # the seed recipes, as the SR sample prints them
        recipe = sr[d.code]
        assert (d.name, d.yield_qty) == (recipe.menu_item_name, recipe.yield_qty)
        assert sorted((x.ingredient, x.qty_base, x.unit) for x in d.lines) == sorted(
            (x.ingredient_name, x.qty_base, x.unit) for x in recipe.lines
        )
        assert all(x.yield_pct is None for x in d.lines), "the seed uses the default yields"


@pytest.mark.db
def test_the_template_from_the_seed_gives_15_unchanged(
    conn: psycopg.Connection[Any], source: UUID
) -> None:
    batch = parse_file(render(build(conn, TENANT, CENTRO, DAY)))
    r = load(conn, batch, source_id=source, proposed_by=LUPITA)
    assert (r.status, r.duplicate, r.pending_change_ids, r.issues) == ("parsed", False, (), ())
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 15,
        "held": 0,
    }


@pytest.mark.db
def test_the_template_round_trip_with_one_quantity_edited_and_a_dish_added(
    conn: psycopg.Connection[Any], source: UUID
) -> None:
    pastor, guacamole = "Tacos al pastor (orden de 3)", "Guacamole con totopos"
    filled = edited(
        render(build(conn, TENANT, CENTRO, DAY)),
        {
            (pastor, "Carne al pastor (adobada)"): {fmt.QTY: 70},
            (guacamole, ""): {fmt.INGREDIENT: "Aguacate Hass", fmt.QTY: 0.15, fmt.UNIT: "kg"},
        },
    )
    r = load(conn, parse_file(filled), source_id=source, proposed_by=LUPITA)
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 2,
        "unchanged": 14,
        "held": 0,
    }
    rows = conn.execute(
        """select target_id, base_version, payload, diff from public.pending_change
           where id = any(%s) order by diff -> 'menu_item' ->> 'name'""",
        (list(r.pending_change_ids),),
    ).fetchall()
    (guac_id, guac_base, guac_payload, guac_diff), (_, pastor_base, _, pastor_diff) = rows
    assert (guac_diff["menu_item"]["external_id"], guac_base) == (GUACAMOLE_ITEM_CODE, None)
    assert (guac_diff["before"], guac_diff["added"], guac_diff["parser"]) == (
        None,
        ["Aguacate Hass"],
        fmt.PARSER,
    )
    (line,) = RecipeUpsertProposal.model_validate(guac_payload).values.lines
    assert (line.ingredient_name, line.qty_base, line.unit) == ("Aguacate Hass", Decimal(150), "g")
    assert pastor_base == 1
    assert (pastor_diff["added"], pastor_diff["removed"]) == ([], [])
    assert pastor_diff["changed"] == [
        {
            "ingredient": "Carne al pastor (adobada)",
            "before": {"qty_base": "63.850000", "yield_override_pct": None},
            "after": {"qty_base": "70.000000", "yield_override_pct": None},
        }
    ]
    assert guac_id != pastor_diff["menu_item"]["id"]


@pytest.mark.db
def test_a_dish_held_by_the_template_is_counted_and_the_rest_loads(
    conn: psycopg.Connection[Any], source: UUID
) -> None:
    filled = edited(
        render(build(conn, TENANT, CENTRO, DAY)),
        {("Tacos al pastor (orden de 3)", ""): {fmt.PORTIONS: 0}},
    )
    r = load(conn, parse_file(filled), source_id=source)
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 14,
        "held": 1,
    }
    assert {"plantilla.porciones_not_positive", "plantilla.recipe_held"} <= {
        i.code for i in r.issues
    }


@pytest.mark.db
def test_the_committed_sample_is_what_the_cli_writes_from_the_seed(tmp_path: Path) -> None:
    if not os.environ.get("MERMIA_DB_URL"):
        pytest.skip("MERMIA_DB_URL is not set")
    out = tmp_path / SAMPLE.name
    args = ["--tenant", str(TENANT), "--location", str(CENTRO), "--date", DAY.isoformat()]
    assert writer.main([*args, "--out", str(out), "--golden"]) == 0
    assert out.read_bytes() == SAMPLE.read_bytes(), "regenerate the sample with the CLI"
    golden = SAMPLE.with_name(SAMPLE.stem + ".golden.json")
    assert out.with_name(golden.name).read_text() == golden.read_text()


@pytest.mark.db
def test_the_template_leaves_menu_modifiers_out(conn: psycopg.Connection[Any]) -> None:
    names = {d.name for d in build(conn, TENANT, CENTRO, DAY).dishes}
    assert not names & {"Extra queso", "Extra aguacate"}
    assert {"Coca-Cola", "Guacamole con totopos"} <= names, "drinks and dishes stay"


@pytest.mark.db
def test_prefilled_lines_go_biggest_quantity_first(conn: psycopg.Connection[Any]) -> None:
    (pastor,) = [d for d in build(conn, TENANT, CENTRO, DAY).dishes if d.code == "P001"]
    assert [(x.ingredient, x.qty_base) for x in pastor.lines] == [
        ("Tortilla de maíz", Decimal(75)),
        ("Carne al pastor (adobada)", Decimal("63.85")),
        ("Salsa verde (preparada)", Decimal(30)),
        ("Piña", Decimal(28)),
        ("Limón", Decimal(20)),
        ("Cebolla blanca", Decimal(15)),
        ("Cilantro", Decimal(5)),
    ]


def test_lines_with_the_same_quantity_go_by_name() -> None:
    lines = (
        TemplateLine("Sal", Decimal(1), "g", None),
        TemplateLine("Ajo", Decimal(1), "g", None),
        TemplateLine("Res", Decimal(90), "g", None),
    )
    assert [x.ingredient for x in writer.ordered(lines)] == ["Res", "Ajo", "Sal"]


@pytest.mark.db
def test_an_unknown_dish_in_a_template_does_not_send_the_owner_to_soft_restaurant(
    conn: psycopg.Connection[Any], source: UUID
) -> None:
    filled = edited(
        render(build(conn, TENANT, CENTRO, DAY)),
        {("Tacos al pastor (orden de 3)", ""): {fmt.CODE: None, fmt.DISH: "Pozole rojo grande"}},
    )
    r = load(conn, parse_file(filled), source_id=source)
    (issue,) = [i for i in r.issues if i.code == "recipe.item_unknown"]
    assert "«Pozole rojo grande»" in issue.message_es
    assert "Soft Restaurant" not in issue.message_es


PASTOR_ITEM = UUID("f496f051-9f85-5f8a-a4b6-c1a814d37c73")


def newer_pastor_recipe(conn: psycopg.Connection[Any], effective_from: dt.date) -> None:
    """A version 2 of the pastor recipe (less meat), the recipe of record from `effective_from`;
    test setup only, rolled back."""
    row = conn.execute(
        """insert into public.recipe
             (tenant_id, menu_item_id, recipe_version, effective_from, yield_qty, status)
           select tenant_id, menu_item_id, 2, %s, yield_qty, 'confirmed' from public.recipe
           where menu_item_id = %s and recipe_version = 1 returning id""",
        (effective_from, PASTOR_ITEM),
    ).fetchone()
    assert row is not None
    conn.execute(
        """insert into public.recipe_line
             (tenant_id, recipe_id, ingredient_id, sub_recipe_id, qty_base, yield_override_pct)
           select rl.tenant_id, %s, rl.ingredient_id, rl.sub_recipe_id,
                  case when i.name = 'Carne al pastor (adobada)' then 50 else rl.qty_base end,
                  rl.yield_override_pct
           from public.recipe_line rl join public.recipe r on r.id = rl.recipe_id
           left join public.ingredient i on i.id = rl.ingredient_id
           where r.menu_item_id = %s and r.recipe_version = 1""",
        (row[0], PASTOR_ITEM),
    )


@pytest.mark.db
def test_a_dish_whose_recipe_changed_after_the_template_is_held(
    conn: psycopg.Connection[Any], source: UUID
) -> None:
    template = render(build(conn, TENANT, CENTRO, DAY))  # Fecha 12/10/2026
    newer_pastor_recipe(conn, dt.date(2026, 10, 20))
    r = load(conn, parse_file(template), source_id=source, proposed_by=LUPITA)
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 0,
        "unchanged": 14,
        "held": 1,
    }
    (issue,) = [i for i in r.issues if i.code == "plantilla.recipe_changed_since"]
    assert issue.message_es == (
        "La receta de «Tacos al pastor (orden de 3)» cambió el 20/10, después de esta "
        "plantilla (12/10); descarga una plantilla nueva."
    )
    assert r.pending_change_ids == ()


@pytest.mark.db
def test_a_recipe_changed_before_the_template_is_compared_as_usual(
    conn: psycopg.Connection[Any], source: UUID
) -> None:
    newer_pastor_recipe(conn, dt.date(2026, 10, 1))
    template = render(build(conn, TENANT, CENTRO, DAY))
    r = load(conn, parse_file(template), source_id=source, proposed_by=LUPITA)
    assert stats(conn, r.batch_id)["unchanged"] == 15
    assert r.issues == ()


@pytest.fixture
def tenant_source(conn: psycopg.Connection[Any]) -> UUID:
    """A tenant-level manual source (no location), as an email inbox would be."""
    row = conn.execute(
        """insert into public.source (tenant_id, location_id, kind, config, status)
           values (%s, null, 'manual', '{"report": "plantilla_recetas"}', 'active') returning id""",
        (TENANT,),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


@pytest.mark.db
def test_a_tenant_wide_template_loads_without_a_location(
    conn: psycopg.Connection[Any], tenant_source: UUID
) -> None:
    template = render(build(conn, TENANT, None, DAY))
    filled = edited(template, {("Tacos al pastor (orden de 3)", "Cilantro"): {fmt.QTY: 7}})
    batch = parse_file(filled)
    assert batch.location_hint is None
    r = load(conn, batch, source_id=tenant_source, proposed_by=LUPITA)
    codes = {i.code for i in r.issues}
    assert "location.unknown" not in codes
    assert "recipe.chain_location_differs" not in codes, "no location: no chain comparison"
    assert stats(conn, r.batch_id) == {
        "status": "parsed",
        "proposed": 1,
        "unchanged": 14,
        "held": 0,
    }
    again = load(conn, parse_file(filled), source_id=tenant_source, proposed_by=LUPITA)
    assert (again.duplicate, again.batch_id) == (True, r.batch_id)


@pytest.mark.db
def test_an_sr_recipe_report_without_a_location_is_still_refused(
    conn: psycopg.Connection[Any],
) -> None:
    row = conn.execute(
        """insert into public.source (tenant_id, location_id, kind, config, status)
           values (%s, null, 'sr_report', '{"report": "recetas"}', 'active') returning id""",
        (TENANT,),
    ).fetchone()
    assert row is not None
    sr = parse_file(SR_SAMPLE.read_bytes())
    batch = sr.model_copy(update={"location_hint": None})  # a title that names no location
    r = load(conn, batch, source_id=UUID(str(row[0])), proposed_by=LUPITA)
    assert r.status == "rejected"
    assert "location.unknown" in {i.code for i in r.issues}
    assert r.pending_change_ids == ()
