"""get_dish_margin without a location never picks one for the caller.

Prices (`menu_item_price`) and cost snapshots (`dish_cost_snapshot`) are per location while a
dish is shared by the tenant. With `location_id` missing and no single location to answer for,
the answer is `needs_location` (the dish and the locations to choose from), never a margin of an
arbitrary location. A resolved margin says which location it is for.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.agent import MetricCardMsg
from mermia_contracts.rpc import RPCS, DishMarginNeedsLocation, DishMarginResolved, RpcEnvelope

EXAMPLES = Path(__file__).parent / "examples" / "rpc"
DISH = "0f7a1c52-3b6e-7c1a-9d22-000000000001"
CENTRO = "0f7a1c52-3b6e-7c1a-9d11-000000000001"
POLANCO = "0f7a1c52-3b6e-7c1a-9d11-000000000002"


def _adapter(tp: Any) -> TypeAdapter[Any]:
    return TypeAdapter(tp)


ADAPTER = _adapter(RPCS["get_dish_margin"].data)


def _needs(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "match": "needs_location",
        "menu_item_id": DISH,
        "name": "Tacos al pastor",
        "locations": [
            {"location_id": CENTRO, "name": "Centro"},
            {"location_id": POLANCO, "name": "Polanco"},
        ],
    }
    return {**doc, **over}


def _resolved() -> dict[str, Any]:
    doc = json.loads((EXAMPLES / "get_dish_margin.json").read_text())
    data: dict[str, Any] = copy.deepcopy(doc["response"]["data"])
    return data


def _errors(doc: dict[str, Any]) -> list[tuple[tuple[Any, ...], str]]:
    with pytest.raises(ValidationError) as info:
        ADAPTER.validate_python(doc)
    return [(tuple(e["loc"]), e["type"]) for e in info.value.errors()]


def test_the_union_picks_the_variant_by_match() -> None:
    assert isinstance(ADAPTER.validate_python(_needs()), DishMarginNeedsLocation)
    assert isinstance(ADAPTER.validate_python(_resolved()), DishMarginResolved)


def test_a_resolved_margin_says_which_location_it_is_for() -> None:
    assert _resolved()["location_id"] == CENTRO
    data = _resolved()
    del data["location_id"]
    assert (("resolved", "location_id"), "missing") in _errors(data)


def test_needs_location_carries_no_margin_figures() -> None:
    for extra in ("cost", "net_price", "margin", "margin_pct", "food_cost", "confidence"):
        assert (("needs_location", extra), "extra_forbidden") in _errors({**_needs(), extra: 1})


def test_a_resolved_margin_cannot_also_list_locations() -> None:
    bad = {**_resolved(), "locations": _needs()["locations"]}
    assert (("resolved", "locations"), "extra_forbidden") in _errors(bad)


@pytest.mark.parametrize("locations", [[], [{"location_id": CENTRO, "name": "Centro"}]])
def test_needs_location_means_at_least_two_locations_to_choose_from(
    locations: list[dict[str, Any]],
) -> None:
    ADAPTER.validate_python(_needs())
    assert (("needs_location", "locations"), "too_short") in _errors(_needs(locations=locations))


def test_the_locations_to_choose_from_are_distinct() -> None:
    twice = [{"location_id": CENTRO, "name": "Centro"}] * 2
    with pytest.raises(ValidationError, match="distinct"):
        ADAPTER.validate_python(_needs(locations=twice))


def test_a_location_needs_an_id_and_a_name() -> None:
    for field in ("location_id", "name"):
        locations = [{"location_id": CENTRO, "name": "Centro"}, {"location_id": POLANCO}]
        if field == "location_id":
            locations = [{"name": "Centro"}, {"location_id": POLANCO, "name": "Polanco"}]
        assert any(t == "missing" for _, t in _errors(_needs(locations=locations)))


def test_an_unknown_match_is_rejected() -> None:
    assert _errors(_needs(match="first_location"))[0][1] == "union_tag_invalid"


def test_the_envelope_and_the_metric_card_accept_needs_location() -> None:
    envelope = _adapter(RpcEnvelope[RPCS["get_dish_margin"].data])  # type: ignore[misc]
    doc = {
        "ok": True,
        "data": _needs(),
        "flags": [],
        "meta": {"as_of": "2026-10-19T08:00:00-06:00"},
    }
    assert envelope.validate_python(doc).ok
    card = {"kind": "metric_card", "rpc": "get_dish_margin", "data": _needs()}
    MetricCardMsg.model_validate(card)


def test_the_needs_location_example_has_no_location_argument() -> None:
    doc = json.loads((EXAMPLES / "get_dish_margin.needs_location.json").read_text())
    assert "location_id" not in doc["args"]
    assert doc["response"]["data"]["match"] == "needs_location"
    assert len(doc["response"]["data"]["locations"]) >= 2


def test_a_resolved_example_answers_for_the_location_it_was_asked() -> None:
    doc = json.loads((EXAMPLES / "get_dish_margin.json").read_text())
    assert doc["args"]["location_id"] == doc["response"]["data"]["location_id"]
