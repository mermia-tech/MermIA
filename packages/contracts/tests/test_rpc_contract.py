"""C3: the 11 RPC contracts parse their examples and reject malformed input."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.rpc import RPCS, RpcEnvelope

EXAMPLES = Path(__file__).parent / "examples" / "rpc"
FILES = sorted(EXAMPLES.glob("*.json"))
NAMES = [
    "get_sales_summary",
    "compare_periods",
    "compare_locations",
    "get_top_dishes",
    "get_sales_breakdown",
    "get_cancellations",
    "get_dish_margin",
    "get_food_cost_pct",
    "get_menu_engineering",
    "get_cost_alerts",
    "get_data_status",
]


def _envelope(name: str) -> TypeAdapter[Any]:
    return TypeAdapter(RpcEnvelope[RPCS[name].data])  # type: ignore[misc,arg-type]


def test_registry_has_the_eleven_rpcs_in_order() -> None:
    assert list(RPCS) == NAMES


def test_every_rpc_has_an_example() -> None:
    assert {p.name.split(".")[0] for p in FILES} >= set(NAMES)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_examples_parse_and_round_trip(path: Path) -> None:
    name = path.name.split(".")[0]
    example = json.loads(path.read_text())
    RPCS[name].args.model_validate(example["args"])
    adapter = _envelope(name)
    parsed = adapter.validate_json(json.dumps(example["response"]))
    assert adapter.validate_json(adapter.dump_json(parsed, by_alias=True)) == parsed


def _ok_summary() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((EXAMPLES / "get_sales_summary.json").read_text())
    response: dict[str, Any] = doc["response"]
    return response


def _summary_with(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    doc = _ok_summary()
    node = doc
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return doc


@pytest.mark.parametrize(
    "doc",
    [
        _summary_with(("data", "net_sales", "raw"), 1843205.5),  # float money
        _summary_with(("data", "net_sales", "raw"), "18432050"),  # string money
        _summary_with(("data", "tickets"), -1),
        _summary_with(("data", "surprise"), 1),  # unknown field
        _summary_with(("meta", "as_of"), "2026-10-19T08:00:00"),  # no time zone
    ],
    ids=["float-money", "string-money", "negative-count", "unknown-field", "naive-instant"],
)
def test_malformed_responses_are_rejected(doc: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _envelope("get_sales_summary").validate_python(doc)


def _error() -> dict[str, Any]:
    return {"code": "no_data", "message": "x"}


@pytest.mark.parametrize(
    "patch",
    [
        {"data": None},  # ok=true, no data
        {"error": _error()},  # ok=true with an error
    ],
    ids=["ok-no-data", "ok-with-error"],
)
def test_envelope_ok_true_inconsistencies(patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _envelope("get_sales_summary").validate_python({**_ok_summary(), **patch})


@pytest.mark.parametrize(
    "patch",
    [
        {"error": None},  # ok=false, no error
        {"data": _ok_summary()["data"]},  # ok=false with data
        {"error": {"code": "boom", "message": "x"}},  # code outside the closed list
    ],
    ids=["fail-no-error", "fail-with-data", "unknown-code"],
)
def test_envelope_ok_false_inconsistencies(patch: dict[str, Any]) -> None:
    error_doc = json.loads((EXAMPLES / "get_sales_summary.error.json").read_text())["response"]
    with pytest.raises(ValidationError):
        _envelope("get_sales_summary").validate_python({**error_doc, **patch})


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_top_dishes", {"period": "today", "metric": "units", "limit": 11}),
        ("get_top_dishes", {"period": "today", "metric": "units", "limit": 0}),
        ("get_top_dishes", {"period": "today", "metric": "profit"}),
        ("get_sales_breakdown", {"period": "today", "by": "mood"}),
        ("get_cancellations", {"period": "today", "kind": "refunds"}),
        ("compare_periods", {"metric": "net_sales", "period_a": "today"}),
        ("get_sales_summary", {"period": "next_year"}),
        ("get_sales_summary", {"period": {"from": "2026-10-07", "to": "2026-10-01"}}),
        ("get_sales_summary", {"period": "today", "tenant_id": "x"}),
        ("get_dish_margin", {"dish": " "}),
    ],
)
def test_bad_arguments_are_rejected(name: str, args: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RPCS[name].args.model_validate(args)


def test_custom_period_uses_the_from_alias() -> None:
    args = RPCS["get_sales_summary"].args.model_validate(
        {"period": {"from": "2026-10-01", "to": "2026-10-07"}}
    )
    assert json.loads(args.model_dump_json())["period"]["from"] == "2026-10-01"


def test_top_dishes_defaults() -> None:
    args = RPCS["get_top_dishes"].args.model_validate({"period": "today", "metric": "units"})
    assert (args.order, args.limit) == ("desc", 5)  # type: ignore[attr-defined]
