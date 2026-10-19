"""propose_change inputs for a menu price and a recipe: what the user said, not what is stored.

The model sends a price in pesos, a location by NAME, and a quantity with a unit of the closed
list. It never writes centavos, a location id or a base quantity. The confirmation service
(MR-37) resolves the names, fills a missing date and converts the units; the stored proposals
(`ChangeProposal`) keep `price_gross` in centavos, a `location_id` and `qty_base`. None of that
service work exists in this package: only the exact pesos-to-centavos helper does.
"""

import random
import time
from decimal import Decimal, localcontext
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.agent_tools import VALUES_FOR_KIND, ProposeChangeArgs, tool_definitions
from mermia_contracts.decimals import pesos_to_centavos
from mermia_contracts.pending import (
    ChangeProposal,
    IngredientPriceInput,
    IngredientPriceSet,
    MenuItemPriceInput,
    MenuItemPriceSet,
    NoPayload,
    PendingKind,
    RecipeUpsert,
    RecipeUpsertInput,
)

DAY = "2026-10-19"
TARGET = "0f7a1c52-3b6e-7c1a-9d33-000000000001"
CENTRO = "0f7a1c52-3b6e-7c1a-9d11-000000000001"
MENU = "menu_item_price.set"
RECIPE = "recipe.upsert"
STORED: TypeAdapter[Any] = TypeAdapter(ChangeProposal)
UNITS = ["g", "kg", "ml", "l", "pza"]


def _args(kind: str, values: Any) -> dict[str, Any]:
    return {"kind": kind, "target": "tacos al pastor", "values": values}


def _menu(**over: Any) -> dict[str, Any]:
    return {"price_pesos": 65, "location": "Centro", **over}


def _recipe(**line_over: Any) -> dict[str, Any]:
    line = {"ingredient_name": "Carne al pastor", "qty": "0.2", "unit": "kg", **line_over}
    return {"yield_qty": 1, "lines": [line]}


def _stored(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "target_id": TARGET, "values": values}


def _locs(info: pytest.ExceptionInfo[ValidationError]) -> list[tuple[str, str]]:
    return [(str(e["loc"][-1]), e["type"]) for e in info.value.errors()]


# --- pesos to centavos -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "pesos,cents",
    [
        (Decimal("65"), 6500),
        (Decimal("65.00"), 6500),
        (Decimal("65.5"), 6550),
        (Decimal("0.01"), 1),
        (Decimal("1234567.89"), 123456789),
        (65, 6500),
        (Decimal("92233720368547758.07"), 2**63 - 1),
    ],
)
def test_pesos_become_centavos_exactly(pesos: Decimal | int, cents: int) -> None:
    assert pesos_to_centavos(pesos) == cents


def test_the_conversion_is_exact_for_every_amount_of_centavos() -> None:
    rng = random.Random(7)
    for cents in [*range(1, 3000), *(rng.randrange(1, 2**63) for _ in range(3000))]:
        assert pesos_to_centavos(Decimal(cents) / 100) == cents


@pytest.mark.parametrize("pesos", [Decimal("65.005"), Decimal("0.001"), Decimal("1.0000001")])
def test_more_than_two_decimals_are_an_error_never_rounded(pesos: Decimal) -> None:
    with pytest.raises(ValueError, match="two decimals"):
        pesos_to_centavos(pesos)


@pytest.mark.parametrize("pesos", [Decimal(0), Decimal("-1"), Decimal("92233720368547758.08")])
def test_a_non_positive_or_out_of_range_amount_is_an_error(pesos: Decimal) -> None:
    with pytest.raises(ValueError):
        pesos_to_centavos(pesos)


LONG_FRACTION = Decimal("65.0000000000000000000000000001")  # 30 digits: not exact in centavos


def test_a_long_decimal_that_is_not_exact_in_centavos_fails_instead_of_rounding() -> None:
    """65.0000000000000000000000000001 x 100 loses its last digit under a 28-digit context."""
    assert len(LONG_FRACTION.as_tuple().digits) > 28
    with pytest.raises(ValueError, match="two decimals"):
        pesos_to_centavos(LONG_FRACTION)
    with pytest.raises(ValueError, match="two decimals"):
        pesos_to_centavos(Decimal("0.1000000000000000000000000000001"))


