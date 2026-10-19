"""Figure.raw has one scale per metric: centavos, a count, or percent points.

The unit is not a field of Figure; it follows from the `metric` that travels beside it
(rpc.METRIC_UNIT). These tests pin the table, the checks it drives and the agreement between
RPCs that report the same amount.
"""

import json
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from mermia_contracts.rpc import (
    METRIC_UNIT,
    CompareLocationsData,
    CompareMetric,
    ComparePeriodsData,
    Figure,
    SalesSummaryData,
    TopDishesData,
    TopMetric,
)

EXAMPLES = Path(__file__).parent / "examples" / "rpc"
LOC = "0f7a1c52-3b6e-7c1a-9d11-000000000001"
DISH = "0f7a1c52-3b6e-7c1a-9d22-000000000001"
MONEY = [m for m, u in METRIC_UNIT.items() if u == "centavos"]


def _fig(raw: Any) -> dict[str, Any]:
    return {"raw": raw, "text": str(raw)}


def _compare(metric: str, a: Any, b: Any, change: Any) -> dict[str, Any]:
    return {
        "metric": metric,
        "period_a": {"from": "2026-10-12", "to": "2026-10-18"},
        "period_b": {"from": "2026-10-05", "to": "2026-10-11"},
        "a": _fig(a),
        "b": _fig(b),
        "abs_change": _fig(change),
    }


def _locations(metric: str, value: Any, diff: Any) -> dict[str, Any]:
    row = {"location_id": LOC, "name": "Centro", "value": _fig(value), "rank": 1}
    return {"metric": metric, "rows": [{**row, "diff_vs_best": _fig(diff)}]}


def _dishes(metric: str, value: Any) -> dict[str, Any]:
    return {
        "metric": metric,
        "rows": [{"rank": 1, "menu_item_id": DISH, "name": "Taco", "value": _fig(value)}],
    }


def test_the_table_names_a_unit_for_every_metric_of_every_rpc() -> None:
    assert set(METRIC_UNIT) == set(get_args(CompareMetric)) | set(get_args(TopMetric))


def test_the_table_pins_the_agreed_units() -> None:
    assert METRIC_UNIT == {
        "net_sales": "centavos",
        "avg_ticket": "centavos",
        "revenue": "centavos",
        "margin": "centavos",
        "tickets": "count",
        "guests": "count",
        "units": "quantity",
        "food_cost_pct": "percent_points",
        "margin_pct": "percent_points",
    }


def test_the_figure_schema_tells_the_reader_where_the_unit_comes_from() -> None:
    description = Figure.model_json_schema()["description"]
    assert "METRIC_UNIT" in description and "centavos" in description


@pytest.mark.parametrize("metric", [m for m in MONEY if m in get_args(CompareMetric)])
def test_compare_periods_money_is_whole_centavos(metric: str) -> None:
    ComparePeriodsData.model_validate(_compare(metric, 18432050, 17190500, 1241550))
    with pytest.raises(ValidationError, match="whole centavos"):
        ComparePeriodsData.model_validate(_compare(metric, 184320.5, 171905, 12415.5))


@pytest.mark.parametrize("metric", [m for m in MONEY if m in get_args(CompareMetric)])
def test_the_same_pesos_in_pesos_instead_of_centavos_is_a_fractional_centavo(metric: str) -> None:
    """184,320.50 pesos written as 184320.50 is the 100x mix-up: it must not pass as money."""
    with pytest.raises(ValidationError, match="whole centavos"):
        ComparePeriodsData.model_validate(_compare(metric, "184320.50", 0, "184320.50"))


@pytest.mark.parametrize("metric", ["tickets", "guests"])
def test_counts_are_whole_numbers(metric: str) -> None:
    ComparePeriodsData.model_validate(_compare(metric, 15, 1, 14))
    with pytest.raises(ValidationError, match="whole number"):
        ComparePeriodsData.model_validate(_compare(metric, 15.5, 1, 14.5))


def test_units_sold_are_a_quantity_with_up_to_six_decimals() -> None:
    """item_sales_agg.units and sale_line.qty are numeric(18,6): a barbacoa sold by the kilo."""
    ComparePeriodsData.model_validate(_compare("units", "12.5", 10, "2.5"))
    ComparePeriodsData.model_validate(_compare("units", "0.000001", 0, "0.000001"))
    ComparePeriodsData.model_validate(_compare("units", 15, 1, 14))  # whole units still fit
    with pytest.raises(ValidationError) as info:
        ComparePeriodsData.model_validate(_compare("units", "0.0000001", 0, "0.0000001"))
    assert info.value.errors()[0]["type"] == "decimal_max_places"


