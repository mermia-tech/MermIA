import json
from typing import Any

import httpx

from mermia_contracts.agent_tools import tool_definitions
from mermia_eval.tools import Backend, build_tools, make_rpc_caller


def _never(name: str, args: dict[str, Any]) -> str:
    raise AssertionError(f"the mock must not be called: {name}")


def test_twelve_tools_in_c4_order() -> None:
    tools = build_tools(_never)
    assert [t.name for t in tools] == [d["name"] for d in tool_definitions()]


def test_schemas_reach_agno_unchanged() -> None:
    # Agno empties `required` when it processes an entrypoint(**kwargs); the spike found it.
    for tool, definition in zip(build_tools(_never), tool_definitions(), strict=True):
        tool.process_entrypoint()
        assert tool.parameters == definition["input_schema"], tool.name
        assert tool.description == definition["description"]


def test_required_is_kept() -> None:
    tool = next(t for t in build_tools(_never) if t.name == "get_dish_margin")
    tool.process_entrypoint()
    assert tool.parameters["required"] == ["dish"]


def test_read_tool_calls_the_mock() -> None:
    tool = next(t for t in build_tools(make_rpc_caller()) if t.name == "get_dish_margin")
    assert tool.entrypoint is not None
    assert "$37.63" in tool.entrypoint(dish="tacos al pastor")


def test_bad_arguments_return_the_mock_422_text() -> None:
    tool = next(t for t in build_tools(make_rpc_caller()) if t.name == "get_dish_margin")
    assert tool.entrypoint is not None
    assert "detail" in tool.entrypoint(plato="tacos")  # the model sees the error, nothing raises


def test_propose_change_never_calls_the_mock() -> None:
    tool = next(t for t in build_tools(_never) if t.name == "propose_change")
    assert tool.entrypoint is not None
    result = tool.entrypoint(kind="ingredient_price.set", target="carne al pastor")
    assert json.loads(result) == {"status": "pending_approval"}


def test_unreachable_backend_records_a_failure() -> None:
    backend = make_rpc_caller("http://127.0.0.1:1")
    text = backend("get_dish_margin", {"dish": "x"})  # returns text, does not raise
    assert "ConnectError" in text
    assert len(backend.failures) == 1


def test_server_error_status_is_a_failure() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom")),
        base_url="http://mock",
    )
    backend = Backend(client)
    assert backend("get_dish_margin", {"dish": "x"}) == "boom"
    assert backend.failures == ["HTTP 500"]


def test_422_is_not_a_failure() -> None:
    backend = make_rpc_caller()
    assert "detail" in backend("get_dish_margin", {"plato": "x"})
    assert backend.failures == []
