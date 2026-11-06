"""MR-33: a price suggestion says what it suggests, why, and how sure the cost is.

Prices are menu prices with IVA (MR-11 spec 7.2). The figures are doc 12's Bistec: cost $27.90,
menu price $85.00 -> $90.00 (+5.9 %, 36.0 %), $101.14 to reach 32 %.
"""

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.rpc import PriceSuggestion, SuggestionRationale

BISTEC: dict[str, Any] = {
    "menu_item_id": "f6fdf947-ec26-5cd9-90c2-4255b53ceae8",
    "location_id": "705e8e51-376b-5785-adbb-405eff4e2a22",
    "name": "Orden de bistec",
    "current_price": {"raw": 8500, "text": "$85.00"},
    "target_price": {"raw": 10114, "text": "$101.14"},
    "suggested_price": {"raw": 9000, "text": "$90.00"},
    "change": {"raw": 5.8824, "text": "+5.9%"},
    "new_food_cost": {"raw": 35.9582, "text": "36.0%"},
    "confidence": "estimated",
    "rationale_code": "raise_capped",
}

REVIEW: dict[str, Any] = {
    **BISTEC,
    "suggested_price": None,
    "change": None,
    "new_food_cost": None,
    "rationale_code": "review_portion_cost",
}


def _with(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**copy.deepcopy(base), **changes}


def test_doc_12_bistec_is_a_capped_raise() -> None:
    s = PriceSuggestion.model_validate(BISTEC)
    assert s.rationale_code is SuggestionRationale.raise_capped
    assert s.suggested_price is not None and s.suggested_price.raw == 9000


def test_a_raise_that_reaches_the_target_says_so() -> None:
    reached = _with(
        BISTEC,
        suggested_price={"raw": 10500, "text": "$105.00"},
        change={"raw": 23.5294, "text": "+23.5%"},
        new_food_cost={"raw": 30.82, "text": "30.8%"},
    )
    with pytest.raises(ValidationError, match="raise_to_target"):
        PriceSuggestion.model_validate(reached)
    ok = PriceSuggestion.model_validate({**reached, "rationale_code": "raise_to_target"})
    assert ok.rationale_code is SuggestionRationale.raise_to_target


def test_a_review_carries_the_target_but_no_price() -> None:
    s = PriceSuggestion.model_validate(REVIEW)
    assert (s.suggested_price, s.change, s.new_food_cost) == (None, None, None)
    assert s.target_price.raw == 10114


@pytest.mark.parametrize("field", ["suggested_price", "change", "new_food_cost"])
def test_a_review_with_a_price_is_refused(field: str) -> None:
    with pytest.raises(ValidationError, match="review"):
        PriceSuggestion.model_validate(_with(REVIEW, **{field: BISTEC[field]}))


@pytest.mark.parametrize("field", ["suggested_price", "change", "new_food_cost"])
def test_a_raise_without_its_figures_is_refused(field: str) -> None:
    with pytest.raises(ValidationError, match="raise needs"):
        PriceSuggestion.model_validate(_with(BISTEC, **{field: None}))


@pytest.mark.parametrize(
    "field",
    ["suggested_price", "change", "new_food_cost", "menu_item_id", "location_id", "target_price"],
)
def test_every_field_is_required_even_when_null(field: str) -> None:
    omitted = {k: v for k, v in BISTEC.items() if k != field}
    with pytest.raises(ValidationError) as info:
        PriceSuggestion.model_validate(omitted)
    assert ((field,), "missing") in [(e["loc"], e["type"]) for e in info.value.errors()]


def test_never_a_decrease() -> None:
    lower = _with(
        BISTEC,
        suggested_price={"raw": 8000, "text": "$80.00"},
        change={"raw": -5.8824, "text": "-5.9%"},
    )
    with pytest.raises(ValidationError, match="never lowers"):
        PriceSuggestion.model_validate(lower)


def test_the_change_follows_the_prices() -> None:
    with pytest.raises(ValidationError, match="change"):
        PriceSuggestion.model_validate(_with(BISTEC, change={"raw": 6.7, "text": "+6.7%"}))


def test_a_missing_cost_is_no_suggestion() -> None:
    with pytest.raises(ValidationError, match="confirmed or estimated"):
        PriceSuggestion.model_validate(_with(BISTEC, confidence="missing"))


@pytest.mark.parametrize("field", ["current_price", "target_price"])
def test_prices_are_above_zero(field: str) -> None:
    with pytest.raises(ValidationError):
        PriceSuggestion.model_validate(_with(BISTEC, **{field: {"raw": 0, "text": "$0.00"}}))


def test_an_unknown_rationale_is_refused() -> None:
    with pytest.raises(ValidationError):
        PriceSuggestion.model_validate(_with(REVIEW, rationale_code="portion"))
