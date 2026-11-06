"""MR-27: a burst of texts in one chat is one question and one answer (spec: Grouping)."""

import logging
from collections.abc import Callable
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest

from mermia_api.agent.grouping import GROUP_WINDOW, Grouper
from mermia_contracts.agent import AgentRequest, AgentResponse, TextMsg

TENANT, USER = uuid4(), uuid4()


class FakeTimer:
    """threading.Timer's shape; a test fires it by hand."""

    made: ClassVar[list["FakeTimer"]] = []

    def __init__(self, interval: float, function: Callable[[], None]) -> None:
        self.interval, self.function, self.cancelled = interval, function, False
        FakeTimer.made.append(self)

    def start(self) -> None: ...

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.function()


class Later:
    """A spawn that holds work until the test runs it, to see what happens meanwhile."""

    def __init__(self) -> None:
        self.waiting: list[Callable[[], None]] = []

    def __call__(self, work: Callable[[], None]) -> None:
        self.waiting.append(work)

    def run(self) -> None:
        self.waiting.pop(0)()


def _request(input: dict[str, Any], user: UUID = USER) -> AgentRequest:
    return AgentRequest.model_validate(
        {
            "tenant_id": str(TENANT),
            "user_id": str(user),
            "location_ids": [],
            "channel": "whatsapp",
            "conversation_id": str(uuid4()),
            "input": input,
        }
    )


def _text(text: str, user: UUID = USER) -> AgentRequest:
    return _request({"type": "text", "text": text}, user)


def _said(request: AgentRequest) -> str:
    return request.input.text if request.input.type == "text" else request.input.type


class Recorder:
    def __init__(self) -> None:
        self.asked: list[AgentRequest] = []
        self.sent: list[tuple[str, str]] = []

    def respond(self, request: AgentRequest) -> AgentResponse:
        self.asked.append(request)
        return AgentResponse(messages=[TextMsg(kind="text", text=_said(request))], route="haiku")

    def send(self, name: str) -> Callable[[AgentResponse], None]:
        return lambda response: self.sent.append((name, response.messages[0].text))  # type: ignore[union-attr]


@pytest.fixture(autouse=True)
def _timers() -> None:
    FakeTimer.made.clear()


def test_a_burst_of_texts_is_one_question_and_one_answer() -> None:
    r = Recorder()
    grouper = Grouper(r.respond, timer=FakeTimer, spawn=lambda work: work())
    for i, text in enumerate(["hola", "¿cuánto vendí", "ayer?"]):
        grouper.submit(_text(text), r.send(f"m{i}"))
    assert r.asked == []  # still within the window
    FakeTimer.made[-1].fire()

    assert [_said(q) for q in r.asked] == ["hola\n¿cuánto vendí\nayer?"]
    assert r.sent == [("m2", "hola\n¿cuánto vendí\nayer?")]  # on the last message's callback
    assert [t.interval for t in FakeTimer.made] == [GROUP_WINDOW] * 3 == [2.5] * 3
    assert all(t.cancelled for t in FakeTimer.made[:-1])  # each text restarts the window


def test_an_action_flushes_the_waiting_texts_first() -> None:
    r = Recorder()
    grouper = Grouper(r.respond, timer=FakeTimer, spawn=lambda work: work())
    grouper.submit(_text("¿cuánto vendí?"), r.send("text"))
    grouper.submit(_request({"type": "action", "action_id": "tpl:sales_yesterday"}), r.send("tap"))
    assert r.sent == [("text", "¿cuánto vendí?"), ("tap", "action")]
    FakeTimer.made[-1].fire()  # the cancelled window does nothing
    assert len(r.asked) == 2


def test_a_text_during_an_answer_is_answered_after_it() -> None:
    r = Recorder()
    later = Later()
    grouper = Grouper(r.respond, timer=FakeTimer, spawn=later)
    grouper.submit(_text("primero"), r.send("a"))
    FakeTimer.made[-1].fire()
    grouper.submit(_text("segundo"), r.send("b"))  # the first answer is still in flight
    FakeTimer.made[-1].fire()
    assert len(later.waiting) == 1  # one worker per chat
    later.run()
    assert r.sent == [("a", "primero"), ("b", "segundo")]


def test_two_chats_do_not_block_each_other() -> None:
    r = Recorder()
    later = Later()
    grouper = Grouper(r.respond, timer=FakeTimer, spawn=later)
    grouper.submit(_request({"type": "media", "raw_file_id": str(uuid4())}), r.send("a"))
    grouper.submit(_request({"type": "media", "raw_file_id": str(uuid4())}, uuid4()), r.send("b"))
    assert len(later.waiting) == 2


def test_a_bug_in_respond_is_logged_and_the_chat_goes_on(caplog: pytest.LogCaptureFixture) -> None:
    r = Recorder()
    calls = 0

    def flaky(request: AgentRequest) -> AgentResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("bug")
        return r.respond(request)

    later = Later()
    grouper = Grouper(flaky, timer=FakeTimer, spawn=later)
    grouper.submit(_text("uno"), r.send("a"))
    FakeTimer.made[-1].fire()
    grouper.submit(_text("dos"), r.send("b"))
    FakeTimer.made[-1].fire()
    with caplog.at_level(logging.ERROR):
        later.run()
    assert "bug" in caplog.text
    assert r.sent == [("b", "dos")]
