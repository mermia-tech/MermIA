"""Scores of one run, each 0.0 or 1.0 (spec section 5)."""

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mermia_api.agent.validator import DATE, LIST_MARKER, numbers, strip_dates, tool_numbers
from mermia_contracts.agent_tools import tool_definitions
from mermia_eval.cases import Case
from mermia_eval.config import SYSTEM_PROMPT
from mermia_eval.figures import EXPECTED

_PROMPT_DATES = set(DATE.findall(SYSTEM_PROMPT))  # today and the data cutoff


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


_PLAIN_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def _fold(text: str) -> str:
    """Lower case without accents, so "Cambié" and "cambie" match."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _norm(value: Any) -> Any:
    """Text without case, numbers (and numeric strings, which C4 allows) as Decimals."""
    if isinstance(value, str):
        return Decimal(value) if _PLAIN_NUMBER.fullmatch(value) else value.lower()
    if isinstance(value, int | float) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def _drop_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_nulls(v) for v in value]
    return value


# Naming every location is the same request as naming none (C3: no location = all of them).
_ALL_LOCATIONS = sorted(
    loc["id"] for loc in json.loads((EXPECTED.parent / "location.json").read_text())
)

_DEFAULTS = {
    t["name"]: {
        k: p["default"]
        for k, p in t["input_schema"].get("properties", {}).items()
        if "default" in p
    }
    for t in tool_definitions()
}


def _clean(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    # null means omitted, a schema default means omitted, the free-text reason is not scored;
    # text is compared without case, numbers by value
    defaults = _DEFAULTS.get(tool, {})
    if sorted(args.get("location_ids") or []) == _ALL_LOCATIONS:
        args = {k: v for k, v in args.items() if k != "location_ids"}
    lowered = _norm(_drop_nulls(args))
    return {
        k: v
        for k, v in lowered.items()
        if k != "reason" and not (k in defaults and v == _norm(defaults[k]))
    }


def score_tool(case: Case, calls: Sequence[ToolCall]) -> float:
    if case.expected_tool is None:
        return float(all(c.name in case.accepted_tools for c in calls))
    return float(bool(calls) and all(c.name == case.expected_tool for c in calls))


def score_args(case: Case, calls: Sequence[ToolCall]) -> float:
    """Only the first call to the expected tool: the fixed mock answers every call the same, so
    later calls react to data that does not match the request (MR-20). score_tool still checks
    that every call uses the right tool."""
    if case.expected_tool is None:
        return score_tool(case, calls)
    first = next((c for c in calls if c.name == case.expected_tool), None)
    accepted = [_clean(case.expected_tool, a) for a in [case.expected_args, *case.accepted_args]]
    return float(first is not None and _clean(first.name, first.args) in accepted)


def score_numbers(case: Case, reply: str, tool_results: Sequence[str]) -> float:
    """1.0 if every number in the reply comes from a tool result or the question (dates
    from the tools or the prompt are not numbers), and every
    must_contain figure is in the reply (numbers compared as values, not as text), and no
    must_not_contain phrase is."""
    if any(_fold(p) in _fold(reply) for p in case.must_not_contain):
        return 0.0
    reply = strip_dates(reply, _PROMPT_DATES | {d for r in tool_results for d in DATE.findall(r)})
    shown = numbers(LIST_MARKER.sub("", reply))  # "7. " of a list is not a figure
    known = numbers(case.question).union(*(tool_numbers(r) for r in tool_results))
    required = set().union(*(numbers(f) for f in case.must_contain))
    return float(shown <= known and required <= shown)
