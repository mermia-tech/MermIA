"""The agent (09 section 4.2): a deterministic router and zero-token templates first, the LLM
broker for everything else. Spec: docs/superpowers/specs/2026-11-04-mr-26-router-templates-design.md
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from mermia_api.agent.broker import Broker, RpcCall, fallback
from mermia_api.agent.router import Match, menu, route
from mermia_api.agent.templates import no_data, render
from mermia_api.agent.usage import UsageStore, fresh
from mermia_api.agent.validator import Turn
from mermia_contracts.agent import AgentRequest, AgentResponse, AgentRoute, TextInput, TextMsg
from mermia_contracts.rpc import RPCS, RpcErrorCode

logger = logging.getLogger(__name__)

UNAVAILABLE = "No pude consultar eso ahora, inténtalo en un momento."


def respond(
    request: AgentRequest,
    *,
    locations: Mapping[UUID, str],
    rpc: RpcCall,
    broker: Broker,
    store: UsageStore,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AgentResponse:
    """The channel's entry point: answer(), then the turn it leaves in memory. It never raises:
    any failure gets the menu, and a failed memory write still sends the answer."""
    try:
        response = answer(request, locations=locations, rpc=rpc, broker=broker)
    except Exception:
        logger.exception("agent failed, sending the menu")
        return fallback(locations)
    texts = [m.text for m in response.messages if isinstance(m, TextMsg)]
    # shortcut: only text questions become turns; a menu tap answered by a template is not
    # remembered, so "¿y Norte?" after a tap has no context; store the tapped label if it matters.
    if response.route != "fallback" and texts and isinstance(request.input, TextInput):
        try:
            now = clock()
            key = (request.tenant_id, request.user_id, request.channel)
            turns = fresh(store.turns(*key), now)
            store.save_turns(*key, [*turns, Turn(q=request.input.text, a=texts[0], ts=now)])
        except Exception:
            logger.exception("could not save the conversation turn")
    return response


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
        return broker(request, locations, rpc)
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
