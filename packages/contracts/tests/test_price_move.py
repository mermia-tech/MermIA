"""PriceMove.new_unit_price: the number is per BASE unit, the text is what the model quotes.

`raw` stays pesos per g, ml or pza (the unit ingredient_price.unit_price_net is stored in), so
it never has to be converted by the model; `text` carries the amount in the unit the owner
thinks in ("$220.00/kg"), already formatted by the metric layer, and `base_unit` names what
`raw` is per. A bare number, which left the unit to be guessed, is no longer valid.
"""

import copy
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.rpc import CostAlertsData, PriceMove

EXAMPLE = Path(__file__).parent / "examples" / "rpc" / "get_cost_alerts.json"
# How many base units a display unit holds: the only conversions an example may use.
PER_DISPLAY_UNIT = {("g", "kg"): 1000, ("ml", "l"): 1000, ("g", "g"): 1, ("ml", "ml"): 1}
PER_DISPLAY_UNIT[("pza", "pza")] = 1


def _move() -> dict[str, Any]:
    data = json.loads(EXAMPLE.read_text())["response"]["data"]
    move: dict[str, Any] = copy.deepcopy(data["price_moves"][0])
    return move


def _price(**over: Any) -> dict[str, Any]:
    return {**_move()["new_unit_price"], **over}


def _with_price(price: Any) -> dict[str, Any]:
    return {**_move(), "new_unit_price": price}


def test_the_example_move_is_valid_and_keeps_the_price_per_base_unit() -> None:
    move = PriceMove.model_validate(_move())
    assert move.new_unit_price.base_unit == "g"
    assert move.new_unit_price.raw == Decimal("0.22")


@pytest.mark.parametrize("bare", [0.22, "0.22", 220, None])
def test_a_bare_number_no_longer_says_its_unit(bare: Any) -> None:
    PriceMove.model_validate(_move())
    with pytest.raises(ValidationError) as info:
        PriceMove.model_validate(_with_price(bare))
    assert info.value.errors()[0]["loc"] == ("new_unit_price",)


@pytest.mark.parametrize("missing", ["raw", "base_unit", "text"])
def test_the_price_needs_its_number_unit_and_text(missing: str) -> None:
    price = {k: v for k, v in _price().items() if k != missing}
    with pytest.raises(ValidationError) as info:
        PriceMove.model_validate(_with_price(price))
    assert [(e["loc"][-1], e["type"]) for e in info.value.errors()] == [(missing, "missing")]


@pytest.mark.parametrize("unit", ["kg", "l", "oz", "G", "", None])
def test_base_unit_is_g_ml_or_pza_never_a_purchase_unit(unit: Any) -> None:
    with pytest.raises(ValidationError) as info:
        PriceMove.model_validate(_with_price(_price(base_unit=unit)))
    assert info.value.errors()[0]["loc"][-1] == "base_unit"


@pytest.mark.parametrize("unit", ["g", "ml", "pza"])
def test_each_base_unit_is_accepted(unit: str) -> None:
    PriceMove.model_validate(_with_price(_price(base_unit=unit)))


@pytest.mark.parametrize("raw", [0, -0.1, "-0.000001"])
def test_a_price_per_base_unit_is_greater_than_zero(raw: Any) -> None:
    with pytest.raises(ValidationError) as info:
        PriceMove.model_validate(_with_price(_price(raw=raw)))
    assert ("raw", "greater_than") in [(e["loc"][-1], e["type"]) for e in info.value.errors()]


def test_the_price_per_base_unit_keeps_six_decimals_and_rejects_more() -> None:
    PriceMove.model_validate(_with_price(_price(raw="0.123456")))
    with pytest.raises(ValidationError) as info:
        PriceMove.model_validate(_with_price(_price(raw="0.1234567")))
    assert info.value.errors()[0]["type"] == "decimal_max_places"


def test_the_text_cannot_be_blank() -> None:
    with pytest.raises(ValidationError):
        PriceMove.model_validate(_with_price(_price(text=" ")))


def test_the_example_text_and_number_agree_through_the_display_unit() -> None:
    """The example quotes "$220.00/kg" for 0.22 pesos per g: 0.22 x 1000 = 220."""
    move = PriceMove.model_validate(_move())
    match = re.fullmatch(r"\$([0-9,]+\.[0-9]{2})/(\w+)", move.new_unit_price.text)
    assert match, move.new_unit_price.text
    amount, display = Decimal(match[1].replace(",", "")), match[2]
    factor = PER_DISPLAY_UNIT[(move.new_unit_price.base_unit.value, display)]
    assert move.new_unit_price.raw * factor == amount


def test_the_alert_example_validates_as_a_whole() -> None:
    doc = json.loads(EXAMPLE.read_text())["response"]["data"]
    assert len(CostAlertsData.model_validate(doc).price_moves) == 1