@pytest.mark.parametrize(
    "pesos,cents",
    [
        (Decimal("65.00000000000000000000000000000"), 6500),  # 31 digits, exactly 65 pesos
        (Decimal("92233720368547758.07000000000000"), 2**63 - 1),
        (Decimal("0.010000000000000000000000000000"), 1),
        (Decimal("6.5E+1"), 6500),
    ],
)
def test_a_long_decimal_that_is_exact_in_centavos_converts(pesos: Decimal, cents: int) -> None:
    assert pesos_to_centavos(pesos) == cents


@pytest.mark.parametrize(
    "pesos",
    [
        Decimal("sNaN"),
        Decimal("-sNaN"),
        Decimal("NaN"),
        Decimal("-NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_a_special_value_is_a_value_error_never_an_internal_exception(pesos: Decimal) -> None:
    with pytest.raises(ValueError):
        pesos_to_centavos(pesos)


@pytest.mark.parametrize(
    "pesos",
    [
        Decimal("1E+999999"),
        Decimal("1E-999999"),
        Decimal("1E+30"),
        Decimal("1E+999999999"),
        Decimal("1E-999999999"),
        Decimal("7E-999999999"),
    ],
)
def test_an_extreme_exponent_is_an_error_and_returns_quickly(pesos: Decimal) -> None:
    """Without the exponent guards, 1E+999999999 would try to build a 10**999999999 integer."""
    started = time.perf_counter()
    with pytest.raises(ValueError):
        pesos_to_centavos(pesos)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("prec", [1, 3, 28, 100])
def test_the_result_does_not_depend_on_the_callers_decimal_context(prec: int) -> None:
    with localcontext() as context:
        context.prec = prec
        assert pesos_to_centavos(Decimal("1234567.89")) == 123456789
        with pytest.raises(ValueError, match="two decimals"):
            pesos_to_centavos(LONG_FRACTION)


@pytest.mark.parametrize("pesos", [65.5, "65", True, None])
def test_only_a_decimal_or_an_int_is_converted_never_a_float(pesos: Any) -> None:
    with pytest.raises(TypeError):
        pesos_to_centavos(pesos)


# --- the menu price input --------------------------------------------------------------------


def test_the_model_sends_pesos_and_a_location_name_and_no_date() -> None:
    args = ProposeChangeArgs.model_validate(_args(MENU, _menu()))
    assert isinstance(args.values, MenuItemPriceInput)
    assert (args.values.price_pesos, args.values.location) == (Decimal(65), "Centro")
    assert args.values.effective_from is None


def test_a_menu_price_may_carry_a_date_and_a_null_date_means_none() -> None:
    dated = ProposeChangeArgs.model_validate(_args(MENU, _menu(effective_from=DAY)))
    assert str(dated.values.effective_from) == DAY  # type: ignore[union-attr]
    nulled = ProposeChangeArgs.model_validate(_args(MENU, _menu(effective_from=None)))
    assert nulled.values.effective_from is None  # type: ignore[union-attr]


def test_a_menu_price_needs_its_location() -> None:
    ProposeChangeArgs.model_validate(_args(MENU, _menu()))
    values = {"price_pesos": 65}
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(MENU, values))
    assert ("location", "missing") in _locs(info)


@pytest.mark.parametrize("location", ["", "  ", None, 7])
def test_the_location_is_a_readable_name(location: Any) -> None:
    with pytest.raises(ValidationError):
        ProposeChangeArgs.model_validate(_args(MENU, _menu(location=location)))


@pytest.mark.parametrize("price", [0, -1, "-0.01", "0.00"])
def test_a_menu_price_in_pesos_is_greater_than_zero(price: Any) -> None:
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(MENU, _menu(price_pesos=price)))
    assert ("price_pesos", "greater_than") in _locs(info)


@pytest.mark.parametrize("price", ["65.005", 65.001, "0.001"])
def test_a_menu_price_in_pesos_has_two_decimals_at_most(price: Any) -> None:
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(MENU, _menu(price_pesos=price)))
    assert ("price_pesos", "decimal_max_places") in _locs(info)


