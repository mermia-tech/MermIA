"""What the LLM broker records and remembers: one `llm_usage` row per LLM call (spec: Metering)
and the last turns of each conversation (spec: Memory).

The store is injected: MemoryStore for tests and the eval, PgStore in the API. Both tables are
backend-only, so PgStore gets a privileged connection, never the one of the tool path.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from mermia_api.agent.templates import MEXICO_CITY
from mermia_api.agent.validator import Turn

MEMORY_TURNS: Final = 4
MEMORY_TTL: Final = timedelta(hours=2)


def fresh(turns: list[Turn], now: datetime) -> list[Turn]:
    """The stored turns, or none when the newest is older than MEMORY_TTL."""
    return turns if turns and now - turns[-1].ts <= MEMORY_TTL else []


@dataclass(frozen=True)
class UsageRow:
    """One LLM call, as `public.llm_usage` holds it. Tokens and cost are None when the call
    failed before the provider reported usage."""

    tenant_id: UUID
    user_id: UUID
    request_id: str  # shared by the rows of one question (a retry is not a second question)
    model: str
    latency_ms: int
    tool_calls: int
    input_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    validator_result: str | None = None  # pass, retry, retry_pass, reject; None: no reply
    error: str | None = None
    route: str = "haiku"  # the primary LLM route on every row, failures included (Q1)
    location_id: UUID | None = None  # a question can span locations
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID = field(default_factory=uuid4)


class UsageStore(Protocol):
    def add(self, row: UsageRow) -> UUID: ...

    def questions_today(self, tenant_id: UUID, day: date) -> int:
        """Distinct questions (request ids) on that Mexico City day."""
        ...

    def turns(self, tenant_id: UUID, user_id: UUID, channel: str) -> list[Turn]: ...

    def save_turns(
        self, tenant_id: UUID, user_id: UUID, channel: str, turns: Sequence[Turn]
    ) -> None:
        """Replace the conversation's turns with the last MEMORY_TURNS of `turns`."""
        ...


class MemoryStore:
    def __init__(self) -> None:
        self.rows: list[UsageRow] = []
        self.conversations: dict[tuple[UUID, UUID, str], list[Turn]] = {}

    def add(self, row: UsageRow) -> UUID:
        self.rows.append(row)
        return row.id

    def questions_today(self, tenant_id: UUID, day: date) -> int:
        return len(
            {
                r.request_id
                for r in self.rows
                if r.tenant_id == tenant_id and r.ts.astimezone(MEXICO_CITY).date() == day
            }
        )

    def turns(self, tenant_id: UUID, user_id: UUID, channel: str) -> list[Turn]:
        return list(self.conversations.get((tenant_id, user_id, channel), []))

    def save_turns(
        self, tenant_id: UUID, user_id: UUID, channel: str, turns: Sequence[Turn]
    ) -> None:
        self.conversations[(tenant_id, user_id, channel)] = list(turns[-MEMORY_TURNS:])


class PgStore:
    """`connect` opens a backend connection; leaving its block commits (psycopg's default)."""

    def __init__(
        self, connect: Callable[[], AbstractContextManager[psycopg.Connection[Any]]]
    ) -> None:
        self._connect = connect

    def add(self, row: UsageRow) -> UUID:
        with self._connect() as conn:
            conn.execute(
                "insert into public.llm_usage (id, tenant_id, location_id, user_id, ts,"
                " request_id, route, model, input_tokens, cache_read_tokens, cache_write_tokens,"
                " output_tokens, cost_usd, latency_ms, tool_calls, validator_result, error)"
                " values (%s, %s, %s, %s, %s, %s, %s::app.llm_route, %s, %s, %s, %s, %s, %s, %s,"
                " %s, %s, %s)",
                (
                    row.id,
                    row.tenant_id,
                    row.location_id,
                    row.user_id,
                    row.ts,
                    row.request_id,
                    row.route,
                    row.model,
                    row.input_tokens,
                    row.cache_read_tokens,
                    row.cache_write_tokens,
                    row.output_tokens,
                    row.cost_usd,
                    row.latency_ms,
                    row.tool_calls,
                    row.validator_result,
                    row.error,
                ),
            )
        return row.id

    def questions_today(self, tenant_id: UUID, day: date) -> int:
        with self._connect() as conn:
            found = conn.execute(
                "select count(distinct request_id) from public.llm_usage"
                " where tenant_id = %s and (ts at time zone %s)::date = %s",
                (tenant_id, MEXICO_CITY.key, day),
            ).fetchone()
        return int(found[0]) if found else 0

    def turns(self, tenant_id: UUID, user_id: UUID, channel: str) -> list[Turn]:
        with self._connect() as conn:
            found = conn.execute(
                "select last_turns from public.conversation"
                " where tenant_id = %s and user_id = %s and channel = %s::app.channel",
                (tenant_id, user_id, channel),
            ).fetchone()
        stored: list[dict[str, str]] = found[0] if found else []
        return [Turn(q=t["q"], a=t["a"], ts=datetime.fromisoformat(t["ts"])) for t in stored]

    def save_turns(
        self, tenant_id: UUID, user_id: UUID, channel: str, turns: Sequence[Turn]
    ) -> None:
        kept = [{"q": t.q, "a": t.a, "ts": t.ts.isoformat()} for t in turns[-MEMORY_TURNS:]]
        with self._connect() as conn:
            conn.execute(
                "insert into public.conversation (tenant_id, user_id, channel, last_turns)"
                " values (%s, %s, %s::app.channel, %s)"
                " on conflict (tenant_id, user_id, channel)"
                " do update set last_turns = excluded.last_turns",
                (tenant_id, user_id, channel, Jsonb(kept)),
            )
