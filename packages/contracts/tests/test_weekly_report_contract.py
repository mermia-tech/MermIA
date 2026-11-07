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


# --- [Ver márgenes] (W4, doc 12 1b) -------------------------------------------------------------


def _breaches() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = _data()["cost_alerts"]["breaches"]
    return out


def _with_breach(i: int, **change: Any) -> dict[str, Any]:
    data = copy.deepcopy(_data())
    data["cost_alerts"]["breaches"][i] = {**data["cost_alerts"]["breaches"][i], **change}
    return data


def _with_at(i: int, k: int, **change: Any) -> dict[str, Any]:
    data = copy.deepcopy(_data())
    at = data["cost_alerts"]["breaches"][i]["at"]
    at[k] = {**at[k], **change}
    return data


def _raise_data() -> dict[str, Any]:
    out: dict[str, Any] = json.loads(EXAMPLE.with_suffix(".raise.json").read_text())["response"][
        "data"
    ]
    return out


def test_a_breach_line_of_ver_margenes_comes_from_the_payload() -> None:
    """Doc 12 1b: "*1. Costra de pastor* — costo $29.80, precio $89.00 → *38.8%*", then the
    suggestion of that dish at that location, labelled with the location's name; one line per
    location over target, worst first."""
    report = WeeklyReportData.model_validate(_data())
    names = {loc.location_id: loc.name for loc in report.locations}
    for b in report.cost_alerts.breaches:
        assert b.at and b.food_cost == b.at[0].food_cost
        for e in b.at:
            assert e.location_id in names
            assert e.net_price.raw <= e.price_gross.raw
            line = (
                f"{b.name} — costo {e.cost.text}, precio {e.price_gross.text} → {e.food_cost.text}"
            )
            assert "$" in line and line.endswith("%")
            if e.suggestion is not None:
                assert (e.suggestion.menu_item_id, e.suggestion.location_id) == (
                    b.menu_item_id,
                    e.location_id,
                )


def test_a_dish_over_target_at_two_locations_lists_both() -> None:
    """N2: Quesadilla over target at Centro (no suggestion) and at Polanco ($50 -> $55)."""
    report = WeeklyReportData.model_validate(_raise_data())
    names = {loc.location_id: loc.name for loc in report.locations}
    quesadilla = next(b for b in report.cost_alerts.breaches if b.name == "Quesadilla de queso")
    lines = [
        (
            names[e.location_id],
            e.price_gross.text,
            e.food_cost.text,
            e.suggestion and e.suggestion.suggested_price and e.suggestion.suggested_price.text,
        )
        for e in quesadilla.at
    ]
    assert lines == [("Centro", "$45.00", "50.0%", None), ("Polanco", "$50.00", "45.0%", "$55.00")]


def test_the_agent_tool_keeps_its_compact_breach() -> None:
    """The extra breach fields are the report's only: get_cost_alerts (doc 13) stays as is."""
    agent = ALL_RPCS["get_cost_alerts"].data.model_fields["breaches"].annotation
    report = WeeklyReportData.model_fields["cost_alerts"].annotation
    assert agent != report.model_fields["breaches"].annotation  # type: ignore[union-attr]
    plain = {
        k: v
        for k, v in _breaches()[0].items()
        if k in {"menu_item_id", "name", "food_cost", "target"}
    }
    TypeAdapter(agent).validate_python([plain])
    with pytest.raises(ValidationError):
        TypeAdapter(agent).validate_python([_breaches()[0]])


def _with_suggestion() -> tuple[int, dict[str, Any]]:
    """The first breach whose worst location has a review suggestion, and that suggestion."""
    i, b = next(
        (n, b)
        for n, b in enumerate(_breaches())
        if b["at"][0]["suggestion"]
        and b["at"][0]["suggestion"]["rationale_code"] == "review_portion_cost"
    )
    suggestion: dict[str, Any] = b["at"][0]["suggestion"]
    return i, suggestion


def test_a_breach_suggestion_is_for_the_same_dish_and_location() -> None:
    i, s = _with_suggestion()
    other = next(b["menu_item_id"] for b in _breaches() if b["menu_item_id"] != s["menu_item_id"])
    with pytest.raises(ValidationError, match="same dish and location"):
        WeeklyReportData.model_validate(_with_at(i, 0, suggestion={**s, "menu_item_id": other}))


def test_a_breach_suggestion_is_at_the_breach_menu_price() -> None:
    """N1: a suggestion priced on another menu price (or cost) is not on the line."""
    i, s = _with_suggestion()
    price = {"raw": s["current_price"]["raw"] + 100, "text": "x"}
    with pytest.raises(ValidationError, match="menu price"):
        WeeklyReportData.model_validate(_with_at(i, 0, suggestion={**s, "current_price": price}))


def test_a_breach_food_cost_is_its_cost_on_the_net_price() -> None:
    e = _breaches()[0]["at"][0]
    cost = {"raw": e["cost"]["raw"] + 500, "text": "x"}
    with pytest.raises(ValidationError, match="cost / net_price"):
        WeeklyReportData.model_validate(_with_at(0, 0, cost=cost))
    gross = {"raw": e["net_price"]["raw"] - 1, "text": "x"}
    with pytest.raises(ValidationError, match="net_price must not exceed price_gross"):
        WeeklyReportData.model_validate(_with_at(0, 0, price_gross=gross))


def test_a_breach_food_cost_is_its_worst_location() -> None:
    b = _breaches()[0]
    worse = {"raw": b["food_cost"]["raw"] + 1, "text": "x"}
    with pytest.raises(ValidationError, match="worst location"):
        WeeklyReportData.model_validate(_with_breach(0, food_cost=worse))
    with pytest.raises(ValidationError, match="at least 1"):
        WeeklyReportData.model_validate(_with_breach(0, at=[]))


def test_a_breach_lists_each_location_once_worst_first() -> None:
    data = _raise_data()
    i, b = next((n, b) for n, b in enumerate(data["cost_alerts"]["breaches"]) if len(b["at"]) > 1)
    WeeklyReportData.model_validate(data)
    swapped = copy.deepcopy(data)
    swapped["cost_alerts"]["breaches"][i]["at"] = b["at"][::-1]
    swapped["cost_alerts"]["breaches"][i]["food_cost"] = b["at"][-1]["food_cost"]
    with pytest.raises(ValidationError, match="worst first"):
        WeeklyReportData.model_validate(swapped)
    twice = copy.deepcopy(data)
    twice["cost_alerts"]["breaches"][i]["at"] = [b["at"][0], b["at"][0]]
    with pytest.raises(ValidationError, match="each location once"):
        WeeklyReportData.model_validate(twice)


def test_a_breach_location_is_over_target() -> None:
    e = _breaches()[0]["at"][0]
    under = copy.deepcopy(_data())
    b = under["cost_alerts"]["breaches"][0]
    cost = e["net_price"]["raw"] * 30 // 100
    pct = round(100 * cost / e["net_price"]["raw"], 3)
    b["at"] = [
        {
            **e,
            "cost": {"raw": cost, "text": "x"},
            "food_cost": {"raw": pct, "text": "x"},
            "suggestion": None,
        }
    ]
    b["food_cost"] = b["at"][0]["food_cost"]
    with pytest.raises(ValidationError, match="over target"):
        WeeklyReportData.model_validate(under)


def test_a_breach_is_at_a_location_of_the_report() -> None:
    _reject({"locations": _data()["locations"][:1]}, "location of the report")
    _reject({"locations": [_data()["locations"][0]] * 2}, "locations are distinct")
