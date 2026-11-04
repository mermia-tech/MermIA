"""Zero-token replies: es-MX text built from one RPC result.

Every figure is copied from the RPC data (its `text` fields, names, counts) or is a flag message
our own SQL wrote; nothing is computed or reformatted (CLAUDE.md: the agent never computes money).
Keyed by RPC name, not by router intent, so the MR-27 broker can render its own tool calls.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter

from mermia_contracts.agent import TextMsg
from mermia_contracts.rpc import RPCS, ComparePeriodsData, RpcEnvelope, SalesSummaryData

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
    return TextMsg(kind="text", text=f"No tengo datos de {PERIOD_ES[args['period']]} todavía.")


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
}
