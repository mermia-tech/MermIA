"""Langfuse: Agno traces through OpenInference + OTLP, and the scores of each run."""

import base64
import sys
from collections.abc import Mapping

import httpx
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")


def otlp_endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/public/otel/v1/traces"


def auth_header(public_key: str, secret_key: str) -> str:
    return "Basic " + base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()


def setup_tracing(env: Mapping[str, str]) -> TracerProvider | None:
    """Start sending Agno traces to Langfuse; None (tracing off) when a variable is missing."""
    if not all(env.get(v) for v in _VARS):
        return None
    exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint(env["LANGFUSE_BASE_URL"]),
        headers={
            "Authorization": auth_header(env["LANGFUSE_PUBLIC_KEY"], env["LANGFUSE_SECRET_KEY"])
        },
    )
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)  # so run_case's span joins the same trace
    AgnoInstrumentor().instrument(tracer_provider=provider)
    return provider


def post_scores(env: Mapping[str, str], trace_id: str | None, scores: Mapping[str, float]) -> None:
    """Attach the scores to a trace. A Langfuse failure is a warning, never an error."""
    if trace_id is None:
        return
    base = env["LANGFUSE_BASE_URL"].rstrip("/")
    auth = (env["LANGFUSE_PUBLIC_KEY"], env["LANGFUSE_SECRET_KEY"])
    for name, value in scores.items():
        try:
            response = httpx.post(
                f"{base}/api/public/scores",
                json={"traceId": trace_id, "name": name, "value": value},
                auth=auth,
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            print(
                f"warning: Langfuse score {name!r} not saved ({type(e).__name__})", file=sys.stderr
            )
