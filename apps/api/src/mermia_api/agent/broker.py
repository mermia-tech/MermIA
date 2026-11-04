"""The broker: what answers a message the router did not take (09 section 4.2).

MR-27 provides the real one (LLM + the 12 tools). It gets its RPC caller when it is built; each
call gets the request and the user's location names.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from mermia_contracts.agent import AgentRequest, AgentResponse, TextMsg


class Broker(Protocol):
    def __call__(self, request: AgentRequest, locations: Mapping[UUID, str]) -> AgentResponse: ...


class StubBroker:
    """Stands in for the LLM broker until MR-27: a fixed reply, never a figure."""

    def __call__(self, request: AgentRequest, locations: Mapping[UUID, str]) -> AgentResponse:
        return AgentResponse(
            messages=[TextMsg(kind="text", text="Todavía no sé responder eso.")], route="fallback"
        )