def test_a_menu_price_in_pesos_stays_inside_the_bigint_of_centavos() -> None:
    ProposeChangeArgs.model_validate(_args(MENU, _menu(price_pesos="92233720368547758.07")))
    with pytest.raises(ValidationError):
        ProposeChangeArgs.model_validate(_args(MENU, _menu(price_pesos="92233720368547758.08")))


@pytest.mark.parametrize(
    "key,value", [("price_gross", 6500), ("location_id", CENTRO), ("unit", "kg")]
)
def test_the_model_cannot_send_centavos_an_id_or_a_unit(key: str, value: Any) -> None:
    """A 65 in `price_gross` used to validate and become $0.65: it is no longer a field."""
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(MENU, {**_menu(), key: value}))
    assert (key, "extra_forbidden") in _locs(info)


def test_pesos_cannot_be_given_to_another_kind() -> None:
    with pytest.raises(ValidationError, match="do not match kind"):
        ProposeChangeArgs.model_validate(_args("ingredient_price.set", _menu()))


# --- the stored menu price keeps centavos and carries the location ---------------------------


def _stored_menu(**over: Any) -> dict[str, Any]:
    return {"price_gross": 6500, "location_id": CENTRO, "effective_from": DAY, **over}


def test_the_stored_menu_price_is_centavos_for_one_location_and_a_date() -> None:
    parsed = STORED.validate_python(_stored(MENU, _stored_menu()))
    assert (parsed.values.price_gross, str(parsed.values.location_id)) == (6500, CENTRO)
    assert set(MenuItemPriceSet.model_fields) == {"price_gross", "location_id", "effective_from"}


@pytest.mark.parametrize("key", ["price_gross", "location_id", "effective_from"])
def test_the_stored_menu_price_needs_every_field(key: str) -> None:
    values = {k: v for k, v in _stored_menu().items() if k != key}
    with pytest.raises(ValidationError) as info:
        STORED.validate_python(_stored(MENU, values))
    assert (key, "missing") in _locs(info)


@pytest.mark.parametrize(
    "key,value,error",
    [
        ("location_id", "Centro", "uuid_parsing"),
        ("location_id", None, "uuid_type"),
        ("price_pesos", 65, "extra_forbidden"),
        ("location", "Centro", "extra_forbidden"),
    ],
)
def test_the_stored_menu_price_rejects_what_the_model_sends(
    key: str, value: Any, error: str
) -> None:
    with pytest.raises(ValidationError) as info:
        STORED.validate_python(_stored(MENU, {**_stored_menu(), key: value}))
    assert (key, error) in _locs(info)


def test_the_stored_menu_price_still_has_to_be_greater_than_zero() -> None:
    with pytest.raises(ValidationError) as info:
        STORED.validate_python(_stored(MENU, _stored_menu(price_gross=0)))
    assert ("price_gross", "greater_than") in _locs(info)


# --- the recipe input ------------------------------------------------------------------------


def test_a_recipe_line_is_a_quantity_with_a_unit_of_the_closed_list() -> None:
    args = ProposeChangeArgs.model_validate(_args(RECIPE, _recipe()))
    assert isinstance(args.values, RecipeUpsertInput)
    line = args.values.lines[0]
    assert (line.qty, line.unit) == (Decimal("0.2"), "kg")


@pytest.mark.parametrize("unit", UNITS)
def test_every_unit_of_the_closed_list_is_valid_in_a_recipe(unit: str) -> None:
    ProposeChangeArgs.model_validate(_args(RECIPE, _recipe(unit=unit)))


@pytest.mark.parametrize("unit", ["oz", "KG", "gramos", "", None, 1])
def test_a_recipe_unit_outside_the_list_is_rejected(unit: Any) -> None:
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(RECIPE, _recipe(unit=unit)))
    assert ("unit", "literal_error") in _locs(info)


