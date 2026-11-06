"""MR-27: the LLM broker (spec: Pipeline, Metering). The model is scripted; no network."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from agno.models.message import Message
from agno.run.base import RunStatus

from mermia_api.agent.llm import PRICES, cost_usd
from mermia_api.agent.llm_broker import DAILY_QUESTIONS, MAX_OUTPUT_TOKENS, LlmBroker
from mermia_api.agent.prompt import STATIC_PREFIX
from mermia_api.agent.usage import MemoryStore, UsageRow
from mermia_api.agent.validator import Turn
from mermia_contracts.agent import AgentRequest, AgentResponse, ChoicesMsg, TextMsg
from mermia_contracts.db.models import MemberRole

MODEL = "openai:gpt-5.6-luna"
NOW = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)  # 09:00 in Mexico City
CENTRO = "705e8e51-376b-5785-adbb-405eff4e2a22"
SALES_ARGS = {"period": "last_week", "location_id": CENTRO}
UNAVAILABLE = "No pude responder eso ahora. Prueba con una de estas:"
CLEAN = "La semana pasada Centro vendió $184,320.50 con 648 tickets."


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


def _text(locations: dict[UUID, str], text: str = "¿cuánto vendió Centro?") -> AgentRequest:
    return _request(locations, {"type": "text", "text": text})


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def broker(agents: Any, store: MemoryStore) -> LlmBroker:
    return LlmBroker(
        MODEL, store, role_of=lambda _: MemberRole.owner, agent_factory=agents, clock=lambda: NOW
    )


def _is_menu(response: AgentResponse) -> bool:
    (message,) = response.messages
    return isinstance(message, ChoicesMsg) and response.route == "fallback"


def test_a_clean_reply_is_sent_with_one_pass_row(
    broker: LlmBroker, agents: Any, reply: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    agents.script = [reply(CLEAN, calls=[("get_sales_summary", SALES_ARGS)])]
    request = _text(el_guero)
    response = broker(request, el_guero, fake_rpc)

    assert response.route == "haiku"
    assert response.messages == [TextMsg(kind="text", text=CLEAN)]
    (row,) = store.rows
    assert response.usage_id == row.id
    assert (row.tenant_id, row.user_id, row.location_id) == (
        request.tenant_id,
        request.user_id,
        None,
    )
    assert (row.route, row.model, row.validator_result, row.error) == ("haiku", MODEL, "pass", None)
    assert (row.input_tokens, row.cache_read_tokens, row.output_tokens) == (1000, 800, 50)
    assert row.tool_calls == 1 and row.latency_ms is not None and row.request_id
    expected = cost_usd(MODEL, PRICES[MODEL], input=1000, cached=800, output=50, reasoning=0)
    assert isinstance(row.cost_usd, Decimal) and row.cost_usd == expected
    assert fake_rpc.calls == [("get_sales_summary", SALES_ARGS)]


def test_the_agent_gets_the_static_prefix_the_caps_and_the_twelve_tools(
    broker: LlmBroker, agents: Any, reply: Any, el_guero: Any, fake_rpc: Any
) -> None:
    agents.script = [reply("Hola.")]
    broker(_text(el_guero), el_guero, fake_rpc)

    (built,) = agents.built
    assert built["instructions"] == STATIC_PREFIX
    assert built["tool_call_limit"] == 4  # Agno refuses a 5th call and the model must answer
    assert built["model"].max_output_tokens == MAX_OUTPUT_TOKENS == 400
    assert len(built["tools"]) == 12


def test_the_tail_and_the_question_reach_the_model(
    broker: LlmBroker, agents: Any, reply: Any, el_guero: Any, fake_rpc: Any
) -> None:
    agents.script = [reply("Hola.")]
    broker(_text(el_guero, "¿qué vendí más?"), el_guero, fake_rpc)

    (messages,) = agents.inputs
    assert all(isinstance(m, Message) and m.role == "user" for m in messages)
    tail, question = (m.content for m in messages)
    assert "Hoy es lunes 12 de octubre de 2026 (2026-10-12)" in tail and "dueño" in tail
    assert f"Centro ({CENTRO})" in tail
    assert question == "¿qué vendí más?"


@pytest.mark.parametrize(
    "input",
    [
        {"type": "action", "action_id": f"pc:{uuid4()}:approve"},
        {"type": "action", "action_id": "something:else"},
        {"type": "media", "raw_file_id": str(uuid4())},
    ],
)
def test_only_text_reaches_the_llm(
    broker: LlmBroker,
    agents: Any,
    store: MemoryStore,
    el_guero: Any,
    fake_rpc: Any,
    input: dict[str, Any],
) -> None:
    response = broker(_request(el_guero, input), el_guero, fake_rpc)
    assert _is_menu(response)
    assert agents.built == [] and store.rows == []


@pytest.mark.parametrize(
    "step",
    [
        RuntimeError("boom"),
        "error status",
    ],
)
def test_a_provider_failure_gets_the_menu_and_a_row_with_the_error(
    broker: LlmBroker,
    agents: Any,
    reply: Any,
    store: MemoryStore,
    el_guero: Any,
    fake_rpc: Any,
    step: Any,
) -> None:
    if step == "error status":  # Agno returns the provider error as the content
        step = reply("Error code: 503", status=RunStatus.error)
    agents.script = [step]
    response = broker(_text(el_guero), el_guero, fake_rpc)

    assert _is_menu(response)
    assert response.messages[0].text == UNAVAILABLE  # type: ignore[union-attr]
    (row,) = store.rows
    assert row.error and row.validator_result is None and row.route == "haiku"
    assert response.usage_id == row.id
    assert "503" not in str(response.messages)


@pytest.mark.parametrize(
    "kwargs", [{"text": "  "}, {"text": "La semana pasada", "output_tokens": 400}]
)
def test_an_empty_or_incomplete_reply_gets_the_menu(
    broker: LlmBroker,
    agents: Any,
    reply: Any,
    store: MemoryStore,
    el_guero: Any,
    fake_rpc: Any,
    kwargs: dict[str, Any],
) -> None:
    agents.script = [reply(**kwargs)]
    response = broker(_text(el_guero), el_guero, fake_rpc)
    assert _is_menu(response)
    assert response.messages[0].text == UNAVAILABLE  # type: ignore[union-attr]
    (row,) = store.rows
    assert row.error and row.validator_result is None


def test_invalid_tool_arguments_go_back_to_the_model_and_no_rpc_runs(
    broker: LlmBroker, agents: Any, reply: Any, el_guero: Any, fake_rpc: Any
) -> None:
    agents.script = [reply("¿De qué periodo?", calls=[("get_sales_summary", {"period": "ayer"})])]
    broker(_text(el_guero), el_guero, fake_rpc)
    assert fake_rpc.calls == []


def test_tool_results_go_to_the_model_as_text(
    broker: LlmBroker, agents: Any, reply: Any, el_guero: Any, fake_rpc: Any
) -> None:
    seen: list[str] = []

    def step(tools: dict[str, Any]) -> Any:
        seen.append(tools["get_sales_summary"].entrypoint(**SALES_ARGS))
        seen.append(tools["get_sales_summary"].entrypoint(period="ayer"))
        seen.append(tools["propose_change"].entrypoint(kind="x"))
        return reply("Hola.")(tools)

    agents.script = [step]
    broker(_text(el_guero), el_guero, fake_rpc)
    ok, invalid, pending = seen
    assert json.loads(ok)["data"]["net_sales"]["text"] == "$184,320.50"
    assert "period" in invalid  # the validation error names the bad field
    assert json.loads(pending) == {"status": "pending_approval"}
    assert [name for name, _ in fake_rpc.calls] == ["get_sales_summary"]  # propose writes nothing


def test_an_rpc_exception_goes_back_to_the_model_and_the_run_goes_on(
    broker: LlmBroker, agents: Any, reply: Any, el_guero: Any, fake_rpc: Any
) -> None:
    fake_rpc.answers["get_sales_summary"] = TimeoutError("rpc timeout")
    seen: list[str] = []

    def step(tools: dict[str, Any]) -> Any:
        seen.append(tools["get_sales_summary"].entrypoint(**SALES_ARGS))
        return reply("No pude consultar las ventas ahora.")(tools)

    agents.script = [step]
    response = broker(_text(el_guero), el_guero, fake_rpc)
    assert "rpc timeout" in seen[0]
    assert response.route == "haiku"


def test_each_request_runs_its_tools_on_its_own_rpc(
    broker: LlmBroker, agents: Any, reply: Any, el_guero: Any, fake_rpc: Any, other_rpc: Any
) -> None:
    first, second = fake_rpc, other_rpc
    agents.script = [
        reply(CLEAN, calls=[("get_sales_summary", SALES_ARGS)]),
        reply(CLEAN, calls=[("get_sales_summary", SALES_ARGS)]),
    ]
    broker(_text(el_guero), el_guero, first)
    broker(_text(el_guero), el_guero, second)
    assert len(first.calls) == len(second.calls) == 1


INVENTED = "Vendiste $99,999."


def test_an_invented_figure_gets_one_silent_retry(
    broker: LlmBroker, agents: Any, reply: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    from types import SimpleNamespace

    def first(tools: dict[str, Any]) -> Any:
        out = reply(INVENTED, calls=[("get_sales_summary", SALES_ARGS)])(tools)
        system = Message(role="system", content=STATIC_PREFIX)
        said = Message(role="assistant", content=INVENTED)
        return SimpleNamespace(**{**vars(out), "messages": [system, said]})

    agents.script = [first, reply(CLEAN)]  # the retry needs no new tool call
    response = broker(_text(el_guero), el_guero, fake_rpc)

    assert response.messages == [TextMsg(kind="text", text=CLEAN)] and response.route == "haiku"
    assert [r.validator_result for r in store.rows] == ["retry", "retry_pass"]
    assert store.rows[0].request_id == store.rows[1].request_id
    assert response.usage_id == store.rows[1].id
    *earlier, correction = agents.inputs[1]
    assert [m.role for m in earlier] == ["assistant"]  # the first run, without its system message
    assert correction.role == "user" and "99999" in correction.content
    assert "no lo menciones" in correction.content  # the owner never sees the correction
    assert len(fake_rpc.calls) == 1


def test_an_invented_figure_twice_gets_the_menu(
    broker: LlmBroker, agents: Any, reply: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    invented = reply(INVENTED, calls=[("get_sales_summary", SALES_ARGS)])
    agents.script = [invented, invented]
    response = broker(_text(el_guero), el_guero, fake_rpc)

    assert _is_menu(response)
    (message,) = response.messages
    assert message.text == "No pude confirmar esa cifra. Prueba con una de estas:"  # type: ignore[union-attr]
    assert "99,999" not in str(response.messages)
    assert [r.validator_result for r in store.rows] == ["retry", "reject"]
    assert response.usage_id == store.rows[1].id


def test_a_provider_failure_on_the_retry_gets_the_menu(
    broker: LlmBroker, agents: Any, reply: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    agents.script = [reply(INVENTED), RuntimeError("503")]
    response = broker(_text(el_guero), el_guero, fake_rpc)

    assert _is_menu(response)
    assert [(r.validator_result, bool(r.error)) for r in store.rows] == [
        ("retry", False),
        (None, True),
    ]


# Daily cap and memory.


def _seed_questions(store: MemoryStore, request: AgentRequest, n: int) -> None:
    for i in range(n):
        store.add(
            UsageRow(
                tenant_id=request.tenant_id,
                user_id=uuid4(),  # the cap is per tenant, not per user
                request_id=f"q{i}",
                model=MODEL,
                latency_ms=1,
                tool_calls=0,
                ts=NOW,
            )
        )


def test_the_61st_question_of_the_day_gets_the_menu_without_a_model_call(
    broker: LlmBroker, agents: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    request = _text(el_guero)
    _seed_questions(store, request, DAILY_QUESTIONS)
    response = broker(request, el_guero, fake_rpc)
    assert _is_menu(response) and agents.built == []
    assert response.messages[0].text == (  # type: ignore[union-attr]
        "Por hoy ya no puedo responder preguntas abiertas. Prueba con una de estas:"
    )
    assert len(store.rows) == DAILY_QUESTIONS == 60


def test_the_60th_question_goes_through(
    broker: LlmBroker, agents: Any, reply: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    request = _text(el_guero)
    _seed_questions(store, request, DAILY_QUESTIONS - 1)
    agents.script = [reply("Hola.")]
    assert broker(request, el_guero, fake_rpc).route == "haiku"


def test_a_follow_up_sees_the_earlier_turn(
    broker: LlmBroker, agents: Any, reply: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    request = _text(el_guero, "¿y Polanco?")
    earlier = Turn(q="¿cuánto vendió Centro?", a=CLEAN, ts=NOW - timedelta(minutes=10))
    store.save_turns(request.tenant_id, request.user_id, "whatsapp", [earlier])
    agents.script = [reply("Hola.")]
    broker(request, el_guero, fake_rpc)

    (messages,) = agents.inputs
    assert [(m.role, m.content) for m in messages[1:]] == [
        ("user", "¿cuánto vendió Centro?"),
        ("assistant", CLEAN),
        ("user", "¿y Polanco?"),
    ]


def test_memory_expires_after_two_hours(
    broker: LlmBroker, agents: Any, reply: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    request = _text(el_guero, "¿y Polanco?")
    old = Turn(q="¿cuánto vendió Centro?", a=CLEAN, ts=NOW - timedelta(hours=2, minutes=1))
    store.save_turns(request.tenant_id, request.user_id, "whatsapp", [old])
    agents.script = [reply("Hola.")]
    broker(request, el_guero, fake_rpc)
    (messages,) = agents.inputs
    assert len(messages) == 2  # the tail and the question


def test_a_figure_from_an_earlier_reply_passes_the_validator(
    broker: LlmBroker, agents: Any, reply: Any, store: MemoryStore, el_guero: Any, fake_rpc: Any
) -> None:
    request = _text(el_guero, "¿y eso es bueno?")
    earlier = Turn(q="¿cuánto vendió Centro?", a=CLEAN, ts=NOW - timedelta(minutes=10))
    store.save_turns(request.tenant_id, request.user_id, "whatsapp", [earlier])
    agents.script = [reply("Los $184,320.50 de Centro son la venta de la semana pasada.")]
    response = broker(request, el_guero, fake_rpc)
    assert response.route == "haiku"
    assert [r.validator_result for r in store.rows] == ["pass"]
