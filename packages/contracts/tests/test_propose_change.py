"""propose_change: `values` is typed per kind, prices come in the unit the user said.

The model sends "$220 el kilo" as {unit_price: 220, unit: "kg", effective_from}. Converting it to
pesos per base unit (0.22 per g) is the confirmation service's job (MR-37 with the unit
conversions of MR-25); this contract does not do it. What is stored, shown and applied stays per
base unit (pending.IngredientPriceSet), so the two shapes differ on purpose.
"""

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.agent_tools import (
    VALUES_FOR_KIND,
    ProposeChangeArgs,
    tool_definitions,
)
from mermia_contracts.pending import (
    IngredientPriceInput,
    IngredientPriceSet,
    MenuItemPriceSet,
    NoPayload,
    PendingKind,
    RecipeUpsert,
)

DAY = "2026-10-19"
UNITS = ["g", "kg", "ml", "l", "pza"]
INGREDIENT = "ingredient_price.set"
MENU = "menu_item_price.set"
RECIPE = "recipe.upsert"
APPROVE = "import_batch.approve"
ROLLBACK = "import_batch.rollback"
RECIPE_VALUES = {
    "yield_qty": 1,
    "lines": [{"ingredient_name": "Carne", "qty_base": 60, "unit": "g"}],
}


def _args(kind: str, values: Any = ..., **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {"kind": kind, "target": "carne al pastor", **extra}
    if values is not ...:
        doc["values"] = values
    return doc


def _ingredient(**over: Any) -> dict[str, Any]:
    return {"unit_price": 220.00, "unit": "kg", "effective_from": DAY, **over}


def _without(values: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k != key}


def _locs(info: pytest.ExceptionInfo[ValidationError]) -> list[tuple[str, str]]:
    return [(str(e["loc"][-1]), e["type"]) for e in info.value.errors()]


def test_the_eval_shape_with_its_effective_date_is_a_typed_proposal() -> None:
    """13 H3 #9: "$220 el kilo" arrives as a price, a unit and a date, as json.loads gives it."""
    tool_input = json.loads(
        '{"kind": "ingredient_price.set", "target": "carne al pastor",'
        ' "values": {"unit_price": 220.00, "unit": "kg", "effective_from": "2026-10-19"}}'
    )
    args = ProposeChangeArgs.model_validate(tool_input)
    assert isinstance(args.values, IngredientPriceInput)
    assert (args.values.unit_price, args.values.unit) == (Decimal("220"), "kg")


@pytest.mark.parametrize("unit", UNITS)
def test_every_unit_of_the_closed_list_is_accepted(unit: str) -> None:
    ProposeChangeArgs.model_validate(_args(INGREDIENT, _ingredient(unit=unit)))


@pytest.mark.parametrize("unit", ["oz", "lb", "KG", "kilo", "kg ", "", "litro", None, 1])
def test_a_unit_outside_the_closed_list_is_rejected(unit: Any) -> None:
    ProposeChangeArgs.model_validate(_args(INGREDIENT, _ingredient()))
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(INGREDIENT, _ingredient(unit=unit)))
    assert ("unit", "literal_error") in _locs(info)


@pytest.mark.parametrize("key", ["unit_price", "unit", "effective_from"])
def test_a_price_proposal_needs_price_unit_and_date(key: str) -> None:
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(INGREDIENT, _without(_ingredient(), key)))
    assert (key, "missing") in _locs(info)


def test_a_menu_price_proposal_needs_its_effective_date() -> None:
    good = {"price_gross": 6500, "effective_from": DAY}
    ProposeChangeArgs.model_validate(_args(MENU, good))
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(MENU, _without(good, "effective_from")))
    assert ("effective_from", "missing") in _locs(info)


@pytest.mark.parametrize(
    "kind,values,extra",
    [
        (INGREDIENT, _ingredient(), "source"),  # the proposer never sets the source
        (INGREDIENT, _ingredient(), "currency"),
        (MENU, {"price_gross": 6500, "effective_from": DAY}, "unit"),  # no unit on a menu price
        (RECIPE, RECIPE_VALUES, "effective_from"),
        (APPROVE, {}, "unit"),
        (ROLLBACK, {}, "reason"),
    ],
    ids=["source", "currency", "unit-on-menu-price", "date-on-recipe", "approve", "rollback"],
)
def test_a_field_that_does_not_belong_to_the_kind_is_rejected(
    kind: str, values: dict[str, Any], extra: str
) -> None:
    ProposeChangeArgs.model_validate(_args(kind, values))
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(kind, {**values, extra: "kg"}))
    assert (extra, "extra_forbidden") in _locs(info)


