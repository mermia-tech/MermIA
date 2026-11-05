"""The number validator (09 D6, 13 H3): every figure in an LLM reply must come from a source.

Sources are the tool results of this question, the bare numbers of the question ("top 5", "30
días") and the agent's earlier replies in memory, which were validated when sent. A money-shaped
number from the owner's question is never a source: the agent would confirm the owner's guess.
Spec: docs/superpowers/specs/2026-11-05-mr-27-broker-validator-design.md

Known limit: a figure is checked for existence in a source, not for the measure it is attached
to ("$212" passes when 212 is the ticket count), and numbers written in words are not seen.
The extraction helpers are shared with the eval's numbers score (apps/eval).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

# A sign counts only when it is not glued to a word or digit ("2026-10-20" has no negatives),
# but a currency code may touch the figure ("MXN70.00") and a sign may precede "$" ("-$37.63");
# a comma is a thousands separator only before exactly three digits; "+" is no sign.
NUMBER = re.compile(
    r"(?:(?<![\w.])|(?<=MXN)|(?<=USD))([-\u2212]?)\$?"
    r"(\d{1,3}(?:,\d{3})+(?!\d)(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)",
    re.IGNORECASE,
)
# Digits that are not figures: ids and dates inside the tool data.
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:T[\d:.]+(?:[+-]\d{2}:\d{2}|Z)?)?")  # with UTC offset
MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
# "12 de octubre (de 2026)", a range "del 5 al 11 de octubre", and abbreviations ("4 de oct",
# "28 de sept"); "12/10/2026" is dd/mm/yyyy.
SPANISH_DATE = re.compile(
    r"\b(\d{1,2})(?:\s+(?:al|y|a)\s+(\d{1,2}))?\s+de\s+("
    + "|".join([*MONTHS, "sept", *(m[:3] for m in MONTHS)])  # full names first
    + r")\.?(?:\s+del?\s+(\d{4}))?\b",
    re.IGNORECASE,
)
SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
LIST_MARKER = re.compile(r"(?m)^[ \t]*\d{1,2}[.)][ \t]+")
TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
# A question number is a source only when bare: no "$", separator or decimals, no "MXN" before
# it and no %, "mil" or "pesos" after it; and never for a figure the reply shows as money.
_MONEY_BEFORE = re.compile(r"(?:mxn|usd)\s*$", re.IGNORECASE)
_MONEY_AFTER = re.compile(r"\s*(?:%|mil\b|pesos\b|mxn\b)", re.IGNORECASE)


@dataclass(frozen=True)
class Turn:
    """One answered message in memory: the owner's question and the text the agent sent."""

    q: str
    a: str
    ts: datetime


def numbers(text: str) -> set[Decimal]:
    return {_value(m) for m in NUMBER.finditer(text)}


def tool_numbers(result: str) -> set[Decimal]:
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
            found.update(numbers(DATETIME.sub(" ", UUID.sub(" ", value))))
        elif isinstance(value, int | float) and not isinstance(value, bool):
            found.add(Decimal(str(value)))

    try:
        walk(json.loads(result))
    except ValueError:  # not JSON (an error text): every digit run counts
        found = numbers(result)
    return found


def _month(name: str) -> int:
    name = name.lower()
    return next(i for i, m in enumerate(MONTHS, 1) if m == name or m[:3] == name[:3])


def strip_dates(reply: str, dates: set[str]) -> str:
    """Remove the given dates from the reply, in ISO or Spanish form; other dates stay."""
    days = {tuple(map(int, d.split("-"))) for d in dates}

    def known(day: str, month: int, year: str | None) -> bool:
        return any(
            (year is None or int(year) == y) and (m, int(day)) == (month, d) for y, m, d in days
        )

    def spanish(match: re.Match[str]) -> str:
        first, second, month, year = match.groups()
        m = _month(month)
        ok = all(known(day, m, year) for day in (first, second) if day)
        return " " if ok else match.group()

    def slash(match: re.Match[str]) -> str:
        day, month, year = match.groups()
        return " " if known(day, int(month), year) else match.group()

    for d in dates:
        reply = reply.replace(d, " ")
    return SLASH_DATE.sub(slash, SPANISH_DATE.sub(spanish, reply))


def _money(text: str, m: re.Match[str]) -> bool:
    return (
        "$" in m.group(0)
        or bool(_MONEY_BEFORE.search(text, 0, m.start()))
        or bool(_MONEY_AFTER.match(text, m.end()))
    )


def _value(m: re.Match[str]) -> Decimal:
    return Decimal(m.group(1).replace("\u2212", "-") + m.group(2).replace(",", ""))


def _bare_numbers(question: str) -> set[Decimal]:
    return {
        _value(m)
        for m in NUMBER.finditer(question)
        if m.group(2).isdigit() and not _money(question, m)
    }


def _memory_numbers(answer: str) -> set[Decimal]:
    """Figures of an earlier reply, without its dates, times and list markers."""
    text = SLASH_DATE.sub(" ", SPANISH_DATE.sub(" ", DATETIME.sub(" ", answer)))
    return numbers(LIST_MARKER.sub("", TIME.sub(" ", text)))


def validate(
    reply: str,
    *,
    tool_results: Sequence[str],
    question: str,
    memory: Sequence[Turn],
    dates: Iterable[str] = (),
) -> set[Decimal]:
    """The figures in `reply` with no source; empty means the reply may be sent. `dates` are
    the dates the agent was told (today), which are not figures. A date an earlier reply wrote
    may be repeated."""
    known_dates = {d for r in [*tool_results, *(t.a for t in memory)] for d in DATE.findall(r)}
    said = {m.group().lower() for t in memory for m in SPANISH_DATE.finditer(t.a)}
    text = strip_dates(reply, set(dates) | known_dates)
    text = SPANISH_DATE.sub(lambda m: " " if m.group().lower() in said else m.group(), text)
    text = LIST_MARKER.sub("", TIME.sub(" ", text))
    money = {_value(m) for m in NUMBER.finditer(text) if _money(text, m)}
    known = set().union(
        *(tool_numbers(r) for r in tool_results), *(_memory_numbers(t.a) for t in memory)
    )
    return numbers(text) - known - (_bare_numbers(question) - money)
