"""Figures the data may not have are null, never zero (MR-10 spec 5.5: not reported is not zero).

`daily_sales_agg.tickets`, `guests`, `discounts` and `cancellations_amount` and
`daily_location_metrics.avg_ticket` are nullable; `item_sales_agg` has no ticket count; the
`price_suggestion` table has no `menu_item_id` and no current price. The fields stay REQUIRED
where they are nullable (a key that is left out is an error), except the two optional ones of
PriceSuggestion.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.rpc import BreakdownRow, PriceSuggestion, SalesSummaryData

EXAMPLES = Path(__file__).parent / "examples" / "rpc"
NULLABLE = ["tickets", "avg_ticket", "guests", "discounts", "cancellations"]


def _summary() -> dict[str, Any]:
    doc = json.loads((EXAMPLES / "get_sales_summary.json").read_text())
    data: dict[str, Any] = copy.deepcopy(doc["response"]["data"])
    return data


@pytest.mark.parametrize("field", NULLABLE)
def test_each_unreported_summary_figure_may_be_null(field: str) -> None:
    SalesSummaryData.model_validate(_summary())
    data = {**_summary(), field: None}
    assert getattr(SalesSummaryData.model_validate(data), field) is None


def test_a_summary_with_only_net_sales_reported() -> None:
    data = {**dict.fromkeys(NULLABLE), "net_sales": _summary()["net_sales"]}
    summary = SalesSummaryData.model_validate(data)
    assert [getattr(summary, f) for f in NULLABLE] == [None] * 5


@pytest.mark.parametrize("field", NULLABLE)
def test_a_reported_zero_stays_zero_and_is_not_null(field: str) -> None:
    zero: Any = 0 if field in ("tickets", "guests") else {"raw": 0, "text": "$0.00"}
    summary = SalesSummaryData.model_validate({**_summary(), field: zero})
    value = getattr(summary, field)
    assert value is not None
    assert (value if isinstance(value, int) else value.raw) == 0


@pytest.mark.parametrize("field", NULLABLE)
def test_a_figure_that_is_left_out_is_an_error_not_a_null(field: str) -> None:
    data = _summary()
    del data[field]
    with pytest.raises(ValidationError) as info:
        SalesSummaryData.model_validate(data)
    assert [(e["loc"], e["type"]) for e in info.value.errors()] == [((field,), "missing")]


def test_net_sales_is_always_reported() -> None:
    data = {**dict.fromkeys(NULLABLE), "net_sales": None}
    with pytest.raises(ValidationError):
        SalesSummaryData.model_validate(data)


@pytest.mark.parametrize("field,bad", [("tickets", 1.5), ("tickets", -1), ("guests", "3")])
def test_a_reported_figure_is_still_validated(field: str, bad: Any) -> None:
    with pytest.raises(ValidationError):
        SalesSummaryData.model_validate({**_summary(), field: bad})


def _row() -> dict[str, Any]:
    return {
        "key": "Tacos",
        "net_sales": {"raw": 5000000, "text": "$50,000.00"},
        "tickets": 120,
        "share": {"raw": "27.1", "text": "27.1%"},
    }


def test_a_breakdown_row_without_a_ticket_count_is_valid() -> None:
    """A category breakdown from Productos vendidos has no tickets: it is null, not invented."""
    row = BreakdownRow.model_validate({**_row(), "tickets": None})
    assert row.tickets is None
    assert BreakdownRow.model_validate(_row()).tickets == 120


def test_a_breakdown_row_that_omits_tickets_is_an_error() -> None:
    data = {k: v for k, v in _row().items() if k != "tickets"}
    with pytest.raises(ValidationError) as info:
        BreakdownRow.model_validate(data)
    assert info.value.errors()[0]["type"] == "missing"


def test_zero_tickets_in_a_breakdown_row_stays_zero() -> None:
    assert BreakdownRow.model_validate({**_row(), "tickets": 0}).tickets == 0


def _suggestion() -> dict[str, Any]:
    return {
        "menu_item_id": "0f7a1c52-3b6e-7c1a-9d22-000000000001",
        "name": "Taco al pastor",
        "current_price": {"raw": 5000, "text": "$50.00"},
        "suggested_price": {"raw": 5500, "text": "$55.00"},
    }


@pytest.mark.parametrize("field", ["menu_item_id", "current_price"])
def test_the_dish_id_and_the_current_price_of_a_suggestion_are_optional(field: str) -> None:
    PriceSuggestion.model_validate(_suggestion())
    omitted = {k: v for k, v in _suggestion().items() if k != field}
    assert getattr(PriceSuggestion.model_validate(omitted), field) is None
    assert getattr(PriceSuggestion.model_validate({**_suggestion(), field: None}), field) is None


def test_a_suggestion_still_needs_a_name_and_a_suggested_price() -> None:
    for field in ("name", "suggested_price"):
        omitted = {k: v for k, v in _suggestion().items() if k != field}
        with pytest.raises(ValidationError) as info:
            PriceSuggestion.model_validate(omitted)
        assert [(e["loc"], e["type"]) for e in info.value.errors()] == [((field,), "missing")]


def test_a_suggestion_with_neither_optional_field_is_valid() -> None:
    bare = {"name": "Taco al pastor", "suggested_price": {"raw": 5500, "text": "$55.00"}}
    suggestion = PriceSuggestion.model_validate(bare)
    assert (suggestion.menu_item_id, suggestion.current_price) == (None, None)


@pytest.mark.parametrize("name", ["get_sales_summary.nulls", "get_sales_breakdown.no_tickets"])
def test_the_null_examples_exist_and_carry_nulls(name: str) -> None:
    doc = json.loads((EXAMPLES / f"{name}.json").read_text())
    data = doc["response"]["data"]
    text = json.dumps(data)
    assert "null" in text
