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
        self.calls: list[tuple[AgentRequest, dict[UUID, str]]] = []

    def __call__(self, request: AgentRequest, locations: Any) -> AgentResponse:
        self.calls.append((request, dict(locations)))
        return AgentResponse(messages=[TextMsg(kind="text", text="(broker)")], route="haiku")


@pytest.fixture
def counting_broker() -> CountingBroker:
    return CountingBroker()
