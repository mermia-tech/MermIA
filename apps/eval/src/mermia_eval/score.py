"""Scores of one run, each 0.0 or 1.0 (spec section 5)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from mermia_eval.cases import Case

# A sign counts only when it is not glued to a word or digit ("2026-10-20" has no negatives);
# a comma is a thousands separator only before exactly three digits; "+" is no sign.
_NUMBER = re.compile(
    r"(?<![\w.])([-\u2212]?)(\d{1,3}(?:,\d{3})+(?!\d)(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
)
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
    return float(bool(calls) and all(c.name == case.expected_tool for c in calls))


def score_args(case: Case, calls: Sequence[ToolCall]) -> float:
    accepted = [_clean(a) for a in [case.expected_args, *case.accepted_args]]
    return float(any(c.name == case.expected_tool and _clean(c.args) in accepted for c in calls))


def score_numbers(case: Case, reply: str, tool_results: Sequence[str]) -> float:
    """1.0 if every number in the reply comes from a tool result or the question, and every
    must_contain figure is in the reply (numbers compared as values, not as text)."""
    shown = _numbers(_LIST_MARKER.sub("", reply))  # "7. " of a list is not a figure
    known = _numbers(case.question).union(*(_numbers(r) for r in tool_results))
    required = set().union(*(_numbers(f) for f in case.must_contain))
    return float(shown <= known and required <= shown)
