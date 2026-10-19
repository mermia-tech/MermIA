"""C4: 12 tools, one per RPC plus propose_change, each with a valid JSON Schema."""

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.agent_tools import (
    DESCRIPTIONS,
    ProposeChangeArgs,
    tool_definitions,
    tools_sha256,
)
from mermia_contracts.pending import ChangeProposal, IngredientPriceInput
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


def test_tool_input_from_json_loads_becomes_a_typed_proposal() -> None:
    """What the SDK hands over (floats and ints from json.loads) must validate, exactly.

    The price arrives per the unit the user said ($220 per kg). The proposal that is stored is
    per base unit (0.22 per g): the confirmation service converts between the two (MR-37 with
    MR-25), which this package does not do, so the stored price below is written by hand.
    """
    tool_input = json.loads(
        '{"kind": "ingredient_price.set", "target": "carne al pastor", "reason": "subió",'
        ' "values": {"unit_price": 220.00, "unit": "kg", "effective_from": "2026-10-19"}}'
    )
    args = ProposeChangeArgs.model_validate(tool_input)
    assert isinstance(args.values, IngredientPriceInput)
    resolved: dict[str, Any] = {
        "kind": args.kind,
        "target_id": "0f7a1c52-3b6e-7c1a-9d33-000000000001",  # resolved from args.target
        "values": {"unit_price": Decimal("0.22"), "effective_from": args.values.effective_from},
        "reason": args.reason,
    }
    proposal = TypeAdapter(ChangeProposal).validate_python(resolved)
    assert proposal.values.unit_price == Decimal("0.22")  # type: ignore[union-attr]
    assert str(proposal.values.effective_from) == "2026-10-19"  # type: ignore[union-attr]
