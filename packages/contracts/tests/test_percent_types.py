"""Calculated percentages (RPC results) and persisted percentages (database columns).

`Pct` carries a value the metric layer computes, so a legitimate change such as units going from
1 to 15 (+1400 %) must fit. `PercentPoints` mirrors `numeric(7,4)` columns and keeps their limit.
"""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.batch import Model
from mermia_contracts.decimals import ComputedPercent, PercentPoints
from mermia_contracts.pending import RecipeLine
from mermia_contracts.rpc import ComparePeriodsData, Meta, Pct

PERIODS = {"from": "2026-10-12", "to": "2026-10-18"}


def _fig(raw: Any) -> dict[str, Any]:
    return {"raw": raw, "text": str(raw)}


def _compare(a: int, b: int, pct: Any) -> dict[str, Any]:
    return {
        "metric": "units",
        "period_a": PERIODS,
        "period_b": {"from": "2026-10-05", "to": "2026-10-11"},
        "a": _fig(a),
        "b": _fig(b),
        "abs_change": _fig(a - b),
        "pct_change": None if pct is None else {"raw": pct, "text": f"{pct}%"},
    }


@pytest.mark.parametrize("raw", [1400, 1400.0, "1400", 123456.7891, -100, 0])
def test_a_calculated_percentage_can_exceed_the_column_limit(raw: Any) -> None:
    assert Pct.model_validate({"raw": raw, "text": "x"}).raw == Decimal(str(raw))


def test_one_to_fifteen_units_is_a_valid_compare_periods_answer() -> None:
    data = ComparePeriodsData.model_validate(_compare(15, 1, 1400))
    assert data.pct_change is not None
    assert data.pct_change.raw == Decimal("1400")


def test_calculated_percentages_keep_four_decimals() -> None:
    Pct.model_validate({"raw": "7.1234", "text": "x"})
    with pytest.raises(ValidationError) as info:
        Pct.model_validate({"raw": "7.12345", "text": "x"})
    assert info.value.errors()[0]["type"] == "decimal_max_places"


def test_coverage_in_meta_is_a_calculated_percentage() -> None:
    meta = {"as_of": "2026-10-19T08:00:00-06:00", "coverage_pct": 87.5, "period_resolved": PERIODS}
    assert Meta.model_validate(meta).coverage_pct == Decimal("87.5")


def test_persisted_percent_points_keep_the_numeric_7_4_limit() -> None:
    class Column(Model):
        x: PercentPoints

    assert Column.model_validate({"x": "999.9999"}).x == Decimal("999.9999")
    with pytest.raises(ValidationError) as info:
        Column.model_validate({"x": "1000.0000"})
    assert info.value.errors()[0]["type"] == "decimal_whole_digits"


def test_a_recipe_line_yield_still_mirrors_the_column() -> None:
    line = {"ingredient_name": "x", "qty_base": 1, "unit": "g", "yield_override_pct": 1000}
    with pytest.raises(ValidationError) as info:
        RecipeLine.model_validate(line)
    assert info.value.errors()[0]["type"] == "decimal_whole_digits"


def test_the_two_percent_types_are_different_types() -> None:
    assert ComputedPercent is not PercentPoints


@pytest.mark.parametrize("pct", [None])
def test_pct_change_is_null_when_the_base_period_is_zero(pct: Any) -> None:
    """The change is (a - b) / b: with b = 0 it is undefined, so it is null, never 0 or inf."""
    ComparePeriodsData.model_validate(_compare(5, 0, pct))
    with pytest.raises(ValidationError, match="base period"):
        ComparePeriodsData.model_validate(_compare(5, 0, 100))


def test_pct_change_may_be_null_when_the_base_is_not_zero() -> None:
    ComparePeriodsData.model_validate(_compare(5, 2, None))
