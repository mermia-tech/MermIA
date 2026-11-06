"""One model answering one case, and what it cost."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from agno.agent import Agent
from agno.run.base import RunStatus
from agno.tools import Function
from opentelemetry import trace

from mermia_api.agent import llm
from mermia_api.agent.llm_broker import LlmBroker
from mermia_api.agent.usage import MemoryStore
from mermia_contracts.agent import AgentRequest, TextInput, TextMsg
from mermia_contracts.db.models import Channel, MemberRole
from mermia_contracts.rpc import RpcEnvelope
from mermia_eval.cases import Case
from mermia_eval.config import SYSTEM_PROMPT, Price, build_model
from mermia_eval.score import ToolCall


@dataclass
class RunResult:
    model: str
    calls: list[ToolCall]
    tool_results: list[str]
    text: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    reasoning_tokens: int  # Gemini reports its thinking apart from the output
    seconds: float
    error: str | None  # set when the provider failed: such a run is never scored
    trace_id: str | None
    validator: list[str] = field(default_factory=list)  # --broker: validator_result per call


def run_case(
    model: str,
    case: Case,
    tools: list[Function],
    agent_factory: Callable[..., Any] = Agent,
    failures: Sequence[str] = (),  # tool backend failures during this run
) -> RunResult:
    result = RunResult(model, [], [], "", 0, 0, 0, 0, 0.0, None, None)
    with trace.get_tracer("mermia_eval").start_as_current_span("eval.run") as span:
        ctx = span.get_span_context()
        result.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        start = time.perf_counter()
        try:
            agent = agent_factory(
                model=build_model(model), tools=tools, instructions=SYSTEM_PROMPT, telemetry=False
            )
            out = agent.run(case.question)
        except Exception as e:  # a failing model must not stop the others
            result.error = str(e)
            out = None
        result.seconds = time.perf_counter() - start
    if out is None:
        return result
    result.text = str(out.content or "")
    if out.status != RunStatus.completed:  # provider errors come back as the answer text
        result.error = result.text or f"run {out.status}"
        return result
    for t in out.tools or []:
        result.calls.append(ToolCall(t.tool_name or "", dict(t.tool_args or {})))
        result.tool_results.append(t.result or "")
    if m := out.metrics:
        result.input_tokens = m.input_tokens
        result.output_tokens = m.output_tokens
        result.cached_tokens = m.cache_read_tokens
        result.reasoning_tokens = m.reasoning_tokens
    if failures and result.error is None:  # the model is not to blame for a dead backend
        result.error = f"tool backend failed: {failures[0]}"
    return result


# The El Güero locations and the day the mock data and SYSTEM_PROMPT assume (09:00 in CDMX).
LOCATIONS = {
    UUID("705e8e51-376b-5785-adbb-405eff4e2a22"): "Centro",
    UUID("fdda5e3b-6bcd-5c48-a6de-f524be37463e"): "Polanco",
}
NOW = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)


def run_broker_case(
    model: str,
    case: Case,
    backend: Callable[[str, dict[str, Any]], str],
    agent_factory: Callable[..., Any] = Agent,
    failures: Sequence[str] = (),
) -> RunResult:
    """The case through the API's LlmBroker (MR-27): its prompt, validator and retry. A menu
    answer (reject or provider failure) is an error here, so it is counted apart, not scored."""
    runs: list[Any] = []

    def recording(**kwargs: Any) -> Any:
        agent = agent_factory(**kwargs)

        def run(input: Any) -> Any:
            out = agent.run(input)
            runs.append(out)
            return out

        return SimpleNamespace(run=run)

    store = MemoryStore()
    broker = LlmBroker(
        model,
        store,
        role_of=lambda _: MemberRole.owner,
        agent_factory=recording,
        clock=lambda: NOW,
    )
    request = AgentRequest(
        tenant_id=uuid4(),
        user_id=uuid4(),
        location_ids=list(LOCATIONS),
        channel=Channel.whatsapp,
        conversation_id=uuid4(),
        input=TextInput(type="text", text=case.question),
    )
    rpc = lambda name, args: RpcEnvelope[Any].model_validate_json(backend(name, args))  # noqa: E731
    result = RunResult(model, [], [], "", 0, 0, 0, 0, 0.0, None, None)
    with trace.get_tracer("mermia_eval").start_as_current_span("eval.broker") as span:
        ctx = span.get_span_context()
        result.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        start = time.perf_counter()
        response = broker(request, LOCATIONS, rpc)
        result.seconds = time.perf_counter() - start
    for out in runs:
        for t in getattr(out, "tools", None) or []:
            result.calls.append(ToolCall(t.tool_name or "", dict(t.tool_args or {})))
            result.tool_results.append(t.result or "")
    # shortcut: the rows carry no reasoning tokens, so Gemini's thinking is left out of the
    # eval cost here (the rows' own cost_usd has it); add a field if Gemini is smoked.
    for row in store.rows:
        result.input_tokens += row.input_tokens or 0
        result.output_tokens += row.output_tokens or 0
        result.cached_tokens += row.cache_read_tokens or 0
    result.validator = [r.validator_result or "error" for r in store.rows]
    message = response.messages[0]
    result.text = message.text if isinstance(message, TextMsg) else ""
    if response.route == "fallback":
        last = store.rows[-1] if store.rows else None
        result.error = f"menu ({last.error or last.validator_result if last else 'no call'})"
    elif failures:
        result.error = f"tool backend failed: {failures[0]}"
    return result


def cost_usd(result: RunResult, price: Price | None) -> float | None:
    cost = llm.cost_usd(
        result.model,
        price,
        input=result.input_tokens,
        cached=result.cached_tokens,
        output=result.output_tokens,
        reasoning=result.reasoning_tokens,
    )
    return None if cost is None else float(cost)
