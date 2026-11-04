"""The router: the one template question a message asks, or None when it is not certain.

Precision beats coverage (MR-26 spec). The router works on a closed vocabulary: it removes the
location names, the period and the words of the intent it recognizes, then the filler words, and
any word left over (a dish, a staff name, a date, a figure, a location the user cannot see) means
no match. Not matching is never wrong: the message goes to the LLM broker.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
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


def route(text: str, locations: Mapping[UUID, str]) -> Match | None:
    """The one intent `text` asks for, or None when any word is not understood."""
    words = re.sub(r"[^a-z0-9]+", " ", normalize_name(text)).split()
    if WRITE_VERBS.intersection(words):
        return None

    # a name two locations share cannot tell them apart: it stays unknown, the message falls through
    names = {location_id: normalize_name(name) for location_id, name in locations.items()}
    count = Counter(names.values())
    by_name = {name: location_id for location_id, name in names.items() if count[name] == 1}
    named = {by_name[name] for name in _take(words, by_name)}
    periods = {PERIODS[phrase] for phrase in _take(words, PERIODS)}

    if not _take(words, SALES_TRIGGERS):
        return None
    if len(periods) != 1 or len(named) > 1 or not _understood(words):
        return None
    (period,) = periods
    args: dict[str, Any] = {"period": period}
    if named:
        args["location_id"] = str(next(iter(named)))
    intent: Intent = "sales_yesterday" if period == "yesterday" else "sales_period"
    return Match(intent, "get_sales_summary", args)


def _take(words: list[str], phrases: Iterable[str]) -> list[str]:
    """Removes every whole-word occurrence of `phrases` from `words`, longest phrase first, and
    returns the phrases found (one entry per occurrence)."""
    found = []
    for phrase in sorted(phrases, key=lambda p: -len(p.split())):
        target = phrase.split()
        if not target:  # a location name with no letters ("🌮") would match forever
            continue
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
