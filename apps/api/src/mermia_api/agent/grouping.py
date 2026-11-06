"""The front door (spec: Grouping): a burst of texts in one chat becomes one question and one
answer; actions and media keep their place in line; one answer in flight per chat.

shortcut: grouping state lives in one process, so it works only with a single API instance and
a restart drops buffered messages; move it to Postgres (advisory lock + queue table) or
Procrastinate before running more than one instance.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from mermia_contracts.agent import AgentRequest, AgentResponse, TextInput

logger = logging.getLogger(__name__)

GROUP_WINDOW: Final = 2.5  # seconds of quiet that close a burst

Send = Callable[[AgentResponse], None]
_Key = tuple[UUID, UUID, str]


@dataclass
class _Chat:
    texts: list[AgentRequest] = field(default_factory=list)
    send: Send | None = None  # the last text's callback answers the group
    timer: Any = None
    ready: deque[tuple[AgentRequest, Send]] = field(default_factory=deque)
    busy: bool = False


def _spawn(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


class Grouper:
    """`respond` must not raise (agent.respond catches everything); if it does anyway, the bug
    is logged, since the grouper has no locations to build a menu."""

    def __init__(
        self,
        respond: Callable[[AgentRequest], AgentResponse],
        *,
        window: float = GROUP_WINDOW,
        timer: Callable[[float, Callable[[], None]], Any] = threading.Timer,
        spawn: Callable[[Callable[[], None]], None] = _spawn,
    ) -> None:
        self._respond = respond
        self._window = window
        self._timer = timer
        self._spawn = spawn
        self._lock = threading.Lock()
        self._chats: dict[_Key, _Chat] = {}

    def submit(self, request: AgentRequest, send: Send) -> None:
        key = (request.tenant_id, request.user_id, request.channel)
        with self._lock:
            chat = self._chats.setdefault(key, _Chat())
            if isinstance(request.input, TextInput):
                chat.texts.append(request)
                chat.send = send
                if chat.timer is not None:
                    chat.timer.cancel()
                chat.timer = timer = self._timer(self._window, lambda: self._close(key, timer))
                timer.start()
                return
            self._flush(chat)
            chat.ready.append((request, send))
            start = self._claim(chat)
        if start:
            self._spawn(lambda: self._work(key))

    def _close(self, key: _Key, timer: Any) -> None:
        with self._lock:
            chat = self._chats.get(key)
            if chat is None or chat.timer is not timer:  # a later text restarted the window
                return
            self._flush(chat)
            start = self._claim(chat)
        if start:
            self._spawn(lambda: self._work(key))

    def _flush(self, chat: _Chat) -> None:
        if chat.timer is not None:
            chat.timer.cancel()
            chat.timer = None
        if chat.texts and chat.send is not None:
            joined = "\n".join(r.input.text for r in chat.texts if isinstance(r.input, TextInput))
            last = chat.texts[-1]
            grouped = last.model_copy(update={"input": TextInput(type="text", text=joined)})
            chat.ready.append((grouped, chat.send))
        chat.texts, chat.send = [], None

    def _claim(self, chat: _Chat) -> bool:
        if chat.busy or not chat.ready:
            return False
        chat.busy = True
        return True

    def _work(self, key: _Key) -> None:
        """Answers the chat's ready groups in order, then lets the next worker start."""
        while True:
            with self._lock:
                chat = self._chats[key]
                if not chat.ready:
                    chat.busy = False
                    if not chat.texts:
                        del self._chats[key]
                    return
                request, send = chat.ready.popleft()
            try:
                send(self._respond(request))
            except Exception:
                logger.exception("grouped answer failed; the owner got no reply")
