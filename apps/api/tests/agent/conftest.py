import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from mermia_contracts.agent import AgentRequest, AgentResponse, TextMsg
from mermia_contracts.rpc import RpcEnvelope

CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")
POLANCO = UUID("fdda5e3b-6bcd-5c48-a6de-f524be37463e")
EXAMPLES = Path(__file__).parents[4] / "packages" / "contracts" / "tests" / "examples" / "rpc"


@pytest.fixture
def el_guero() -> dict[UUID, str]:
    """The two El Güero locations, as the eval system prompt names them."""
    return {CENTRO: "Centro", POLANCO: "Polanco"}


@pytest.fixture
def example() -> Any:
    """example("get_sales_summary.nulls") -> the envelope that C3 example holds (what the mock
    serves)."""

    def load(name: str) -> RpcEnvelope[Any]:
        response = json.loads((EXAMPLES / f"{name}.json").read_text())["response"]
        return RpcEnvelope[Any].model_validate(response)

    return load


class FakeRpc:
    """Answers each RPC with its C3 example, or with what a test put in `answers` (an envelope
    or an exception to raise); records every call."""

    def __init__(self, example: Any) -> None:
        self._example = example
        self.answers: dict[str, RpcEnvelope[Any] | Exception] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, name: str, args: dict[str, Any]) -> RpcEnvelope[Any]:
        self.calls.append((name, args))
        answer = self.answers.get(name) or self._example(name)
        if isinstance(answer, Exception):
            raise answer
        envelope: RpcEnvelope[Any] = answer
        return envelope


@pytest.fixture
def fake_rpc(example: Any) -> FakeRpc:
    return FakeRpc(example)


class CountingBroker:
    def __init__(self) -> None:
        self.calls: list[tuple[AgentRequest, dict[UUID, str], Any]] = []

    def __call__(self, request: AgentRequest, locations: Any, rpc: Any) -> AgentResponse:
        self.calls.append((request, dict(locations), rpc))
        return AgentResponse(messages=[TextMsg(kind="text", text="(broker)")], route="haiku")


@pytest.fixture
def counting_broker() -> CountingBroker:
    return CountingBroker()


class ScriptedAgents:
    """An `agent_factory` for LlmBroker: each `run` plays the next step of `script`. A step is
    an exception to raise or a function of the tools (by name) that returns a run output; the
    `reply` fixture builds those. Records what each agent was built with and its input."""

    def __init__(self) -> None:
        self.script: list[Any] = []
        self.built: list[dict[str, Any]] = []
        self.inputs: list[Any] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.built.append(kwargs)
        tools = {f.name: f for f in kwargs.get("tools", [])}
        factory = self

        class Agent:
            def run(self, input: Any) -> Any:
                factory.inputs.append(input)
                step = factory.script.pop(0)
                if isinstance(step, Exception):
                    raise step
                return step(tools)

        return Agent()


@pytest.fixture
def agents() -> ScriptedAgents:
    return ScriptedAgents()


@pytest.fixture
def reply() -> Any:
    """reply(text, calls=[(tool, args)], ...) -> a script step: it runs each tool call through
    the broker's tools, then answers `text` with the given status and usage."""
    from types import SimpleNamespace

    from agno.metrics import RunMetrics
    from agno.run.base import RunStatus

    def make(
        text: str,
        calls: list[tuple[str, dict[str, Any]]] = (),  # type: ignore[assignment]
        status: RunStatus = RunStatus.completed,
        input_tokens: int = 1000,
        output_tokens: int = 50,
        cached: int = 800,
    ) -> Any:
        def step(tools: dict[str, Any]) -> Any:
            executed = [
                SimpleNamespace(tool_name=n, tool_args=a, result=tools[n].entrypoint(**a))
                for n, a in calls
            ]
            metrics = RunMetrics(
                input_tokens=input_tokens, output_tokens=output_tokens, cache_read_tokens=cached
            )
            return SimpleNamespace(
                content=text, status=status, tools=executed, metrics=metrics, messages=[]
            )

        return step

    return make


@pytest.fixture
def other_rpc(example: Any) -> FakeRpc:
    """A second user's RPC caller, for tests that two requests never share one."""
    return FakeRpc(example)