@pytest.mark.parametrize("key", ["qty", "unit", "ingredient_name"])
def test_a_recipe_line_needs_name_quantity_and_unit(key: str) -> None:
    line = {"ingredient_name": "Carne", "qty": 1, "unit": "g"}
    del line[key]
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(RECIPE, {"yield_qty": 1, "lines": [line]}))
    assert (key, "missing") in _locs(info)


@pytest.mark.parametrize("qty", [0, -1, "-0.000001"])
def test_a_recipe_quantity_is_greater_than_zero(qty: Any) -> None:
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(RECIPE, _recipe(qty=qty)))
    assert ("qty", "greater_than") in _locs(info)


@pytest.mark.parametrize("key,value", [("qty_base", 200), ("ingredient_external_id", "x1")])
def test_the_model_does_not_send_a_base_quantity_or_an_export_id(key: str, value: Any) -> None:
    with pytest.raises(ValidationError) as info:
        ProposeChangeArgs.model_validate(_args(RECIPE, _recipe(**{key: value})))
    assert (key, "extra_forbidden") in _locs(info)


def test_a_recipe_needs_lines_and_keeps_the_yield_rules() -> None:
    with pytest.raises(ValidationError):
        ProposeChangeArgs.model_validate(_args(RECIPE, {"yield_qty": 1, "lines": []}))
    for pct, ok in [(0, False), (-5, False), (55, True), (250, True), ("1000.0000", False)]:
        doc = _args(RECIPE, _recipe(yield_override_pct=pct))
        if ok:
            ProposeChangeArgs.model_validate(doc)
        else:
            with pytest.raises(ValidationError):
                ProposeChangeArgs.model_validate(doc)


def test_the_stored_recipe_keeps_the_base_quantity() -> None:
    """Unchanged persisted shape: qty_base and a free unit, as the importer produces it."""
    line = {"ingredient_name": "Carne", "qty_base": 200, "unit": "g"}
    parsed = STORED.validate_python(_stored(RECIPE, {"yield_qty": 1, "lines": [line]}))
    assert parsed.values.lines[0].qty_base == Decimal(200)
    with pytest.raises(ValidationError) as info:
        STORED.validate_python(_stored(RECIPE, _recipe()))
    assert ("qty", "extra_forbidden") in _locs(info)


# --- coherence between what the model sends and what is stored -------------------------------


def test_each_kind_has_the_input_variant_and_a_distinct_stored_payload() -> None:
    assert {
        PendingKind.ingredient_price_set: IngredientPriceInput,
        PendingKind.recipe_upsert: RecipeUpsertInput,
        PendingKind.menu_item_price_set: MenuItemPriceInput,
        PendingKind.import_batch_approve: NoPayload,
        PendingKind.import_batch_rollback: NoPayload,
    } == VALUES_FOR_KIND
    stored = {
        PendingKind.ingredient_price_set: IngredientPriceSet,
        PendingKind.recipe_upsert: RecipeUpsert,
        PendingKind.menu_item_price_set: MenuItemPriceSet,
    }
    for kind, stored_class in stored.items():
        assert VALUES_FOR_KIND[kind] is not stored_class


def test_the_tool_schema_has_no_centavos_no_ids_and_no_base_quantities() -> None:
    """The model never computes an amount in centavos, a base quantity or a unit conversion."""
    tool = next(t for t in tool_definitions() if t["name"] == "propose_change")
    schema = tool["input_schema"]
    names = {
        field
        for definition in schema["$defs"].values()
        for field in definition.get("properties", {})
    }
    assert not names & {"price_gross", "location_id", "qty_base", "base_unit", "target_id"}
    assert {"price_pesos", "location", "qty", "unit", "unit_price"} <= names
    units = [d for d in _enum_lists(schema) if d == UNITS]
    assert len(units) == 2  # the ingredient price and the recipe line, one closed list each


def _enum_lists(node: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(node, dict):
        if "enum" in node:
            found.append(node["enum"])
        for value in node.values():
            found += _enum_lists(value)
    elif isinstance(node, list):
        for item in node:
            found += _enum_lists(item)
    return found
