"""MR-26: answer() sends what the router takes to a template and everything else to the broker
(spec: Pipeline, RPC failures)."""

import logging
import subprocess
import sys
from typing import Any
from uuid import UUID, uuid4

import pytest

from mermia_api.agent import answer
from mermia_api.agent.broker import StubBroker
from mermia_contracts.agent import AgentRequest, AgentResponse, TextMsg
from mermia_contracts.rpc import RpcEnvelope

UNAVAILABLE = "No pude consultar eso ahora, inténtalo en un momento."


def _request(locations: dict[UUID, str], input: dict[str, Any]) -> AgentRequest:
    return AgentRequest.model_validate(
        {
            "tenant_id": str(uuid4()),
            "user_id": str(uuid4()),
            "location_ids": [str(i) for i in locations],
            "channel": "whatsapp",
            "conversation_id": str(uuid4()),
            "input": input,
        }
    )


def _text(locations: dict[UUID, str], text: str) -> AgentRequest:
    return _request(locations, {"type": "text", "text": text})


def _reply_text(response: AgentResponse) -> str:
    (message,) = response.messages
    assert isinstance(message, TextMsg)
    return message.text


def _error(code: str) -> RpcEnvelope[Any]:
    return RpcEnvelope[Any].model_validate(
        {
            "ok": False,
            "error": {"code": code, "message": "x"},
            "meta": {"as_of": "2026-10-12T09:00:00-06:00"},
        }
    )


def test_a_matched_question_is_answered_by_a_template(
    el_guero: dict[UUID, str], fake_rpc: Any, counting_broker: Any
) -> None:
    response = answer(
        _text(el_guero, "¿cuánto vendí ayer?"),
        locations=el_guero,
        rpc=fake_rpc,
        broker=counting_broker,
    )
    assert response.route == "template"
    assert _reply_text(response).startswith("Ayer en tus 2 sucursales vendiste $184,320.50.")
    assert fake_rpc.calls == [("get_sales_summary", {"period": "yesterday"})]
    assert counting_broker.calls == []


@pytest.mark.parametrize(
    "input",
    [
        {"type": "text", "text": "¿qué vino me recomiendas?"},
        {"type": "action", "action_id": f"pc:{uuid4()}:approve"},
        {"type": "action", "action_id": "row:3"},
        {"type": "media", "raw_file_id": str(uuid4())},
    ],
)
def test_everything_else_goes_to_the_broker_unchanged(
    input: dict[str, Any], el_guero: dict[UUID, str], fake_rpc: Any, counting_broker: Any
) -> None:
    request = _request(el_guero, input)
    response = answer(request, locations=el_guero, rpc=fake_rpc, broker=counting_broker)
    assert response.route == "haiku"  # what the counting broker answers
    assert counting_broker.calls == [(request, el_guero)]
    assert fake_rpc.calls == []


def test_locations_must_be_the_requests_locations(
    el_guero: dict[UUID, str], fake_rpc: Any, counting_broker: Any
) -> None:
    request = _text({next(iter(el_guero)): "Centro"}, "¿cuánto vendí ayer?")
    with pytest.raises(ValueError, match="location_ids"):
        answer(request, locations=el_guero, rpc=fake_rpc, broker=counting_broker)


def test_no_data_gets_a_template_reply(
    el_guero: dict[UUID, str], fake_rpc: Any, counting_broker: Any
) -> None:
    fake_rpc.answers["get_sales_summary"] = _error("no_data")
    response = answer(
        _text(el_guero, "cuánto vendí ayer"),
        locations=el_guero,
        rpc=fake_rpc,
        broker=counting_broker,
    )
    assert response.route == "template"
    assert _reply_text(response) == "No tengo datos de ayer todavía."


@pytest.mark.parametrize(
    "failure",
    [_error("internal"), _error("forbidden"), RuntimeError("connection reset")],
    ids=["internal", "forbidden", "raised"],
)
def test_other_failures_get_the_fixed_fallback_reply(
    failure: Any,
    el_guero: dict[UUID, str],
    fake_rpc: Any,
    counting_broker: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_rpc.answers["get_sales_summary"] = failure
    with caplog.at_level(logging.ERROR, logger="mermia_api.agent"):
        response = answer(
            _text(el_guero, "cuánto vendí ayer"),
            locations=el_guero,
            rpc=fake_rpc,
            broker=counting_broker,
        )
    assert response.route == "fallback"
    assert _reply_text(response) == UNAVAILABLE
    assert counting_broker.calls == []
    assert "get_sales_summary" in caplog.text


def test_data_that_does_not_fit_gets_the_fallback_reply(
    el_guero: dict[UUID, str], fake_rpc: Any, counting_broker: Any, example: Any
) -> None:
    envelope = example("get_sales_summary").model_copy(update={"data": {"net_sales": "lots"}})
    fake_rpc.answers["get_sales_summary"] = envelope
    response = answer(
        _text(el_guero, "cuánto vendí ayer"),
        locations=el_guero,
        rpc=fake_rpc,
        broker=counting_broker,
    )
    assert response.route == "fallback"
    assert _reply_text(response) == UNAVAILABLE


def test_the_stub_broker_answers_fallback(el_guero: dict[UUID, str]) -> None:
    response = StubBroker()(_text(el_guero, "¿qué vino me recomiendas?"), el_guero)
    assert response.route == "fallback"
    assert _reply_text(response).startswith("Todavía no sé responder eso.")


def test_the_template_path_loads_no_llm_sdk() -> None:
    # Agno is installed in the workspace; MR-27 will import it inside mermia_api.agent
    code = (
        "import sys, mermia_api.agent\n"
        "sdks = {'agno', 'openai', 'anthropic', 'google'}\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] in sdks)\n"
        "assert not loaded, loaded\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_no_data_on_a_comparison_names_the_weeks(
    el_guero: dict[UUID, str], fake_rpc: Any, counting_broker: Any
) -> None:
    fake_rpc.answers["compare_periods"] = _error("no_data")
    response = answer(
        _text(el_guero, "ventas de la semana pasada vs la anterior"),
        locations=el_guero,
        rpc=fake_rpc,
        broker=counting_broker,
    )
    assert response.route == "template"
    assert _reply_text(response) == "No tengo datos completos para comparar esas semanas."


def test_no_data_without_a_period(
    el_guero: dict[UUID, str], fake_rpc: Any, counting_broker: Any
) -> None:
    fake_rpc.answers["get_data_status"] = _error("no_data")
    response = answer(
        _text(el_guero, "¿ya están al día mis datos?"),
        locations=el_guero,
        rpc=fake_rpc,
        broker=counting_broker,
    )
    assert response.route == "template"
    assert _reply_text(response) == "Todavía no tengo datos."
