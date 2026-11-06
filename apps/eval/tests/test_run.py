from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from agno.metrics import RunMetrics
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

from mermia_eval.cases import load_cases
from mermia_eval.config import Price
from mermia_eval.run import RunResult, cost_usd, run_broker_case, run_case
from mermia_eval.score import ToolCall
from mermia_eval.tools import make_rpc_caller

CASE = next(c for c in load_cases() if c.id == "tacos_al_pastor")
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
    assert cost_usd(
        _result(LUNA), Price(Decimal("0.20"), Decimal("0.02"), Decimal("1.20"))
    ) == pytest.approx(0.12 + 0.008 + 1.20)


def test_cost_adds_cached_for_anthropic() -> None:
    # Anthropic input excludes the cache reads: 1M at 0.10 + 400k at 0.01 + 1M output at 0.50
    cost = cost_usd(
        _result("anthropic:claude-haiku-5-5"),
        Price(Decimal("0.10"), Decimal("0.01"), Decimal("0.50")),
    )
    assert cost == pytest.approx(0.10 + 0.004 + 0.50)


def test_cost_none_without_price() -> None:
    assert cost_usd(_result(LUNA), None) is None


def test_cost_adds_thinking_tokens_for_google() -> None:
    result = RunResult(
        "google:gemini-3.5-flash-lite", [], [], "", 0, 1_000_000, 0, 500_000, 0, None, None
    )
    assert cost_usd(
        result, Price(Decimal("0.30"), Decimal("0.03"), Decimal("2.50"))
    ) == pytest.approx(1.5 * 2.50)


def test_cost_ignores_reasoning_tokens_for_openai() -> None:
    result = RunResult(LUNA, [], [], "", 0, 1_000_000, 0, 500_000, 0, None, None)
    assert cost_usd(
        result, Price(Decimal("0.20"), Decimal("0.02"), Decimal("1.20"))
    ) == pytest.approx(1.20)


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


# --broker: the case goes through the real LlmBroker (MR-27), the model is scripted.

MARGIN_ARGS = {"dish": "tacos al pastor", "location_id": "705e8e51-376b-5785-adbb-405eff4e2a22"}


def _broker_factory(*texts: str) -> Any:
    """Each run calls get_dish_margin through the broker's own tool, then answers the next text."""
    script = list(texts)

    def factory(**kwargs: Any) -> Any:
        tools = {f.name: f for f in kwargs["tools"]}

        def run(_: Any) -> RunOutput:
            result = tools["get_dish_margin"].entrypoint(**MARGIN_ARGS)
            return RunOutput(
                content=script.pop(0),
                status=RunStatus.completed,
                tools=[
                    ToolExecution(tool_name="get_dish_margin", tool_args=MARGIN_ARGS, result=result)
                ],
                metrics=RunMetrics(input_tokens=1000, output_tokens=100, cache_read_tokens=400),
                messages=[],
            )

        return SimpleNamespace(run=run)

    return factory


def test_the_broker_path_maps_a_sent_reply() -> None:
    backend = make_rpc_caller()
    result = run_broker_case(
        LUNA, CASE, backend, agent_factory=_broker_factory("El margen es $37.63.")
    )
    assert result.error is None
    assert result.text == "El margen es $37.63."
    assert result.calls == [ToolCall("get_dish_margin", MARGIN_ARGS)]
    assert "$37.63" in result.tool_results[0]
    assert (result.input_tokens, result.output_tokens, result.cached_tokens) == (1000, 100, 400)
    assert result.validator == ["pass"]


def test_the_broker_path_counts_a_menu_apart() -> None:
    backend = make_rpc_caller()
    invented = "El margen es $40.00."
    result = run_broker_case(LUNA, CASE, backend, agent_factory=_broker_factory(invented, invented))
    assert result.error is not None and result.error.startswith("menu")  # not scored as a reply
    assert result.validator == ["retry", "reject"]
    assert len(result.calls) == 2 and result.input_tokens == 2000  # both runs are paid for
