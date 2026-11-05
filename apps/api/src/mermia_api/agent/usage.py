"""What the LLM broker records: one `llm_usage` row per LLM call (spec: Metering).

The store is injected: MemoryStore for tests and the eval, Postgres in the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4


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
    id: UUID = field(default_factory=uuid4)


class UsageStore(Protocol):
    def add(self, row: UsageRow) -> UUID: ...


class MemoryStore:
    def __init__(self) -> None:
        self.rows: list[UsageRow] = []

    def add(self, row: UsageRow) -> UUID:
        self.rows.append(row)
        return row.id
