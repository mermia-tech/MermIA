"""compare_periods says which two date ranges it compared; the envelope's single range is null."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.rpc import RPCS, ComparePeriodsData, RpcEnvelope

EXAMPLES = Path(__file__).parent / "examples" / "rpc"


def _compare_example() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((EXAMPLES / "compare_periods.json").read_text())
    return doc


def _data() -> dict[str, Any]:
    data: dict[str, Any] = copy.deepcopy(_compare_example()["response"]["data"])
    return data


def test_the_example_carries_both_resolved_ranges() -> None:
    data = ComparePeriodsData.model_validate(_data())
    assert (str(data.period_a.from_), str(data.period_a.to)) == ("2026-10-05", "2026-10-11")
    assert (str(data.period_b.from_), str(data.period_b.to)) == ("2026-09-28", "2026-10-04")


@pytest.mark.parametrize("field", ["period_a", "period_b"])
def test_each_period_is_required(field: str) -> None:
    ComparePeriodsData.model_validate(_data())
    data = _data()
    del data[field]
    with pytest.raises(ValidationError) as info:
        ComparePeriodsData.model_validate(data)
    assert [(e["type"], e["loc"]) for e in info.value.errors()] == [("missing", (field,))]


@pytest.mark.parametrize("field", ["period_a", "period_b"])
def test_each_period_needs_from_not_after_to(field: str) -> None:
    data = _data()
    data[field] = {"from": "2026-10-18", "to": "2026-10-12"}
    with pytest.raises(ValidationError, match="must not be after"):
        ComparePeriodsData.model_validate(data)


@pytest.mark.parametrize("field", ["period_a", "period_b"])
@pytest.mark.parametrize("missing", ["from", "to"])
def test_each_period_needs_both_dates(field: str, missing: str) -> None:
    data = _data()
    del data[field][missing]
    with pytest.raises(ValidationError) as info:
        ComparePeriodsData.model_validate(data)
    assert info.value.errors()[0]["type"] == "missing"


def test_the_example_leaves_the_envelope_range_null() -> None:
    """Meta.period_resolved holds one range; compare_periods has two, so it carries none."""
    response = _compare_example()["response"]
    assert response["meta"]["period_resolved"] is None
    adapter = TypeAdapter(RpcEnvelope[ComparePeriodsData])
    assert adapter.validate_python(response).meta.period_resolved is None


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_an_explicit_range_in_the_arguments_is_the_resolved_range(path: Path) -> None:
    doc = json.loads(path.read_text())
    period = doc["args"].get("period")
    resolved = doc["response"]["meta"].get("period_resolved")
    if isinstance(period, dict) and resolved is not None:
        assert resolved == period


def test_only_compare_periods_has_two_ranges() -> None:
    # get_dish_margin's data is a union of models: no top-level fields to look at
    two = [
        n
        for n, spec in RPCS.items()
        if {"period_a", "period_b"} <= set(getattr(spec.data, "model_fields", {}))
    ]
    assert two == ["compare_periods"]
