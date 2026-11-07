"""Langfuse: Agno traces through OpenInference + OTLP, and the scores of each run."""

import sys
from collections.abc import Mapping

import httpx

from mermia_api.agent.llm import auth_header, otlp_endpoint, setup_tracing

__all__ = ["auth_header", "otlp_endpoint", "post_scores", "setup_tracing"]


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
