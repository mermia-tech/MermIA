from types import SimpleNamespace
from typing import Any

import pytest
from agno.metrics import RunMetrics
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

from mermia_eval.cases import load_cases
from mermia_eval.config import Price
from mermia_eval.run import RunResult, cost_usd, run_case
from mermia_eval.score import ToolCall

CASE = load_cases()[0]
LUNA = "openai:gpt-5.6-luna"


def _factory(out: RunOutput | Exception) -> Any:
    def run(question: str) -> RunOutput:
        assert question == CASE.question
        if isinstance(out, Exception):
            raise out
        return out

    return lambda **_: SimpleNamespace(run=run)


def _ok() -> RunOutput:
    return RunOutput(
        content="El margen es $37.63.",
        status=RunStatus.completed,
        tools=[
            ToolExecution(
                tool_name="get_dish_margin", tool_args={"dish": "tacos al pastor"}, result="{...}"
            )
        ],
        metrics=RunMetrics(input_tokens=1000, output_tokens=100, cache_read_tokens=400),
    )


def test_success_maps_calls_tokens_and_text() -> None:
    result = run_case(LUNA, CASE, [], agent_factory=_factory(_ok()))
    assert result.error is None
    assert result.calls == [ToolCall("get_dish_margin", {"dish": "tacos al pastor"})]
    assert result.tool_results == ["{...}"]
    assert (result.input_tokens, result.output_tokens, result.cached_tokens) == (1000, 100, 400)
    assert result.text == "El margen es $37.63."
    assert result.seconds >= 0


def test_provider_error_status_sets_error() -> None:
    # Agno returns the provider error as the answer, with status ERROR and zero tokens.
    out = RunOutput(content="Your credit balance is too low", status=RunStatus.error)
    result = run_case(LUNA, CASE, [], agent_factory=_factory(out))
    assert result.error is not None and "credit balance" in result.error
    assert result.calls == []


def test_exception_sets_error_and_does_not_raise() -> None:
    result = run_case(LUNA, CASE, [], agent_factory=_factory(RuntimeError("boom")))
    assert result.error == "boom"


def _result(model: str, reasoning: int = 0) -> RunResult:
    return RunResult(model, [], [], "", 1_000_000, 1_000_000, 400_000, reasoning, 0.0, None, None)


def test_cost_splits_cached_for_openai_and_google() -> None:
    # input includes the cached tokens: 600k at 0.20 + 400k at 0.02 + 1M output at 1.20
    assert cost_usd(_result(LUNA), Price(0.20, 0.02, 1.20)) == pytest.approx(0.12 + 0.008 + 1.20)


def test_cost_adds_cached_for_anthropic() -> None:
    # Anthropic input excludes the cache reads: 1M at 0.10 + 400k at 0.01 + 1M output at 0.50
    cost = cost_usd(_result("anthropic:claude-haiku-5-5"), Price(0.10, 0.01, 0.50))
    assert cost == pytest.approx(0.10 + 0.004 + 0.50)


def test_cost_none_without_price() -> None:
    assert cost_usd(_result(LUNA), None) is None


def test_cost_adds_thinking_tokens_for_google() -> None:
    result = RunResult(
        "google:gemini-3.5-flash-lite", [], [], "", 0, 1_000_000, 0, 500_000, 0, None, None
    )
    assert cost_usd(result, Price(0.30, 0.03, 2.50)) == pytest.approx(1.5 * 2.50)


def test_cost_ignores_reasoning_tokens_for_openai() -> None:
    result = RunResult(LUNA, [], [], "", 0, 1_000_000, 0, 500_000, 0, None, None)
    assert cost_usd(result, Price(0.20, 0.02, 1.20)) == pytest.approx(1.20)


def test_success_maps_reasoning_tokens() -> None:
    out = _ok()
    out.metrics = RunMetrics(input_tokens=1, output_tokens=1, reasoning_tokens=42)
    result = run_case(LUNA, CASE, [], agent_factory=_factory(out))
    assert result.reasoning_tokens == 42


def test_run_case_turns_backend_failures_into_error() -> None:
    result = run_case(LUNA, CASE, [], agent_factory=_factory(_ok()), failures=["ConnectError: x"])
    assert result.error is not None and result.error.startswith("tool backend failed")


def test_run_case_keeps_a_422_as_a_scored_run() -> None:
    result = run_case(LUNA, CASE, [], agent_factory=_factory(_ok()), failures=[])
    assert result.error is None


def test_error_is_not_truncated_in_the_result() -> None:
    # the CLI redacts first and truncates after, so a secret cannot be cut in half
    long = "x" * 400
    raised = run_case(LUNA, CASE, [], agent_factory=_factory(RuntimeError(long)))
    status = RunOutput(content=long, status=RunStatus.error)
    answered = run_case(LUNA, CASE, [], agent_factory=_factory(status))
    backend = run_case(LUNA, CASE, [], agent_factory=_factory(_ok()), failures=[long])
    assert raised.error is not None and len(raised.error) == 400
    assert answered.error is not None and len(answered.error) == 400
    assert backend.error is not None and backend.error.endswith(long)


def test_constructor_failure_is_an_error_not_a_crash() -> None:
    # e.g. an SDK bump that renames a model kwarg must not stop the other models
    def broken(**_: Any) -> Any:
        raise TypeError("unexpected keyword argument 'thinking_level'")

    result = run_case(LUNA, CASE, [], agent_factory=broken)
    assert result.error is not None and "thinking_level" in result.error
    assert result.calls == []


def test_cancelled_run_is_an_error_not_a_score() -> None:
    # Agno turns a Ctrl-C or cancel into a normal output with status cancelled
    out = RunOutput(content="", status=RunStatus.cancelled)
    result = run_case(LUNA, CASE, [], agent_factory=_factory(out))
    assert result.error is not None
    assert result.calls == []
