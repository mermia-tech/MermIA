"""The LLM prompt: a static prefix, byte-identical for every tenant, user and day so the provider
caches it (09 section 4.2), and a tail message with this request's context.

Never put tenant data, a date or a name in STATIC_PREFIX. Phone numbers, RFCs and staff names
never reach the LLM (CLAUDE.md), so the tail takes only today, the role and location names.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Final
from uuid import UUID

from mermia_api.agent.templates import MONTHS
from mermia_contracts.db.models import MemberRole

STATIC_PREFIX: Final = (
    "Eres el asistente de un restaurante en México. Responde en español de México, breve y claro. "
    "Para cualquier cifra usa las herramientas y cópiala tal como la devuelven; nunca inventes, "
    "sumes, restes, redondees ni calcules números. Si hace falta un total o una diferencia que "
    "ninguna herramienta da, dilo. "
    "Escribe las cifras con dígitos, nunca con letras. "
    "Si no existe una herramienta para lo que piden, dilo. "
    "Si no dice sucursal, usa todas las suyas. Pregunta solo si falta algo que no se puede "
    "suponer, como el precio nuevo de un cambio. "
    "Los cambios solo se proponen con propose_change; nunca digas que ya se aplicaron. "
    "El primer mensaje del usuario trae la fecha de hoy, su rol y sus sucursales."
)

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_ROLES = {
    MemberRole.owner: "dueño",
    MemberRole.manager: "gerente",
    MemberRole.admin: "administrador",
    MemberRole.support: "soporte",
}


def tail(*, today: date, role: MemberRole, locations: Mapping[UUID, str]) -> str:
    """The per-request context, sent as a user message after the cached prefix. `today` is the
    America/Mexico_City date; its ISO form is also what the validator treats as a date."""
    day = f"{_WEEKDAYS[today.weekday()]} {today.day} de {MONTHS[today.month - 1]} de {today.year}"
    names = ", ".join(f"{name} ({id_})" for id_, name in locations.items())
    return (
        f"Hoy es {day} ({today.isoformat()}). Rol del usuario: {_ROLES[role]}. Sucursales: {names}."
    )
