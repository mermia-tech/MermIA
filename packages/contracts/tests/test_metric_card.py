"""MetricCardMsg.data is the data of the RPC named in `rpc`, complete and valid.

No partial data: a card that shows one metric needs a message type of its own (not defined).
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.agent import AgentResponse, MetricCardMsg
from mermia_contracts.rpc import RPCS

HERE = Path(__file__).parent / "examples"
RPC_EXAMPLES = sorted(
    p for p in (HERE / "rpc").glob("*.json") if not p.name.endswith(".error.json")
)


def _data(path: Path) -> Any:
    return json.loads(path.read_text())["response"]["data"]


def _rpc(path: Path) -> str:
    return path.name.split(".")[0]


def _card(rpc: str, data: Any) -> dict[str, Any]:
    return {"kind": "metric_card", "rpc": rpc, "data": data}


@pytest.mark.parametrize("path", RPC_EXAMPLES, ids=lambda p: p.name)
def test_every_rpc_example_is_a_valid_card_for_its_own_rpc(path: Path) -> None:
    card = MetricCardMsg.model_validate(_card(_rpc(path), _data(path)))
    assert card.data == _data(path)  # kept as returned, for the renderers


@pytest.mark.parametrize("path", RPC_EXAMPLES, ids=lambda p: p.name)
def test_every_rpc_example_is_a_valid_card_from_json_text(path: Path) -> None:
    doc = {"messages": [_card(_rpc(path), _data(path))], "route": "template"}
    AgentResponse.model_validate_json(json.dumps(doc))


FOREIGN_PAIRS = [(p, other) for p in RPC_EXAMPLES for other in sorted(RPCS) if other != _rpc(p)]


@pytest.mark.parametrize(
    "path,other", FOREIGN_PAIRS, ids=lambda v: v.name if hasattr(v, "name") else v
)
def test_data_of_another_rpc_is_rejected(path: Path, other: str) -> None:
    with pytest.raises(ValidationError, match=f"not a valid {other} result"):
        MetricCardMsg.model_validate(_card(other, _data(path)))


@pytest.mark.parametrize(
    "bad",
    [None, [], [1, 2, 3], {}, "text", 7, True, {"net_sales": 1.5}],
    ids=["null", "empty-list", "list", "empty-object", "string", "number", "bool", "bad-money"],
)
def test_malformed_data_is_rejected(bad: Any) -> None:
    good = _data(HERE / "rpc" / "get_sales_summary.json")
    MetricCardMsg.model_validate(_card("get_sales_summary", good))
    with pytest.raises(ValidationError, match="not a valid get_sales_summary result"):
        MetricCardMsg.model_validate(_card("get_sales_summary", bad))


def test_a_partial_summary_is_rejected_and_names_what_is_missing() -> None:
    partial = {"net_sales": {"raw": 18432050, "text": "$184,320.50"}}
    with pytest.raises(ValidationError) as info:
        MetricCardMsg.model_validate(_card("get_sales_summary", partial))
    message = str(info.value)
    assert "tickets" in message and "Field required" in message


def test_one_wrong_field_is_rejected_and_the_message_names_where() -> None:
    data = copy.deepcopy(_data(HERE / "rpc" / "get_sales_summary.json"))
    data["net_sales"]["raw"] = 184320.5
    with pytest.raises(ValidationError, match=r"net_sales\.raw"):
        MetricCardMsg.model_validate(_card("get_sales_summary", data))


def test_an_unknown_rpc_is_still_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown rpc"):
        MetricCardMsg.model_validate(_card("drop_table", {}))


def test_the_example_card_carries_a_complete_summary() -> None:
    doc = json.loads((HERE / "agent" / "response_metric_card.json").read_text())
    card = doc["messages"][0]
    assert card["rpc"] == "get_sales_summary"
    assert card["data"] == _data(HERE / "rpc" / "get_sales_summary.json")
    AgentResponse.model_validate(doc)
