"""C4: 12 tools, one per RPC plus propose_change, each with a valid JSON Schema."""

import pytest
from pydantic import ValidationError

from mermia_contracts.agent_tools import (
    DESCRIPTIONS,
    ProposeChangeArgs,
    tool_definitions,
    tools_sha256,
)
from mermia_contracts.rpc import RPCS

TOOLS = tool_definitions()


def test_twelve_tools_in_order() -> None:
    assert [t["name"] for t in TOOLS] == [*RPCS, "propose_change"]
    assert set(DESCRIPTIONS) == {t["name"] for t in TOOLS}


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_each_tool_is_well_formed(tool: dict) -> None:  # type: ignore[type-arg]
    assert "\n" not in tool["description"]
    assert len(tool["description"]) <= 100
    assert tool["input_schema"]["type"] == "object"


def test_no_title_keys_remain() -> None:
    assert "'title'" not in repr([t["input_schema"] for t in TOOLS])


def test_propose_change_offers_exactly_the_five_kinds() -> None:
    kinds = next(t for t in TOOLS if t["name"] == "propose_change")["input_schema"]
    assert len(kinds["$defs"]["PendingKind"]["enum"]) == 5


@pytest.mark.parametrize(
    "args",
    [
        {"kind": "settings.update", "target": "x", "values": {}},
        {"kind": "recipe.upsert", "target": " ", "values": {}},
        {"kind": "recipe.upsert", "target": "x"},
        {"kind": "recipe.upsert", "target": "x", "values": [], "reason": "r"},
    ],
)
def test_propose_change_rejects_bad_arguments(args: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationError):
        ProposeChangeArgs.model_validate(args)


def test_hash_is_stable() -> None:
    assert tools_sha256() == tools_sha256()
    assert len(tools_sha256()) == 64
