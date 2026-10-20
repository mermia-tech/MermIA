"""One model answering one case, and what it cost."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from agno.agent import Agent
from agno.run.base import RunStatus
from agno.tools import Function
from opentelemetry import trace

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


def run_case(
    model: str,
    case: Case,
    tools: list[Function],
    agent_factory: Callable[..., Any] = Agent,
    failures: Sequence[str] = (),  # tool backend failures during this run
) -> RunResult:
    agent = agent_factory(
        model=build_model(model), tools=tools, instructions=SYSTEM_PROMPT, telemetry=False
    )
    result = RunResult(model, [], [], "", 0, 0, 0, 0, 0.0, None, None)
    with trace.get_tracer("mermia_eval").start_as_current_span("eval.run") as span:
        ctx = span.get_span_context()
        result.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        start = time.perf_counter()
        try:
            out = agent.run(case.question)
        except Exception as e:  # a failing model must not stop the others
            result.error = str(e)
            out = None
        result.seconds = time.perf_counter() - start
    if out is None:
        return result
    result.text = str(out.content or "")
    if out.status == RunStatus.error:  # Agno returns provider errors as the answer text
        result.error = result.text
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


def cost_usd(result: RunResult, price: Price | None) -> float | None:
    if price is None:
        return None
    cached = result.cached_tokens
    # Anthropic input excludes the cache reads; OpenAI and Gemini include them.
    uncached = (
        result.input_tokens
        if result.model.startswith("anthropic:")
        else (result.input_tokens - cached)
    )
    # Google bills the thinking tokens as output; OpenAI's output count already includes them.
    output = result.output_tokens + (
        result.reasoning_tokens if result.model.startswith("google:") else 0
    )
    return (uncached * price.input + cached * price.cached + output * price.output) / 1e6
