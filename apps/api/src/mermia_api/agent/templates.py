"""Zero-token replies: es-MX text built from one RPC result.

Every figure is copied from the RPC data (its `text` fields, names, counts) or is a flag message
our own SQL wrote; nothing is computed or reformatted (CLAUDE.md: the agent never computes money).
Keyed by RPC name, not by router intent, so the MR-27 broker can render its own tool calls.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from mermia_contracts.agent import TextMsg
from mermia_contracts.rpc import (
    RPCS,
    CompareLocationsData,
    ComparePeriodsData,
    DataStatusData,
    FoodCostData,
    RpcEnvelope,
    SalesBreakdownData,
    SalesSummaryData,
    TopDishesData,
)

PERIOD_ES = {
    "today": "hoy",
    "yesterday": "ayer",
    "this_week": "esta semana",
    "last_week": "la semana pasada",
    "prev_week": "la semana antepasada",
    "this_month": "este mes",
    "last_month": "el mes pasado",
    "last_7d": "los últimos 7 días",
    "last_30d": "los últimos 30 días",
}

# shortcut: one time zone for every pilot location; use location.timezone once a tenant spans zones
MEXICO_CITY = ZoneInfo("America/Mexico_City")
MONTHS = (
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
)

_DATA = {name: TypeAdapter(spec.data) for name, spec in RPCS.items()}


def render(
    rpc: str, args: dict[str, Any], envelope: RpcEnvelope[Any], locations: Mapping[UUID, str]
) -> TextMsg:
    """The reply for a successful RPC call. Raises ValidationError when `data` does not fit the
    RPC's C3 model: a changed payload must not be rendered from a guess."""
    data = _DATA[rpc].validate_python(envelope.data)
    lines = _RENDERERS[rpc](data, args, locations)
    lines += [flag.message for flag in envelope.flags if flag.message]
    return TextMsg(kind="text", text="\n".join(lines))


def no_data(rpc: str, args: dict[str, Any]) -> TextMsg:
    if rpc == "compare_periods":
        return TextMsg(kind="text", text="No tengo datos completos para comparar esas semanas.")
    if "period" not in args:
        return TextMsg(kind="text", text="Todavía no tengo datos.")
    of_period = _of(args["period"])
    if rpc == "get_top_dishes" and args.get("metric") in ("margin", "margin_pct"):
        # the SQL says no_data when sales exist but no dish has a cost yet
        text = f"Todavía no tengo costos de tus platillos para calcular la ganancia {of_period}."
        return TextMsg(kind="text", text=text)
    return TextMsg(kind="text", text=f"No tengo datos {of_period} todavía.")


def _sales_summary(
    data: SalesSummaryData, args: dict[str, Any], locations: Mapping[UUID, str]
) -> list[str]:
    lines = [
        f"{_cap(PERIOD_ES[args['period']])} {_where(args, locations)} vendiste "
        f"{data.net_sales.text}."
    ]
    parts = []
    if data.tickets is not None:
        parts.append(f"{data.tickets} tickets")
    if data.avg_ticket is not None:
        parts.append(f"ticket promedio {data.avg_ticket.text}")
    if parts:
        lines.append(_cap(", ".join(parts)) + ".")
    if data.change_vs_previous is not None:
        lines.append(f"Contra el periodo anterior: {data.change_vs_previous.text}.")
    return lines


def _compare_periods(
    data: ComparePeriodsData, args: dict[str, Any], locations: Mapping[UUID, str]
) -> list[str]:
    a, b = _cap(PERIOD_ES[args["period_a"]]), PERIOD_ES[args["period_b"]]
    what = {"net_sales": "vendiste", "avg_ticket": "tu ticket promedio fue"}[data.metric]
    change = f" ({data.pct_change.text})" if data.pct_change is not None else ""
    return [
        f"{a} {_where(args, locations)} {what} {data.a.text} contra {data.b.text} {b}.",
        f"Diferencia: {data.abs_change.text}{change}.",
    ]


# (singular, plural) by metric and order
_DISH_PHRASES = {
    ("units", "desc"): ("más vendido", "más vendidos"),
    ("units", "asc"): ("menos vendido", "menos vendidos"),
    ("revenue", "desc"): ("que más vende en dinero", "que más venden en dinero"),
    ("revenue", "asc"): ("que menos vende en dinero", "que menos venden en dinero"),
    ("margin", "desc"): ("que más ganancia deja", "que más ganancia dejan"),
    ("margin", "asc"): ("que menos ganancia deja", "que menos ganancia dejan"),
    ("margin_pct", "desc"): ("con mayor porcentaje de ganancia",) * 2,
    ("margin_pct", "asc"): ("con menor porcentaje de ganancia",) * 2,
}


