"""The router: the one template question a message asks, or None when it is not certain.

Precision beats coverage (MR-26 spec). The router works on a closed vocabulary: it removes the
location names, the period and the words of the intent it recognizes, then the filler words, and
any word left over (a dish, a staff name, a date, a figure, a location the user cannot see) means
no match. Not matching is never wrong: the message goes to the LLM broker.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from mermia_contracts.keys import normalize_name
from mermia_contracts.rpc import PeriodName

Intent = Literal[
    "sales_yesterday",
    "sales_period",
    "compare_periods",
    "top_dishes",
    "food_cost",
    "compare_locations",
    "payment_methods",
    "data_status",
]


@dataclass(frozen=True)
class Match:
    intent: Intent
    rpc: str  # a key of mermia_contracts.rpc.RPCS
    args: dict[str, Any]  # JSON-ready, as the RPC receives them


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


PERIODS: dict[str, PeriodName] = {
    "hoy": "today",
    "ayer": "yesterday",
    "esta semana": "this_week",
    "semana pasada": "last_week",
    "semana antepasada": "prev_week",
    "este mes": "this_month",
    "lo que va del mes": "this_month",
    "mes pasado": "last_month",
    "ultimos 7 dias": "last_7d",
    "ultimos 30 dias": "last_30d",
}

# Imperative and infinitive forms only: "subió" describes, "súbele" orders a change.
WRITE_VERBS = _words(
    "cambia cambiala cambialo cambiale cambiar sube subele subelo subir baja bajale bajalo bajar "
    "pon ponle ponlo poner actualiza actualizala actualizalo actualizar redondea redondeame "
    "redondealo redondear manda mandale mandar registra registralo registrar"
)

FILLER = _words(
    "cuanto cuanta cuantos cuantas que me mi mis tu tus de del la el las los lo en y por fue es "
    "son se a al dime dame oye hola porfa favor ya total totales todas todos sucursales locales "
    "uno una dos tres cuatro cinco seis siete ocho nueve diez"
)

SALES_TRIGGERS = ("vendi", "vendio", "vendimos", "venta", "ventas", "entro")
COMPARE_TRIGGERS = ("contra", "vs", "versus", "comparado con", "comparada con")
PREVIOUS_WEEK = ("semana anterior", "anterior", "antepasada")  # "la pasada vs la anterior"


def route(text: str, locations: Mapping[UUID, str]) -> Match | None:
    """The one intent `text` asks for, or None when any word is not understood."""
    words = re.sub(r"[^a-z0-9]+", " ", normalize_name(text)).split()
    if WRITE_VERBS.intersection(words):
        return None

    by_name = {normalize_name(name): location_id for location_id, name in locations.items()}
    named = {by_name[name] for name in _take(words, by_name)}
    periods = {PERIODS[phrase] for phrase in _take(words, PERIODS)}

    # a specific intent wins over the sales total; two specific intents is not certain
    specific = [parse for triggers, parse in _SPECIFIC if _take(list(words), triggers)]
    if len(specific) > 1:
        return None
    parse = specific[0] if specific else _sales_total
    match = parse(words, periods, named)
    return match if match is not None and _understood(words) else None


Parser = Callable[[list[str], set[PeriodName], set[UUID]], Match | None]


def _sales_total(words: list[str], periods: set[PeriodName], named: set[UUID]) -> Match | None:
    scope = _scope(named)
    if not _take(words, SALES_TRIGGERS) or len(periods) != 1 or scope is None:
        return None
    (period,) = periods
    intent: Intent = "sales_yesterday" if period == "yesterday" else "sales_period"
    return Match(intent, "get_sales_summary", {"period": period, **scope})


def _compare_periods(words: list[str], periods: set[PeriodName], named: set[UUID]) -> Match | None:
    """Last week against the week before only: the other pairs compare part of a period with a
    whole one (resolve_period ends this_week and this_month today)."""
    _take(words, COMPARE_TRIGGERS)
    metrics = set()
    if _take(words, SALES_TRIGGERS):
        metrics.add("net_sales")
    if _take(words, ("ticket promedio",)):
        metrics.add("avg_ticket")
    if _take(words, PREVIOUS_WEEK):
        periods = periods | {"prev_week"}
    scope = _scope(named)
    if periods != {"last_week", "prev_week"} or len(metrics) != 1 or scope is None:
        return None
    args = {"metric": metrics.pop(), "period_a": "last_week", "period_b": "prev_week", **scope}
    return Match("compare_periods", "compare_periods", args)


def _scope(named: set[UUID]) -> dict[str, Any] | None:
    """The location argument: none named means all the user's, two is not one location."""
    if len(named) > 1:
        return None
    return {"location_id": str(next(iter(named)))} if named else {}


_SPECIFIC: tuple[tuple[tuple[str, ...], Parser], ...] = ((COMPARE_TRIGGERS, _compare_periods),)


def _take(words: list[str], phrases: Iterable[str]) -> list[str]:
    """Removes every whole-word occurrence of `phrases` from `words`, longest phrase first, and
    returns the phrases found (one entry per occurrence)."""
    found = []
    for phrase in sorted(phrases, key=lambda p: -len(p.split())):
        target = phrase.split()
        i = 0
        while i + len(target) <= len(words):
            if words[i : i + len(target)] == target:
                del words[i : i + len(target)]
                found.append(phrase)
            else:
                i += 1
    return found


def _understood(words: list[str]) -> bool:
    return all(word in FILLER for word in words)
