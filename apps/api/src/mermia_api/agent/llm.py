"""The provider adapter: one "provider:model_id" string picks the model (docs/decisions/llm.md),
plus its price, the cost rule and Langfuse tracing. Shared with the eval (apps/eval).

Never imported by mermia_api.agent: the template path loads no LLM SDK (MR-26 N1).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from agno.metrics import MessageMetrics
from agno.models.anthropic import Claude
from agno.models.deepseek import DeepSeek
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from openai.types.completion_usage import CompletionUsage
from opentelemetry.sdk.trace import TracerProvider


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: Decimal
    cached: Decimal
    output: Decimal


def _price(input: str, cached: str, output: str) -> Price:
    return Price(Decimal(input), Decimal(cached), Decimal(output))


# docs/kickoff/13 section H1; gpt-6.1-sol is not listed there (only "GPT-6 Sol"), and a model
# without a price meters cost_usd as null.
PRICES: Final = {
    "openai:gpt-5.6-luna": _price("0.20", "0.02", "1.20"),
    "anthropic:claude-haiku-5-5": _price("0.10", "0.01", "0.50"),
    "anthropic:claude-sonnet-5-5": _price("2.00", "0.10", "10.00"),
    "google:gemini-3.8-flash": _price("0.75", "0.075", "3.75"),
    "google:gemini-3.5-flash-lite": _price("0.30", "0.03", "2.50"),
    # DeepSeek pricing page, 2026-11-05. shortcut: always the peak rate, while off-peak is half,
    # so cost is an upper bound; price by time band once DeepSeek serves real traffic.
    "deepseek:deepseek-flash": _price("0.3", "0.006", "1.2"),
    "deepseek:deepseek-v4-pro": _price("1.32", "0.044", "3.96"),
}

# Seconds per HTTP call; without it one stuck Gemini request hung a whole run (MR-20).
TIMEOUT: Final = 60.0


class _DeepSeek(DeepSeek):
    """DeepSeek reports cache hits as `prompt_cache_hit_tokens`, which Agno does not read."""

    def _get_metrics(self, response_usage: CompletionUsage) -> MessageMetrics:
        metrics = super()._get_metrics(response_usage)
        if not metrics.cache_read_tokens:
            metrics.cache_read_tokens = getattr(response_usage, "prompt_cache_hit_tokens", 0) or 0
        return metrics


def build_model(spec_id: str, *, max_output_tokens: int | None = None) -> Any:
    """The Agno model for "provider:model_id", with the same low reasoning for every provider.
    The broker caps output; the eval and its judge leave it uncapped, as MR-20 measured."""
    provider, _, model_id = spec_id.partition(":")
    if provider == "openai":
        return OpenAIResponses(
            id=model_id,
            reasoning_effort="low",
            timeout=TIMEOUT,
            max_output_tokens=max_output_tokens,
        )
    if provider == "google":
        # Retry 429/503 with 10, 20, 40 s waits: the free-tier key allows 15 requests per minute.
        return Gemini(
            id=model_id,
            thinking_level="low",
            timeout=TIMEOUT,
            retries=3,
            delay_between_retries=10,
            exponential_backoff=True,
            max_output_tokens=max_output_tokens,
        )
    if provider == "anthropic":
        if max_output_tokens is None:
            return Claude(id=model_id, timeout=TIMEOUT)
        return Claude(id=model_id, timeout=TIMEOUT, max_tokens=max_output_tokens)
    if provider == "deepseek":
        return _DeepSeek(
            id=model_id, use_thinking=False, timeout=TIMEOUT, max_tokens=max_output_tokens
        )
    raise ValueError(f"unknown provider in {spec_id!r}")


def cost_usd(
    model: str, price: Price | None, *, input: int, cached: int, output: int, reasoning: int
) -> Decimal | None:
    """USD for one call from the provider's token counts; None when the model has no price."""
    if price is None:
        return None
    # Anthropic input excludes the cache reads; OpenAI, Gemini and DeepSeek include them.
    uncached = input if model.startswith("anthropic:") else input - cached
    # Google bills the thinking tokens as output; OpenAI's output count already includes them.
    billed_output = output + (reasoning if model.startswith("google:") else 0)
    return (
        uncached * price.input + cached * price.cached + billed_output * price.output
    ) / 1_000_000


_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")


def otlp_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/public/otel/v1/traces"


def auth_header(public_key: str, secret_key: str) -> str:
    return "Basic " + base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()


def setup_tracing(env: Mapping[str, str]) -> TracerProvider | None:
    """Start sending Agno traces to Langfuse; None (tracing off) when a variable is missing."""
    if not all(env.get(v) for v in _VARS):
        return None
    from openinference.instrumentation.agno import AgnoInstrumentor
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint(env["LANGFUSE_BASE_URL"]),
        headers={
            "Authorization": auth_header(env["LANGFUSE_PUBLIC_KEY"], env["LANGFUSE_SECRET_KEY"])
        },
    )
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)  # so a caller's span joins the same trace
    AgnoInstrumentor().instrument(tracer_provider=provider)
    return provider
