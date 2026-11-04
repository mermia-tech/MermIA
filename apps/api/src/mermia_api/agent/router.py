"""The router: the one template question a message asks, or None when it is not certain.

Precision beats coverage (MR-26 spec). The router works on a closed vocabulary: it removes the
location names, the period and the words of the intent it recognizes, then the filler words, and
any word left over (a dish, a staff name, a date, a figure, a location the user cannot see) means
no match. Not matching is never wrong: the message goes to the LLM broker.
"""

from __future__ import annotations

import re
from collections import Counter
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

# Imperative and infinitive forms only: "subió" describes, "súbele" orders a change. Defense in
# depth: none of these is in the vocabulary today, so the closed vocabulary already rejects them;
# this keeps a write from ever being read as a question if a word list grows to include one.
WRITE_VERBS = _words(
    "cambia cambiala cambialo cambiale cambiar sube subele subelo subir baja bajale bajalo bajar "
    "pon ponle ponlo poner actualiza actualizala actualizalo actualizar redondea redondeame "
    "redondealo redondear manda mandale mandar registra registralo registrar"
)

FILLER = _words(
    "cuanto cuanta cuantos cuantas cual cuales que me mi mis tu tus de del la el las los lo en "
    "con y por fue es son se a al dime dame oye hola porfa favor ya total totales todas todos "
    "sucursales locales"
)

SALES_TRIGGERS = ("vendi", "vendio", "vendimos", "venta", "ventas", "entro")
COMPARE_TRIGGERS = ("contra", "vs", "versus", "comparado con", "comparada con")
PREVIOUS_WEEK = ("semana anterior", "anterior", "antepasada")  # "la pasada vs la anterior"
DISH_TRIGGERS = ("platillo", "platillos")
FOOD_COST_TRIGGERS = ("food cost", "foodcost", "costo de alimentos")
DATA_STATUS_TRIGGERS = ("al dia", "actualizados", "actualizado", "ultimo reporte")
LOCATIONS_TRIGGERS = (
    "cada local",
    "cada sucursal",
    "por local",
    "por sucursal",
    "cual de mis locales",
    "cual de mis sucursales",
    "cual de mis dos locales",
    "cual de mis dos sucursales",
    "en cual sucursal",
    "en cual local",
)
PAYMENT_TRIGGERS = (
    "tarjeta",
    "efectivo",
    "transferencia",
    "forma de pago",
    "formas de pago",
    "metodo de pago",
    "metodos de pago",
)
DISH_MEASURES = {
    "vendido": "units",
    "vendidos": "units",
    "vendio": "units",
    "dinero": "revenue",
    "ganancia en pesos": "margin",
    "deja": "margin",
    "porcentaje de ganancia": "margin_pct",
}
DISH_ORDERS = {"mas": "desc", "mayor": "desc", "top": "desc", "menos": "asc", "menor": "asc"}
# Number words are not filler ("ventas de ayer a las tres" asks for an hour): only N before
# "platillo(s)", and "dos" inside the compare-locations triggers.
NUMBERS = {
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}


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

    # a specific intent wins over the sales total; two specific intents is not certain
    specific = [parse for triggers, parse in _SPECIFIC if _take(list(words), triggers)]
    if _compare_locations in specific:  # "food cost por sucursal" compares locations
        specific = [parse for parse in specific if parse is not _food_cost]
    if len(specific) > 1:
        return None
    parse = specific[0] if specific else _sales_total
    match = parse(words, periods, named)
    if match is None or not _understood(words):
        return None
    if match.intent == "compare_locations" and len(locations) < 2:
        return None
    return match


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


def _top_dishes(words: list[str], periods: set[PeriodName], named: set[UUID]) -> Match | None:
    """Top or bottom N dishes by one measure. N is a digit or a number word right before
    "platillo(s)"; without it a plural asks for 5 and a singular for 1."""
    at = [i for i, word in enumerate(words) if word in DISH_TRIGGERS]
    if len(at) != 1:
        return None
    (i,) = at
    limit = 1 if words[i] == "platillo" else 5
    if i > 0 and (words[i - 1].isdigit() or words[i - 1] in NUMBERS):
        before = words.pop(i - 1)
        limit = int(before) if before.isdigit() else NUMBERS[before]
    _take(words, DISH_TRIGGERS)
    _take(words, ("venden",))  # "que más dinero me venden": the measure is "dinero"
    metrics = {DISH_MEASURES[m] for m in _take(words, DISH_MEASURES)}
    orders = {DISH_ORDERS[o] for o in _take(words, DISH_ORDERS)}
    scope = _scope(named)
    if len(metrics) != 1 or len(orders) != 1 or len(periods) != 1 or scope is None:
        return None
    if not 1 <= limit <= 10:
        return None
    (period,) = periods
    args = {"period": period, "metric": metrics.pop(), "order": orders.pop(), "limit": limit}
    return Match("top_dishes", "get_top_dishes", {**args, **scope})


