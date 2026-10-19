"""The fixture restaurant ("Taquería El Güero") as the mock reads it, plus text formatting."""

from __future__ import annotations

import datetime as dt
import json
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "el_guero"
TODAY = dt.date(2026, 10, 12)  # the eval's "today" (expected.json); the data ends the day before


@cache
def table(name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads((FIXTURES / f"{name}.json").read_text())
    return rows


@cache
def expected() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((FIXTURES / "expected.json").read_text())
    return doc


LOCATIONS: dict[str, str] = {
    {"Centro": "L1", "Polanco": "L2"}[row["name"]]: row["id"] for row in table("location")
}


def money(cents: int, *, signed: bool = False) -> str:
    sign = "-" if cents < 0 else "+" if signed and cents > 0 else ""
    pesos, centavos = divmod(abs(cents), 100)
    return f"{sign}${pesos:,}.{centavos:02d}"


def pct(value: Decimal, *, signed: bool = False) -> str:
    one = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{one:+}%" if signed else f"{one}%"
