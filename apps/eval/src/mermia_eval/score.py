"""Scores of one run, each 0.0 or 1.0 (spec section 5)."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mermia_eval.cases import Case

# A sign counts only when it is not glued to a word or digit ("2026-10-20" has no negatives),
# but a currency code may touch the figure ("MXN70.00") and a sign may precede "$" ("-$37.63");
# a comma is a thousands separator only before exactly three digits; "+" is no sign.
_NUMBER = re.compile(
    r"(?:(?<![\w.])|(?<=MXN)|(?<=USD))([-\u2212]?)\$?"
    r"(\d{1,3}(?:,\d{3})+(?!\d)(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
)
# Digits that are not figures: ids and dates inside the tool data.
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LIST_MARKER = re.compile(r"(?m)^[ \t]*\d{1,2}[.)][ \t]+")


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


def _numbers(text: str) -> set[Decimal]:
    return {
        Decimal(sign.replace("\u2212", "-") + digits.replace(",", ""))
        for sign, digits in _NUMBER.findall(text)
    }


def _tool_numbers(result: str) -> set[Decimal]:
    """Figures a tool result lets the agent quote: its display text and plain values, not the
    "raw" centavos, UUID fragments or dates."""
    found: set[Decimal] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key != "raw":
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            found.update(_numbers(_DATE.sub(" ", _UUID.sub(" ", value))))
        elif isinstance(value, int | float) and not isinstance(value, bool):
            found.add(Decimal(str(value)))

    try:
        walk(json.loads(result))
    except ValueError:  # not JSON (an error text): every digit run counts
        found = _numbers(result)
    return found


def _lower(value: Any) -> Any:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, dict):
        return {k: _lower(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_lower(v) for v in value]
    return value


def _clean(args: dict[str, Any]) -> dict[str, Any]:
    # null means omitted; text is compared without case
    return {k: _lower(v) for k, v in args.items() if v is not None}


def score_tool(case: Case, calls: Sequence[ToolCall]) -> float:
    if case.expected_tool is None:
        return float(not calls)
    return float(bool(calls) and all(c.name == case.expected_tool for c in calls))


def score_args(case: Case, calls: Sequence[ToolCall]) -> float:
    if case.expected_tool is None:
        return float(not calls)
    accepted = [_clean(a) for a in [case.expected_args, *case.accepted_args]]
    return float(any(c.name == case.expected_tool and _clean(c.args) in accepted for c in calls))


def score_numbers(case: Case, reply: str, tool_results: Sequence[str]) -> float:
    """1.0 if every number in the reply comes from a tool result or the question, and every
    must_contain figure is in the reply (numbers compared as values, not as text), and no
    must_not_contain phrase is."""
    if any(p.lower() in reply.lower() for p in case.must_not_contain):
        return 0.0
    dates = {d for r in tool_results for d in _DATE.findall(r)}  # a date may be quoted whole
    for d in dates:
        reply = reply.replace(d, " ")
    shown = _numbers(_LIST_MARKER.sub("", reply))  # "7. " of a list is not a figure
    known = _numbers(case.question).union(*(_tool_numbers(r) for r in tool_results))
    required = set().union(*(_numbers(f) for f in case.must_contain))
    return float(shown <= known and required <= shown)