def _top_dishes(
    data: TopDishesData, args: dict[str, Any], locations: Mapping[UUID, str]
) -> list[str]:
    when = f"{PERIOD_ES[args['period']]} {_where(args, locations)}"
    if not data.rows:
        return [f"No hay ventas registradas {when}."]
    singular, plural = _DISH_PHRASES[data.metric, args.get("order", "desc")]
    n = len(data.rows)
    head = f"Tu platillo {singular}" if n == 1 else f"Tus {n} platillos {plural}"
    return [f"{head} {when}:"] + [f"{r.rank}. {r.name}: {r.value.text}" for r in data.rows]


def _food_cost(
    data: FoodCostData, args: dict[str, Any], locations: Mapping[UUID, str]
) -> list[str]:
    target = f" (meta: {data.target.text})" if data.target is not None else ""
    return [
        f"Tu food cost {_of(args['period'])} {_where(args, locations)} fue "
        f"{data.theoretical.text}{target}.",
        f"Cobertura de costos: {data.coverage.text} de las ventas.",
    ]


def _data_status(
    data: DataStatusData, args: dict[str, Any], locations: Mapping[UUID, str]
) -> list[str]:
    loaded = [s.last_batch_at for s in data.sources if s.last_batch_at is not None]
    if loaded:
        day = max(loaded).astimezone(MEXICO_CITY).date()
        lines = [f"Último reporte cargado el {_day(day)} de {day.year}."]
    else:
        lines = ["Todavía no hay reportes cargados."]
    if data.missing_business_days:
        lines.append(f"Faltan datos de: {', '.join(map(_day, data.missing_business_days))}.")
    else:
        lines.append("No falta ningún día.")
    if data.stale_costs:
        lines.append(f"{data.stale_costs} ingredientes con precio desactualizado.")
    lines.append(f"Cobertura de costos: {data.coverage.text}.")
    return lines


def _day(day: dt.date) -> str:
    return f"{day.day} de {MONTHS[day.month - 1]}"


_METRIC_ES = {"net_sales": "Ventas", "food_cost_pct": "Food cost"}
PAYMENT_ES = {"card": "Tarjeta", "cash": "Efectivo", "transfer": "Transferencia"}


def _compare_locations(
    data: CompareLocationsData, args: dict[str, Any], locations: Mapping[UUID, str]
) -> list[str]:
    period = PERIOD_ES[args["period"]]
    if not data.rows:
        return [f"No hay ventas registradas {period}."]
    best = min(data.rows, key=lambda r: r.rank).name
    lines = [f"{_METRIC_ES[data.metric]} {_of(args['period'])} por sucursal:"]
    for r in sorted(data.rows, key=lambda r: r.rank):
        behind = f" ({r.diff_vs_best.text} vs. {best})" if r.name != best else ""
        lines.append(f"{r.rank}. {r.name}: {r.value.text}{behind}")
    return lines


def _payment_methods(
    data: SalesBreakdownData, args: dict[str, Any], locations: Mapping[UUID, str]
) -> list[str]:
    when = f"{PERIOD_ES[args['period']]} {_where(args, locations)}"
    if not data.rows:
        return [f"No hay ventas registradas {when}."]
    return [f"Ventas {_of(args['period'])} {_where(args, locations)} por forma de pago:"] + [
        f"- {PAYMENT_ES.get(r.key, r.key)}: {r.net_sales.text} ({r.share.text})" for r in data.rows
    ]


def _of(period: str) -> str:
    """'de la semana pasada', but 'del mes pasado'."""
    label = PERIOD_ES[period]
    return f"del {label[3:]}" if label.startswith("el ") else f"de {label}"


def _where(args: dict[str, Any], locations: Mapping[UUID, str]) -> str:
    if "location_id" in args:
        return f"en {locations[UUID(args['location_id'])]}"
    if len(locations) == 1:
        return f"en {next(iter(locations.values()))}"
    return f"en tus {len(locations)} sucursales"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


_RENDERERS: dict[str, Callable[[Any, dict[str, Any], Mapping[UUID, str]], list[str]]] = {
    "get_sales_summary": _sales_summary,
    "compare_periods": _compare_periods,
    "get_top_dishes": _top_dishes,
    "get_food_cost_pct": _food_cost,
    "get_data_status": _data_status,
    "compare_locations": _compare_locations,
    "get_sales_breakdown": _payment_methods,
}