def test_a_change_in_units_sold_is_exact() -> None:
    """Quantities add up exactly (no rounding), so abs_change is a - b with no tolerance."""
    with pytest.raises(ValidationError, match="abs_change"):
        ComparePeriodsData.model_validate(_compare("units", "12.5", 10, "2.500001"))


def test_percent_metrics_keep_up_to_four_decimals() -> None:
    ComparePeriodsData.model_validate(_compare("food_cost_pct", "36.4", "32.0001", "4.3999"))
    with pytest.raises(ValidationError, match="four decimals"):
        ComparePeriodsData.model_validate(_compare("food_cost_pct", "36.40001", 32, "4.40001"))


def test_abs_change_is_a_minus_b() -> None:
    with pytest.raises(ValidationError, match="abs_change"):
        ComparePeriodsData.model_validate(_compare("net_sales", 18432050, 17190500, 1))


@pytest.mark.parametrize(
    "metric,a,b,change,ok",
    [
        ("avg_ticket", 1000, 501, 500, True),  # true 1000.4 and 500.6: round(499.8) = 500
        ("avg_ticket", 1000, 501, 499, True),  # a - b exactly
        ("avg_ticket", 1000, 501, 498, True),  # a - b = 499, one centavo off
        ("avg_ticket", 1000, 501, 497, False),
        ("avg_ticket", 1000, 501, 501, False),  # two centavos off
        ("food_cost_pct", "10.0000", "5.0001", "5.0000", True),  # true 10.00004 and 5.00006
        ("food_cost_pct", "10.0000", "5.0001", "4.9999", True),
        ("food_cost_pct", "10.0000", "5.0001", "5.0001", False),
        ("tickets", 15, 1, 14, True),
        ("tickets", 15, 1, 15, False),  # counts are exact
    ],
)
def test_abs_change_may_differ_from_a_minus_b_by_the_rounding_of_its_scale(
    metric: str, a: Any, b: Any, change: Any, ok: bool
) -> None:
    """a, b and abs_change are each rounded once from unrounded values, so the difference of
    the rounded ones can be one unit off: a centavo, or 0.0001 percent points. Counts are exact."""
    doc = _compare(metric, a, b, change)
    if ok:
        ComparePeriodsData.model_validate(doc)
    else:
        with pytest.raises(ValidationError, match="abs_change"):
            ComparePeriodsData.model_validate(doc)


def test_compare_locations_checks_value_and_diff_with_the_metric_unit() -> None:
    CompareLocationsData.model_validate(_locations("net_sales", 12000000, -5567950))
    for value, diff in [(120000.5, 0), (12000000, -55679.5)]:
        with pytest.raises(ValidationError, match="whole centavos"):
            CompareLocationsData.model_validate(_locations("net_sales", value, diff))


@pytest.mark.parametrize("metric", ["revenue", "margin"])
def test_top_dishes_money_metrics_are_whole_centavos(metric: str) -> None:
    TopDishesData.model_validate(_dishes(metric, 4200000))
    with pytest.raises(ValidationError, match="whole centavos"):
        TopDishesData.model_validate(_dishes(metric, 42000.5))


def test_top_dishes_units_are_a_quantity_and_margin_pct_are_percent_points() -> None:
    TopDishesData.model_validate(_dishes("units", 640))
    TopDishesData.model_validate(_dishes("units", "12.5"))  # sold by the kilo
    TopDishesData.model_validate(_dishes("margin_pct", "67.1631"))
    with pytest.raises(ValidationError) as info:
        TopDishesData.model_validate(_dishes("units", "12.1234567"))
    assert info.value.errors()[0]["type"] == "decimal_max_places"


def test_compare_locations_units_may_be_fractional() -> None:
    CompareLocationsData.model_validate(_locations("units", "12.5", "-2.25"))


def _example(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((EXAMPLES / f"{name}.json").read_text())
    data: dict[str, Any] = doc["response"]["data"]
    return data


def test_the_same_amount_has_the_same_raw_in_get_sales_summary_and_compare_periods() -> None:
    """Both examples ask about last_week: one is a Money, the other the Figure for net_sales."""
    summary = SalesSummaryData.model_validate(_example("get_sales_summary"))
    compare = ComparePeriodsData.model_validate(_example("compare_periods"))
    assert compare.metric == "net_sales"
    assert compare.a.raw == summary.net_sales.raw
    assert compare.a.text == summary.net_sales.text