def _food_cost(words: list[str], periods: set[PeriodName], named: set[UUID]) -> Match | None:
    _take(words, FOOD_COST_TRIGGERS)
    scope = _scope(named)
    if len(periods) != 1 or scope is None:
        return None
    (period,) = periods
    return Match("food_cost", "get_food_cost_pct", {"period": period, **scope})


def _data_status(words: list[str], periods: set[PeriodName], named: set[UUID]) -> Match | None:
    _take(words, DATA_STATUS_TRIGGERS)
    _take(words, ("estan", "esta"))
    scope = _scope(named)
    if not _take(words, ("datos",)) or periods or scope is None:
        return None
    return Match("data_status", "get_data_status", scope)


def _compare_locations(
    words: list[str], periods: set[PeriodName], named: set[UUID]
) -> Match | None:
    """Ranks every location the user can see. Names in the text are accepted ("Centro y
    Polanco") but never sent: the RPC compares all of them, as the eval case expects."""
    _take(words, LOCATIONS_TRIGGERS)
    _take(words, ("lleva", "mas"))  # "cuál de mis locales lleva más ventas"
    metrics = set()
    if _take(words, SALES_TRIGGERS):
        metrics.add("net_sales")
    if _take(words, FOOD_COST_TRIGGERS):
        metrics.add("food_cost_pct")
    if len(periods) != 1 or len(metrics) != 1:
        return None
    (period,) = periods
    return Match(
        "compare_locations", "compare_locations", {"metric": metrics.pop(), "period": period}
    )


def _payment_methods(words: list[str], periods: set[PeriodName], named: set[UUID]) -> Match | None:
    _take(words, PAYMENT_TRIGGERS)
    _take(words, SALES_TRIGGERS)  # "cuánto entró por tarjeta"
    scope = _scope(named)
    if len(periods) != 1 or scope is None:
        return None
    (period,) = periods
    args = {"period": period, "by": "payment_method", **scope}
    return Match("payment_methods", "get_sales_breakdown", args)


def _scope(named: set[UUID]) -> dict[str, Any] | None:
    """The location argument: none named means all the user's, two is not one location."""
    if len(named) > 1:
        return None
    return {"location_id": str(next(iter(named)))} if named else {}


_SPECIFIC: tuple[tuple[tuple[str, ...], Parser], ...] = (
    (COMPARE_TRIGGERS, _compare_periods),
    (DISH_TRIGGERS, _top_dishes),
    (FOOD_COST_TRIGGERS, _food_cost),
    (DATA_STATUS_TRIGGERS, _data_status),
    (LOCATIONS_TRIGGERS, _compare_locations),
    (PAYMENT_TRIGGERS, _payment_methods),
)


# The fallback menu (spec: Fallback): each option's label and the call a tap runs.
MENU: dict[Intent, tuple[str, Match]] = {
    "sales_yesterday": (
        "Ventas de ayer",
        Match("sales_yesterday", "get_sales_summary", {"period": "yesterday"}),
    ),
    "sales_period": (
        "Ventas semana pasada",
        Match("sales_period", "get_sales_summary", {"period": "last_week"}),
    ),
    "compare_periods": (
        "Semana vs anterior",
        Match(
            "compare_periods",
            "compare_periods",
            {"metric": "net_sales", "period_a": "last_week", "period_b": "prev_week"},
        ),
    ),
    "top_dishes": (
        "Top 5 platillos del mes",
        Match(
            "top_dishes",
            "get_top_dishes",
            {"period": "this_month", "metric": "units", "order": "desc", "limit": 5},
        ),
    ),
    "food_cost": (
        "Food cost de ayer",
        Match("food_cost", "get_food_cost_pct", {"period": "yesterday"}),
    ),
    "compare_locations": (
        "Ventas por sucursal",
        Match(
            "compare_locations",
            "compare_locations",
            {"metric": "net_sales", "period": "last_week"},
        ),
    ),
    "payment_methods": (
        "Formas de pago de ayer",
        Match(
            "payment_methods",
            "get_sales_breakdown",
            {"period": "yesterday", "by": "payment_method"},
        ),
    ),
    "data_status": ("¿Datos al día?", Match("data_status", "get_data_status", {})),
}


def menu(locations: Mapping[UUID, str]) -> dict[str, tuple[str, Match]]:
    """The menu options this user can tap, by action id (`tpl:<intent>`)."""
    return {
        f"tpl:{intent}": option
        for intent, option in MENU.items()
        if intent != "compare_locations" or len(locations) > 1
    }


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
