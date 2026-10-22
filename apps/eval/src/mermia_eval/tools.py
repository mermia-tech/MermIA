"""The 12 C4 tools as Agno functions. Each read tool is one POST to the Mock RPC."""

import copy
import json
from collections.abc import Callable
from typing import Any

import httpx
from agno.tools import Function
from fastapi.testclient import TestClient

from mermia_contracts.agent_tools import tool_definitions
from mermia_mock_rpc.app import app

RpcCaller = Callable[[str, dict[str, Any]], str]
_PENDING = json.dumps({"status": "pending_approval"})


class Backend:
    """Calls the mock. Every answer, errors included, goes back to the model as text; the
    infrastructure failures (network, HTTP 5xx) are also kept in `failures`, because they are
    not the model's fault. A 422 (bad arguments) is the model's fault and is not a failure."""

    def __init__(self, client: TestClient | httpx.Client) -> None:
        self._client = client
        self.failures: list[str] = []

    def __call__(self, name: str, args: dict[str, Any]) -> str:
        try:
            response = self._client.post(f"/rpc/{name}", json=args)
        except Exception as e:
            self.failures.append(f"{type(e).__name__}: {e}")
            return self.failures[-1]
        if response.status_code >= 500:
            self.failures.append(f"HTTP {response.status_code}")
        return response.text


def make_rpc_caller(base_url: str | None = None) -> Backend:
    """The mock in-process, or a running one at `base_url`."""
    if base_url is None:
        return Backend(TestClient(app))
    return Backend(httpx.Client(base_url=base_url, timeout=30))


def _entrypoint(name: str, call: RpcCaller) -> Callable[..., str]:
    if name == "propose_change":  # no RPC behind it: record the call, write nothing
        return lambda **_: _PENDING
    return lambda **kwargs: call(name, kwargs)


def build_tools(call: RpcCaller) -> list[Function]:
    # skip_entrypoint_processing: otherwise Agno rewrites the schema and drops `required`.
    return [
        Function(
            name=d["name"],
            description=d["description"],
            parameters=copy.deepcopy(d["input_schema"]),
            entrypoint=_entrypoint(d["name"], call),
            skip_entrypoint_processing=True,
        )
        for d in tool_definitions()
    ]
