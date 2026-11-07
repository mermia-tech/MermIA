"""The broker: what answers a message the router did not take (09 section 4.2).

MR-27 provides the real one (LLM + the 12 tools). It gets its RPC caller when it is built; each
call gets the request and the user's location names.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from mermia_api.agent.router import menu
from mermia_contracts.agent import AgentRequest, AgentResponse, Choice, ChoicesMsg


class Broker(Protocol):
    def __call__(self, request: AgentRequest, locations: Mapping[UUID, str]) -> AgentResponse: ...


class StubBroker:
    """Stands in for the LLM broker until MR-27: a fixed reply and the template menu, never a
    figure. With MR-27 the menu shows only when the LLM is unavailable or over its cap."""

    def __call__(self, request: AgentRequest, locations: Mapping[UUID, str]) -> AgentResponse:
        options = [Choice(id=i, label=label) for i, (label, _) in menu(locations).items()]
        text = "Todavía no sé responder eso. Prueba con una de estas:"
        return AgentResponse(
            messages=[ChoicesMsg(kind="choices", text=text, options=options)], route="fallback"
        )
