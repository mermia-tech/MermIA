"""MR-34: the build_weekly_report contract (a report RPC, not an agent tool)."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.agent_tools import tool_definitions
from mermia_contracts.rpc import (
    ALL_RPCS,
    REPORT_RPCS,
    RPCS,
    BuildWeeklyReportArgs,
    RpcEnvelope,
    WeeklyReportData,
)

EXAMPLE = Path(__file__).parent / "examples" / "rpc" / "build_weekly_report.json"
ENVELOPE: TypeAdapter[Any] = TypeAdapter(RpcEnvelope[WeeklyReportData])


def _data() -> dict[str, Any]:
    out: dict[str, Any] = json.loads(EXAMPLE.read_text())["response"]["data"]
    return out


def test_the_report_is_a_report_rpc_not_an_agent_tool() -> None:
    assert list(REPORT_RPCS) == ["build_weekly_report"]
    assert not set(REPORT_RPCS) & set(RPCS)
    assert ALL_RPCS == RPCS | REPORT_RPCS
    assert "build_weekly_report" not in {t["name"] for t in tool_definitions()}


@pytest.mark.parametrize(
    "period",
    ["last_week", "prev_week", {"from": "2026-10-05", "to": "2026-10-11"}],
    ids=["last_week", "prev_week", "monday-to-sunday"],
)
def test_args_accept_a_whole_week(period: Any) -> None:
    BuildWeeklyReportArgs.model_validate({"period": period})


def test_args_default_to_last_week_for_the_whole_business() -> None:
    args = BuildWeeklyReportArgs.model_validate({})
    assert (args.period, args.location_id) == ("last_week", None)


@pytest.mark.parametrize(
    "period",
    [
        "this_week",
        "last_7d",
        "last_month",
        {"from": "2026-10-06", "to": "2026-10-12"},  # Tuesday to Monday
        {"from": "2026-10-05", "to": "2026-10-10"},  # six days
        {"from": "2026-09-28", "to": "2026-10-11"},  # two weeks
    ],
    ids=str,
)
def test_args_reject_anything_but_a_monday_to_sunday_week(period: Any) -> None:
    with pytest.raises(ValidationError):
        BuildWeeklyReportArgs.model_validate({"period": period})


def test_the_example_parses() -> None:
    envelope = ENVELOPE.validate_json(json.dumps(json.loads(EXAMPLE.read_text())["response"]))
    assert envelope.ok and envelope.data is not None
    assert envelope.data.sales.net_sales.raw == 34524130


def test_food_cost_may_be_null_but_not_left_out() -> None:
    data = _data()
    WeeklyReportData.model_validate({**data, "food_cost": None})
    with pytest.raises(ValidationError, match="food_cost"):
        WeeklyReportData.model_validate({k: v for k, v in data.items() if k != "food_cost"})


def _reject(change: dict[str, Any], reason: str) -> None:
    good = _data()
    WeeklyReportData.model_validate(good)
    with pytest.raises(ValidationError, match=reason):
        WeeklyReportData.model_validate({**copy.deepcopy(good), **change})


def test_the_week_runs_monday_to_sunday() -> None:
    _reject(
        {
            "week": {"from": "2026-10-06", "to": "2026-10-12"},
            "previous_week": {"from": "2026-09-29", "to": "2026-10-05"},
        },
        "week must run Monday to Sunday",
    )


def test_the_previous_week_is_the_week_before() -> None:
    _reject(
        {"previous_week": {"from": "2026-09-21", "to": "2026-09-27"}},
        "previous_week must be the week before",
    )


def test_top_dishes_are_the_top_three_by_units() -> None:
    top = _data()["top_dishes"]
    four = {**top, "rows": [*top["rows"], {**top["rows"][-1], "rank": 4}]}
    _reject({"top_dishes": four}, "top 3 by units")
    by_revenue = {
        "metric": "revenue",
        "rows": [{**r, "value": {"raw": 100, "text": "$1.00"}} for r in top["rows"]],
    }
    _reject({"top_dishes": by_revenue}, "top 3 by units")


def test_missing_days_fall_in_the_week_once_and_in_order() -> None:
    WeeklyReportData.model_validate({**_data(), "missing_business_days": ["2026-10-11"]})
    _reject({"missing_business_days": ["2026-10-12"]}, "must fall in the week")
    _reject({"missing_business_days": ["2026-10-11", "2026-10-05"]}, "distinct and in order")
    _reject({"missing_business_days": ["2026-10-11", "2026-10-11"]}, "distinct and in order")
