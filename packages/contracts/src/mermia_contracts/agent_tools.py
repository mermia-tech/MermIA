"""C4: the 12 agent tools in Anthropic tool format, derived from C3 plus propose_change.

Each read tool is the RPC of the same name (rpc.RPCS); `propose_change` is the only write tool.
Its schema stays flat on purpose (kind, target, values, reason): `values` is checked against
the kind's payload by the ToolExecutor with pending.ChangeProposal, so the schema the model
sees stays small. `target` is what the user said (a name); the confirmation service resolves it
to the id that ChangeProposal.target_id holds.
"""

import hashlib
import json
from typing import Any, Final, TypedDict

from pydantic import JsonValue

from mermia_contracts.batch import Model, Text
from mermia_contracts.pending import PendingKind
from mermia_contracts.rpc import RPCS

TOKEN_LIMIT: Final = 125
"""Tokens one tool may add to the request (08 C4); measured by tools/measure_tool_tokens.py."""


class ProposeChangeArgs(Model):
    kind: PendingKind
    target: Text
    values: dict[str, JsonValue]
    reason: Text | None = None


class ToolDef(TypedDict):
    name: str
    description: str
    input_schema: dict[str, Any]


DESCRIPTIONS: Final = {
    "get_sales_summary": "Net sales, tickets, average ticket, guests, discounts and cancellations.",
    "compare_periods": "Compare one metric between two periods.",
    "compare_locations": "Rank locations by one metric for a period.",
    "get_top_dishes": "Top dishes by units, revenue or margin.",
    "get_sales_breakdown": "Sales split by payment, staff, hour, weekday, channel or category.",
    "get_cancellations": "Cancellations or discounts with top items and staff.",
    "get_dish_margin": "Cost, price and margin of one dish, by id or name.",
    "get_food_cost_pct": "Theoretical food cost percent and its coverage.",
    "get_menu_engineering": "Star, plowhorse, puzzle and dog counts with top items.",
    "get_cost_alerts": "Ingredient price moves, dishes over target and price suggestions.",
    "get_data_status": "Last data loaded per source, missing days and stale costs.",
    "propose_change": "Propose a change for human approval. Never applies it.",
}


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def _tool(name: str, args: type[Model]) -> ToolDef:
    return {
        "name": name,
        "description": DESCRIPTIONS[name],
        "input_schema": _strip_titles(args.model_json_schema()),
    }


def tool_definitions() -> list[ToolDef]:
    """The 12 tools in the order of 09 section 4.1."""
    tools = [_tool(name, spec.args) for name, spec in RPCS.items()]
    return [*tools, _tool("propose_change", ProposeChangeArgs)]


def tools_sha256() -> str:
    """Hash of the canonical JSON of the tool definitions (ties a token measurement to them)."""
    canonical = json.dumps(tool_definitions(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
