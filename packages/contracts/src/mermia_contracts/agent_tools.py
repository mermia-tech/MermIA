"""C4: the 12 agent tools in Anthropic tool format, derived from C3 plus propose_change.

Each read tool is the RPC of the same name (rpc.RPCS); `propose_change` is the only write tool.
Its schema stays flat (kind, target, values, reason), and `values` is typed per kind: one closed
variant for each payload (VALUES_FOR_KIND), and the variant must be the one of `kind`. Prices are
what the user said, with a unit of a closed list ("$220 per kg" is 220 and "kg"); the model never
converts. The confirmation service (MR-37, with the unit conversions of MR-25) converts to pesos
per base unit, resolves `target` (a name) to ChangeProposal.target_id and stores the typed
proposal: that conversion is NOT implemented in this package.
"""

import hashlib
import json
from typing import Any, Final, TypedDict

from pydantic import model_validator

from mermia_contracts.batch import Model, Text
from mermia_contracts.pending import (
    IngredientPriceInput,
    MenuItemPriceSet,
    NoPayload,
    PendingKind,
    RecipeUpsert,
)
from mermia_contracts.rpc import RPCS

TOKEN_LIMIT: Final = 125
"""Tokens one tool may add to the request (08 C4); measured by tools/measure_tool_tokens.py."""


VALUES_FOR_KIND: Final[dict[PendingKind, type[Model]]] = {
    PendingKind.ingredient_price_set: IngredientPriceInput,
    PendingKind.recipe_upsert: RecipeUpsert,
    PendingKind.menu_item_price_set: MenuItemPriceSet,
    PendingKind.import_batch_approve: NoPayload,
    PendingKind.import_batch_rollback: NoPayload,
}
"""The payload each kind accepts from the model. Only the ingredient price differs from what is
stored (a unit instead of a base-unit price); the other four are the stored payloads."""


class ProposeChangeArgs(Model):
    kind: PendingKind
    target: Text
    values: IngredientPriceInput | MenuItemPriceSet | RecipeUpsert | NoPayload = NoPayload()
    reason: Text | None = None

    @model_validator(mode="after")
    def _values_match_kind(self) -> "ProposeChangeArgs":
        if type(self.values) is not VALUES_FOR_KIND[self.kind]:
            raise ValueError(f"the values do not match kind {self.kind.value}")
        return self


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
