import base64
from typing import Any

import httpx
import pytest
from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace as otel_trace

from mermia_eval import tracing

ENV = {
    "LANGFUSE_PUBLIC_KEY": "pk-test",
    "LANGFUSE_SECRET_KEY": "sk-test",
    "LANGFUSE_BASE_URL": "https://us.cloud.langfuse.com/",
}


def test_setup_returns_none_without_keys() -> None:
    assert tracing.setup_tracing({}) is None
    assert tracing.setup_tracing({"LANGFUSE_PUBLIC_KEY": "pk-test"}) is None


def test_endpoint_and_auth_header() -> None:
    assert (
        tracing.otlp_endpoint("https://x.example/") == "https://x.example/api/public/otel/v1/traces"
    )
    header = tracing.auth_header("pk", "sk")
    assert header == "Basic " + base64.b64encode(b"pk:sk").decode()


def test_post_scores_noop_without_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise AssertionError("no request expected")

    monkeypatch.setattr(httpx, "post", boom)
    tracing.post_scores(ENV, None, {"tool": 1.0})


def test_post_scores_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def fake(url: str, **kw: Any) -> httpx.Response:
        sent.append({"url": url, **kw})
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake)
    tracing.post_scores(ENV, "abc123", {"tool": 1.0, "args": 0.0})
    assert [s["url"] for s in sent] == ["https://us.cloud.langfuse.com/api/public/scores"] * 2
    assert [s["json"] for s in sent] == [
        {"traceId": "abc123", "name": "tool", "value": 1.0},
        {"traceId": "abc123", "name": "args", "value": 0.0},
    ]
    assert sent[0]["auth"] == ("pk-test", "sk-test")


def test_post_scores_swallows_http_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(url: str, **kw: Any) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", fail)
    tracing.post_scores(ENV, "abc123", {"tool": 1.0})  # must not raise
    err = capsys.readouterr().err
    assert "Langfuse" in err and "sk-test" not in err


def test_setup_makes_the_provider_global(monkeypatch: pytest.MonkeyPatch) -> None:
    # run_case takes its tracer from the global provider; without this its trace id is None
    # and no score is ever posted.
    seen: list[Any] = []
    monkeypatch.setattr(otel_trace, "set_tracer_provider", seen.append)
    monkeypatch.setattr(AgnoInstrumentor, "instrument", lambda self, **kw: None)
    provider = tracing.setup_tracing(ENV)
    assert provider is not None and seen == [provider]


def test_spans_are_exported_in_the_background(monkeypatch: pytest.MonkeyPatch) -> None:
    # A synchronous processor would put the Langfuse round trip inside the measured latency.
    monkeypatch.setattr(otel_trace, "set_tracer_provider", lambda p: None)
    monkeypatch.setattr(AgnoInstrumentor, "instrument", lambda self, **kw: None)
    provider = tracing.setup_tracing(ENV)
    assert provider is not None
    processors = provider._active_span_processor._span_processors
    assert [type(p).__name__ for p in processors] == ["BatchSpanProcessor"]
