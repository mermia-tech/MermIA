"""get_dish_margin: margin and food cost are on the NET price (without IVA).

Pastor at Centro: cost $18.40, menu price $65.00 with IVA, so the net price is $56.03.
On net: margin $37.63 = 67.16 % and food cost 32.84 %. On the gross menu price the same dish
would read 71.69 % and 28.31 %, which is a different business number: this contract never
reports it. `price_gross` is only there to quote the menu price.
"""

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.rpc import DishMarginResolved

EXAMPLES = Path(__file__).parent / "examples" / "rpc"


def _money(cents: int) -> dict[str, Any]:
    return {"raw": cents, "text": f"${cents // 100}.{cents % 100:02d}"}


def _pct(raw: str) -> dict[str, Any]:
    return {"raw": raw, "text": f"{raw}%"}


def _pastor(**over: Any) -> dict[str, Any]:
    """Centro's pastor with the numbers of the module docstring."""
    doc: dict[str, Any] = {
        "match": "resolved",
        "menu_item_id": "0f7a1c52-3b6e-7c1a-9d22-000000000001",
        "name": "Tacos al pastor",
        "cost": _money(1840),
        "price_gross": _money(6500),
        "net_price": _money(5603),
        "margin": _money(3763),
        "margin_pct": _pct("67.1604"),
        "food_cost": _pct("32.8396"),
        "confidence": "confirmed",
        "cost_drivers": [],
    }
    return {**doc, **over}


def _example() -> dict[str, Any]:
    doc = json.loads((EXAMPLES / "get_dish_margin.json").read_text())
    data: dict[str, Any] = doc["response"]["data"]
    return data


def _rejects(doc: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        DishMarginResolved.model_validate(doc)


def test_the_pastor_on_net_price_is_valid() -> None:
    dish = DishMarginResolved.model_validate(_pastor())
    assert dish.margin_pct.raw == Decimal("67.1604")
    assert dish.food_cost.raw == Decimal("32.8396")


def test_the_example_is_consistent_and_quotes_both_prices() -> None:
    dish = DishMarginResolved.model_validate(_example())
    assert dish.price_gross.raw >= dish.net_price.raw
    assert dish.margin.raw == dish.net_price.raw - dish.cost.raw


def test_the_gross_basis_pair_is_rejected() -> None:
    """71.69 % is (65.00 - 18.40) / 65.00 and 28.31 % is 18.40 / 65.00: they add up to 100 and
    are consistent with each other, but they are on the gross price, which this contract excludes.
    """
    _rejects(
        _pastor(margin_pct=_pct("71.6923"), food_cost=_pct("28.3077")),
        "must follow .* net_price",
    )


def test_only_the_margin_pct_on_the_gross_price_is_rejected() -> None:
    _rejects(_pastor(margin_pct=_pct("71.6923")), "margin_pct and food_cost must add up to 100")


def test_margin_must_be_net_price_minus_cost() -> None:
    _rejects(_pastor(margin=_money(3763 + 1)), "margin must equal net_price - cost")
    _rejects(_pastor(margin=_money(6500 - 1840)), "margin must equal net_price - cost")


def test_margin_pct_and_food_cost_add_up_to_one_hundred() -> None:
    DishMarginResolved.model_validate(
        _pastor(margin_pct=_pct("67.1605"), food_cost=_pct("32.8396"))
    )
    _rejects(_pastor(margin_pct=_pct("67.1604"), food_cost=_pct("32.8500")), "add up to 100")


def test_percentages_follow_the_amounts_within_the_rounding_of_centavos() -> None:
    """Cost and prices are rounded to the centavo; the percentages come from unrounded values."""
    DishMarginResolved.model_validate(
        _pastor(food_cost=_pct("32.8450"), margin_pct=_pct("67.1550"))
    )
    _rejects(
        _pastor(food_cost=_pct("32.9000"), margin_pct=_pct("67.1000")), "food_cost must follow"
    )


def test_net_price_cannot_exceed_the_menu_price() -> None:
    _rejects(
        _pastor(net_price=_money(6501), margin=_money(6501 - 1840)),
        "net_price must not exceed price_gross",
    )


@pytest.mark.parametrize("field", ["net_price", "price_gross"])
def test_a_resolved_dish_has_a_price_greater_than_zero(field: str) -> None:
    doc = _pastor(**{field: _money(0)})
    with pytest.raises(ValidationError) as info:
        DishMarginResolved.model_validate(doc)
    assert ((field, "raw"), "greater_than") in [
        (tuple(e["loc"][-2:]), e["type"]) for e in info.value.errors()
    ]


@pytest.mark.parametrize("field", ["price_gross", "margin_pct"])
def test_the_new_fields_are_required(field: str) -> None:
    doc = copy.deepcopy(_pastor())
    del doc[field]
    with pytest.raises(ValidationError) as info:
        DishMarginResolved.model_validate(doc)
    assert [(e["loc"][-1], e["type"]) for e in info.value.errors()] == [(field, "missing")]


def test_a_dish_can_sell_below_cost_and_have_a_negative_margin() -> None:
    dish = DishMarginResolved.model_validate(
        _pastor(
            cost=_money(7000),
            margin=_money(5603 - 7000),
            margin_pct=_pct("-24.9331"),
            food_cost=_pct("124.9331"),
        )
    )
    assert dish.margin.raw == -1397
