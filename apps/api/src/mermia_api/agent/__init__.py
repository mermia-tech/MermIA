"""The agent (09 section 4.2): a deterministic router and zero-token templates first, the LLM
broker for everything else. Spec: docs/superpowers/specs/2026-11-04-mr-26-router-templates-design.md
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from mermia_api.agent.broker import Broker
from mermia_api.agent.router import Match, menu, route
from mermia_api.agent.templates import no_data, render
from mermia_contracts.agent import AgentRequest, AgentResponse, AgentRoute, TextMsg
from mermia_contracts.rpc import RPCS, RpcEnvelope, RpcErrorCode

logger = logging.getLogger(__name__)

RpcCall = Callable[[str, dict[str, Any]], RpcEnvelope[Any]]

UNAVAILABLE = "No pude consultar eso ahora, inténtalo en un momento."


def answer(
    request: AgentRequest, *, locations: Mapping[UUID, str], rpc: RpcCall, broker: Broker
) -> AgentResponse:
    """Answers one message. `locations` names exactly the request's locations (the channel layer
    loads them); a mismatch is a caller bug and must not be answered with a wrong scope."""
    if set(locations) != set(request.location_ids):
        raise ValueError("locations must name exactly the request's location_ids")
    match = None
    if request.input.type == "text":
        match = route(request.input.text, locations)
    elif request.input.type == "action" and request.input.action_id in menu(locations):
        _, match = menu(locations)[request.input.action_id]
    if match is None:
        return broker(request, locations)
    return _template(match, locations, rpc)


def _template(match: Match, locations: Mapping[UUID, str], rpc: RpcCall) -> AgentResponse:
    try:
        RPCS[match.rpc].args.model_validate(match.args)
        envelope = rpc(match.rpc, match.args)
        if envelope.ok:
            return _reply(render(match.rpc, match.args, envelope, locations), "template")
        if envelope.error is not None and envelope.error.code == RpcErrorCode.no_data:
            return _reply(no_data(match.rpc, match.args), "template")
        logger.error("rpc %s failed: %s", match.rpc, envelope.error)
    except Exception:
        # an RPC, transport or shape failure: the broker would call the same RPCs
        logger.exception("rpc %s failed", match.rpc)
    return _reply(TextMsg(kind="text", text=UNAVAILABLE), "fallback")


def _reply(message: TextMsg, route: AgentRoute) -> AgentResponse:
    return AgentResponse(messages=[message], route=route)
