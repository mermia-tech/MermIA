"""Bounds of the change payloads: prices, quantities and yields are strictly positive.

A zero or negative price makes a dish cost zero or negative; a zero yield (or yield_qty) is the
divisor of the cost formulas (03 C.6, MR-10 spec 7). `yield_override_pct` is edible portion over
purchased in percent (03 C.6): positive, and it keeps the numeric(7,4) column limit. There is no
100 % cap because the "Recetas" export that fills it is unverified (see the spec, section 6).
"""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.pending import ChangeProposal

ADAPTER: TypeAdapter[Any] = TypeAdapter(ChangeProposal)
TARGET = "0f7a1c52-3b6e-7c1a-9d33-000000000001"
DAY = "2026-10-19"


def _price(unit_price: Any) -> dict[str, Any]:
    return {"unit_price": unit_price, "effective_from": DAY}


def _menu(price_gross: Any) -> dict[str, Any]:
    return {
        "price_gross": price_gross,
        "location_id": "0f7a1c52-3b6e-7c1a-9d11-000000000001",
        "effective_from": DAY,
    }


def _recipe(yield_qty: Any = 1, qty_base: Any = 60, yield_pct: Any = None) -> dict[str, Any]:
    line: dict[str, Any] = {"ingredient_name": "Carne", "qty_base": qty_base, "unit": "g"}
    if yield_pct is not None:
        line["yield_override_pct"] = yield_pct
    return {"yield_qty": yield_qty, "lines": [line]}


def _proposal(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "target_id": TARGET, "values": values}


def _accepts(kind: str, values: dict[str, Any]) -> None:
    doc = _proposal(kind, values)
    ADAPTER.validate_python(doc)
    ADAPTER.validate_json(json.dumps(doc))


def _rejects(kind: str, values: dict[str, Any], loc: str, error: str) -> None:
    """Both entry paths fail at `loc` with `error`; the control (valid) case is tested apart."""
    doc = _proposal(kind, values)
    paths: list[Callable[[dict[str, Any]], Any]] = [
        ADAPTER.validate_python,
        lambda d: ADAPTER.validate_json(json.dumps(d)),
    ]
    for validate in paths:
        with pytest.raises(ValidationError) as info:
            validate(doc)
        found = [(".".join(map(str, e["loc"])), e["type"]) for e in info.value.errors()]
        assert (f"{kind}.values.{loc}", error) in found, found


@pytest.mark.parametrize("value", [0, 0.0, -5, "-0.000001", "0.000000"])
def test_ingredient_unit_price_must_be_greater_than_zero(value: Any) -> None:
    _accepts("ingredient_price.set", _price("0.000001"))
    _rejects("ingredient_price.set", _price(value), "unit_price", "greater_than")


@pytest.mark.parametrize("value", [0, -100, -1])
def test_menu_price_gross_must_be_greater_than_zero(value: int) -> None:
    _accepts("menu_item_price.set", _menu(1))
    _rejects("menu_item_price.set", _menu(value), "price_gross", "greater_than")


@pytest.mark.parametrize("value", [0, -1, "-0.5"])
def test_recipe_yield_qty_must_be_greater_than_zero(value: Any) -> None:
    _accepts("recipe.upsert", _recipe())
    _rejects("recipe.upsert", _recipe(yield_qty=value), "yield_qty", "greater_than")


@pytest.mark.parametrize("value", [0, -5, "-0.000001"])
def test_recipe_line_qty_base_must_be_greater_than_zero(value: Any) -> None:
    _accepts("recipe.upsert", _recipe())
    _rejects("recipe.upsert", _recipe(qty_base=value), "lines.0.qty_base", "greater_than")


@pytest.mark.parametrize("value", [0, 0.0, -50, "-0.0001"])
def test_yield_override_must_be_greater_than_zero(value: Any) -> None:
    _accepts("recipe.upsert", _recipe(yield_pct=55))
    _rejects(
        "recipe.upsert", _recipe(yield_pct=value), "lines.0.yield_override_pct", "greater_than"
    )


@pytest.mark.parametrize("value", ["0.0001", 55, 100, 250, "999.9999"])
def test_yield_override_has_no_cap_below_the_column_limit(value: Any) -> None:
    _accepts("recipe.upsert", _recipe(yield_pct=value))


def test_yield_override_keeps_the_numeric_7_4_column_limit() -> None:
    _rejects(
        "recipe.upsert",
        _recipe(yield_pct="1000.0000"),
        "lines.0.yield_override_pct",
        "decimal_whole_digits",
    )


def test_the_smallest_valid_values_are_exact() -> None:
    parsed = ADAPTER.validate_python(_proposal("ingredient_price.set", _price("0.000001")))
    assert parsed.values.unit_price == Decimal("0.000001")