@pytest.mark.parametrize(
    "kind,values",
    [
        (INGREDIENT, {"price_gross": 6500, "effective_from": DAY}),
        (INGREDIENT, RECIPE_VALUES),
        (MENU, _ingredient()),
        (RECIPE, _ingredient()),
        (APPROVE, _ingredient()),
        (ROLLBACK, {"price_gross": 6500, "effective_from": DAY}),
        (INGREDIENT, {}),
        (MENU, {}),
        (RECIPE, {}),
    ],
    ids=[
        "ingredient-with-menu-values",
        "ingredient-with-recipe-values",
        "menu-with-ingredient-values",
        "recipe-with-ingredient-values",
        "approve-with-values",
        "rollback-with-values",
        "ingredient-without-values",
        "menu-without-values",
        "recipe-without-values",
    ],
)
def test_values_must_be_the_payload_of_their_own_kind(kind: str, values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="do not match kind"):
        ProposeChangeArgs.model_validate(_args(kind, values))


@pytest.mark.parametrize("kind", [APPROVE, ROLLBACK])
@pytest.mark.parametrize("values", [..., {}])
def test_approving_and_rolling_back_a_batch_need_no_values(kind: str, values: Any) -> None:
    args = ProposeChangeArgs.model_validate(_args(kind, values))
    assert isinstance(args.values, NoPayload)


@pytest.mark.parametrize("price", [0, -5, "0.000000", "-0.000001"])
def test_the_price_a_user_quotes_is_greater_than_zero(price: Any) -> None:
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(INGREDIENT, _ingredient(unit_price=price)))
    assert ("unit_price", "greater_than") in _locs(info)


def test_a_menu_price_in_centavos_is_greater_than_zero() -> None:
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(MENU, {"price_gross": 0, "effective_from": DAY}))
    assert ("price_gross", "greater_than") in _locs(info)


def test_the_input_and_the_stored_shapes_differ_only_where_the_unit_is_converted() -> None:
    """Persistence stays per base unit: it has no `unit`, so an input cannot be stored as is."""
    assert VALUES_FOR_KIND[PendingKind.ingredient_price_set] is IngredientPriceInput
    assert VALUES_FOR_KIND[PendingKind.menu_item_price_set] is MenuItemPriceSet
    assert VALUES_FOR_KIND[PendingKind.recipe_upsert] is RecipeUpsert
    assert VALUES_FOR_KIND[PendingKind.import_batch_approve] is NoPayload
    assert VALUES_FOR_KIND[PendingKind.import_batch_rollback] is NoPayload
    assert set(VALUES_FOR_KIND) == set(PendingKind)
    with pytest.raises(ValidationError) as info:
        IngredientPriceSet.model_validate(_ingredient())
    assert ("unit", "extra_forbidden") in _locs(info)
    stored = set(IngredientPriceSet.model_fields)
    assert stored - set(IngredientPriceInput.model_fields) == {"source"}
    assert set(IngredientPriceInput.model_fields) - stored == {"unit"}


def _schema() -> dict[str, Any]:
    tool = next(t for t in tool_definitions() if t["name"] == "propose_change")
    return tool["input_schema"]


def test_the_tool_schema_lists_one_closed_variant_per_payload() -> None:
    schema = _schema()
    variants = schema["properties"]["values"]["anyOf"]
    names = [v["$ref"].rsplit("/", 1)[1] for v in variants]
    assert names == ["IngredientPriceInput", "MenuItemPriceSet", "RecipeUpsert", "NoPayload"]
    for name in names:
        assert schema["$defs"][name]["additionalProperties"] is False


def test_the_tool_schema_states_the_units_and_the_required_dates() -> None:
    defs = _schema()["$defs"]
    ingredient = defs["IngredientPriceInput"]
    assert set(ingredient["required"]) == {"unit_price", "unit", "effective_from"}
    assert ingredient["properties"]["unit"]["enum"] == UNITS
    assert set(defs["MenuItemPriceSet"]["required"]) == {"price_gross", "effective_from"}


def test_the_tool_schema_size_is_recorded_not_budgeted() -> None:
    """Typed values make propose_change larger. This is a size guard in characters, NOT a token
    measurement (that is deferred to the eval ticket): it fails if the schema grows unnoticed."""
    size = len(json.dumps(_schema(), separators=(",", ":")))
    assert size <= 2450, size  # 2397 when written; before typed values: 563
