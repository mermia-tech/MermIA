"""The LLM broker (09 section 4.2, MR-27): the model picks among the 12 tools, and its reply is
sent only if every figure in it has a source (validator.py). Anything else gets the menu.

Imported only where the broker is built: it loads the LLM SDKs (the template path must not).
Spec: docs/superpowers/specs/2026-11-05-mr-27-broker-validator-design.md
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid4

from agno.agent import Agent
from agno.metrics import RunMetrics
from agno.models.message import Message
from agno.run.base import RunStatus
from agno.tools import Function
from pydantic import ValidationError

from mermia_api.agent.broker import RpcCall, fallback
from mermia_api.agent.llm import PRICES, build_model, cost_usd
from mermia_api.agent.prompt import STATIC_PREFIX, tail
from mermia_api.agent.templates import MEXICO_CITY
from mermia_api.agent.usage import UsageRow, UsageStore, fresh
from mermia_api.agent.validator import validate
from mermia_contracts.agent import AgentRequest, AgentResponse, TextInput, TextMsg
from mermia_contracts.agent_tools import tool_definitions
from mermia_contracts.db.models import MemberRole
from mermia_contracts.rpc import RPCS

MAX_OUTPUT_TOKENS: Final = 400
TOOL_CALL_LIMIT: Final = 4
DAILY_QUESTIONS: Final = 60  # LLM questions per tenant per Mexico City day; then the menu
REJECTED: Final = "No pude confirmar esa cifra. Prueba con una de estas:"
UNAVAILABLE: Final = "No pude responder eso ahora. Prueba con una de estas:"
OVER_CAP: Final = "Por hoy ya no puedo responder preguntas abiertas. Prueba con una de estas:"
_PENDING = json.dumps({"status": "pending_approval"})


def _entrypoint(name: str, rpc: RpcCall, results: list[str]) -> Callable[..., str]:
    """One tool: arguments checked against the RPC's contract, then the call as the user (09
    D8). Every outcome goes back to the model as text; only RPC answers count as sources."""
    if name == "propose_change":  # the confirmation flow writes, never the LLM (09 section 5)
        return lambda **_: _PENDING

    def call(**kwargs: Any) -> str:
        try:
            RPCS[name].args.model_validate(kwargs)
        except ValidationError as e:
            return str(e)
        try:
            envelope = rpc(name, kwargs)
        except Exception as e:  # network or timeout: the model says it could not check
            return f"{type(e).__name__}: {e}"
        text = envelope.model_dump_json()
        results.append(text)
        return text

    return call


def _tools(rpc: RpcCall, results: list[str]) -> list[Function]:
    # skip_entrypoint_processing: otherwise Agno rewrites the schema and drops `required`.
    return [
        Function(
            name=d["name"],
            description=d["description"],
            parameters=copy.deepcopy(d["input_schema"]),
            entrypoint=_entrypoint(d["name"], rpc, results),
            skip_entrypoint_processing=True,
        )
        for d in tool_definitions()
    ]


def _reply_text(out: Any) -> str:
    """The last model message: Agno joins every turn's text into `content`, so the owner would
    get the narration written before a tool call ("Voy a revisar….Sí, …")."""
    said = [m for m in (out.messages or []) if m.role == "assistant"]
    if said:
        return said[-1].get_content_string() or ""
    return str(out.content or "")  # no messages: a provider error's text, or a test double


def _reply(text: str, usage_id: UUID) -> AgentResponse:
    return AgentResponse(
        messages=[TextMsg(kind="text", text=text)], route="haiku", usage_id=usage_id
    )


def _correction(figures: set[Decimal]) -> str:
    shown = ", ".join(str(f) for f in sorted(figures))
    return (
        f"Estas cifras no salen de ninguna herramienta: {shown}. Reescribe la respuesta usando "
        "solo cifras que devolvieron las herramientas, copiadas tal cual. Este aviso es "
        "interno: no lo menciones."
    )


class LlmBroker:
    """`role_of` gives the user's role for the tail: the request does not carry it, and the
    caller already knows it from the membership it checked."""

    def __init__(
        self,
        model: str,
        store: UsageStore,
        *,
        role_of: Callable[[AgentRequest], MemberRole],
        agent_factory: Callable[..., Any] = Agent,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._model = model
        self._store = store
        self._role_of = role_of
        self._agent_factory = agent_factory
        self._clock = clock

    def __call__(
        self, request: AgentRequest, locations: Mapping[UUID, str], rpc: RpcCall
    ) -> AgentResponse:
        if not isinstance(request.input, TextInput):  # pc: actions and media have no handler yet
            return fallback(locations)
        question = request.input.text
        now = self._clock()
        today = now.astimezone(MEXICO_CITY).date()
        if self._store.questions_today(request.tenant_id, today) >= DAILY_QUESTIONS:
            return fallback(locations, OVER_CAP)
        memory = fresh(self._store.turns(request.tenant_id, request.user_id, request.channel), now)
        context = tail(today=today, role=self._role_of(request), locations=locations)
        messages = [
            Message(role="user", content=context),
            *(
                m
                for t in memory
                for m in (Message(role="user", content=t.q), Message(role="assistant", content=t.a))
            ),
            Message(role="user", content=question),
        ]
        request_id = str(uuid4())
        results: list[str] = []  # both runs' tool results are sources for the retry

        def unsourced(text: str) -> set[Decimal]:
            return validate(
                text, tool_results=results, question=question, memory=memory, dates=[str(today)]
            )

        row, text, said = self._call(request, request_id, messages, rpc, results)
        if text is None:
            return fallback(locations, UNAVAILABLE, self._store.add(row))
        if not (figures := unsourced(text)):
            return _reply(text, self._store.add(replace(row, validator_result="pass")))
        self._store.add(replace(row, validator_result="retry"))
        retry = [*said, Message(role="user", content=_correction(figures))]
        row, text, _ = self._call(request, request_id, retry, rpc, results)
        if text is None:
            return fallback(locations, UNAVAILABLE, self._store.add(row))
        if unsourced(text):
            return fallback(
                locations, REJECTED, self._store.add(replace(row, validator_result="reject"))
            )
        return _reply(text, self._store.add(replace(row, validator_result="retry_pass")))

    def _call(
        self,
        request: AgentRequest,
        request_id: str,
        messages: list[Message],
        rpc: RpcCall,
        results: list[str],
    ) -> tuple[UsageRow, str | None, list[Message]]:
        """One model run: its usage row (no validator result yet), the reply (None when the
        provider failed or the reply is empty or cut at the output cap) and the run's messages
        without the system one, for a retry that re-sends the tool results without new calls."""
        start = time.perf_counter()
        out: Any = None
        error: str | None = None
        try:
            agent = self._agent_factory(
                model=build_model(self._model, max_output_tokens=MAX_OUTPUT_TOKENS),
                tools=_tools(rpc, results),
                instructions=STATIC_PREFIX,
                tool_call_limit=TOOL_CALL_LIMIT,
                telemetry=False,
            )
            out = agent.run(messages)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        latency_ms = int((time.perf_counter() - start) * 1000)
        text = _reply_text(out).strip() if out is not None else ""
        metrics: RunMetrics | None = out.metrics if out is not None else None
        if out is not None and out.status != RunStatus.completed:  # the provider's error text
            error = str(out.content or "").strip() or f"run {out.status}"
        elif out is not None and not text:
            error = "empty reply"
        elif metrics is not None and self._output_tokens(metrics) >= MAX_OUTPUT_TOKENS:
            error = "incomplete reply: output cap reached"  # Agno reports a cut reply as done
        row = UsageRow(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            request_id=request_id,
            model=self._model,
            latency_ms=latency_ms,
            tool_calls=len(out.tools or []) if out is not None else 0,
            ts=self._clock(),
            error=error,
        )
        if metrics is not None:
            row = replace(
                row,
                input_tokens=metrics.input_tokens,
                cache_read_tokens=metrics.cache_read_tokens,
                cache_write_tokens=metrics.cache_write_tokens,
                output_tokens=metrics.output_tokens,
                cost_usd=cost_usd(
                    self._model,
                    PRICES.get(self._model),
                    input=metrics.input_tokens,
                    cached=metrics.cache_read_tokens,
                    output=metrics.output_tokens,
                    reasoning=metrics.reasoning_tokens,
                ),
            )
        said = [m for m in (out.messages or []) if m.role != "system"] if out is not None else []
        return row, None if error else text, said

    def _output_tokens(self, metrics: RunMetrics) -> int:
        # Gemini reports its thinking apart from the output, but it counts toward the cap.
        thinking = metrics.reasoning_tokens if self._model.startswith("google:") else 0
        return metrics.output_tokens + thinking
