"""The broker: what answers a message the router did not take (09 section 4.2).

The LLM broker (MR-27) lives in llm_broker.py, so importing this module loads no LLM SDK. Each
call gets the request, the user's location names and the RPC caller: the caller carries the
user's identity (09 D8), so it is never fixed when a broker is built.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol
from uuid import UUID

from mermia_api.agent.router import menu
from mermia_contracts.agent import AgentRequest, AgentResponse, Choice, ChoicesMsg
from mermia_contracts.rpc import RpcEnvelope

RpcCall = Callable[[str, dict[str, Any]], RpcEnvelope[Any]]


class Broker(Protocol):
    def __call__(
        self, request: AgentRequest, locations: Mapping[UUID, str], rpc: RpcCall
    ) -> AgentResponse: ...


def fallback(
    locations: Mapping[UUID, str],
    text: str = "Todavía no sé responder eso. Prueba con una de estas:",
    usage_id: UUID | None = None,
) -> AgentResponse:
    """The template menu: the answer whenever the LLM cannot give one."""
    options = [Choice(id=i, label=label) for i, (label, _) in menu(locations).items()]
    return AgentResponse(
        messages=[ChoicesMsg(kind="choices", text=text, options=options)],
        route="fallback",
        usage_id=usage_id,
    )


class StubBroker:
    """Stands in for the LLM broker until MR-27: a fixed reply and the template menu, never a
    figure. With MR-27 the menu shows only when the LLM is unavailable or over its cap."""

    def __call__(
        self, request: AgentRequest, locations: Mapping[UUID, str], rpc: RpcCall
    ) -> AgentResponse:
        return fallback(locations)
