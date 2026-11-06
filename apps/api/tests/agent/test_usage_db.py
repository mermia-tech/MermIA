"""MR-27: llm_usage rows and conversation turns in Postgres (spec: Metering, Memory)."""

import os
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from mermia_api.agent.usage import PgStore, UsageRow
from mermia_api.agent.validator import Turn

pytestmark = pytest.mark.db

TENANT = UUID("03299e41-28bd-5779-bcc6-0e5e76580fad")  # Taquería El Güero
OWNER = UUID("eb52f6ad-4d75-5b06-9881-9f68f4fb05a0")
CENTRO = UUID("705e8e51-376b-5785-adbb-405eff4e2a22")


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[Any]]:
    url = os.environ.get("MERMIA_DB_URL")
    if not url:
        pytest.skip("MERMIA_DB_URL is not set")
    with psycopg.connect(url) as c, c.transaction(force_rollback=True):
        yield c


@pytest.fixture
def store(conn: psycopg.Connection[Any]) -> PgStore:
    return PgStore(lambda: nullcontext(conn))


def _row(request_id: str, ts: datetime, **fields: Any) -> UsageRow:
    return UsageRow(
        tenant_id=TENANT,
        user_id=OWNER,
        request_id=request_id,
        model="openai:gpt-5.6-luna",
        latency_ms=1200,
        tool_calls=1,
        ts=ts,
        **fields,
    )


def test_a_row_round_trips_with_every_field(store: PgStore, conn: psycopg.Connection[Any]) -> None:
    ts = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)
    row = _row(
        "r1",
        ts,
        input_tokens=1000,
        cache_read_tokens=800,
        cache_write_tokens=0,
        output_tokens=50,
        cost_usd=Decimal("0.000136"),
        validator_result="pass",
        error=None,
        location_id=CENTRO,
    )
    assert store.add(row) == row.id
    got = conn.execute(
        "select tenant_id, user_id, request_id, route::text, model, input_tokens,"
        " cache_read_tokens, cache_write_tokens, output_tokens, cost_usd, latency_ms,"
        " tool_calls, validator_result, error, location_id, ts from public.llm_usage where id = %s",
        (row.id,),
    ).fetchone()
    assert got == (
        TENANT,
        OWNER,
        "r1",
        "haiku",
        "openai:gpt-5.6-luna",
        1000,
        800,
        0,
        50,
        Decimal("0.000136"),
        1200,
        1,
        "pass",
        None,
        CENTRO,
        ts,
    )


def test_a_retry_is_not_a_second_question(store: PgStore) -> None:
    ts = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)
    store.add(_row("q1", ts, validator_result="retry"))
    store.add(_row("q1", ts, validator_result="retry_pass"))
    store.add(_row("q2", ts, validator_result="pass"))
    assert store.questions_today(TENANT, date(2026, 11, 5)) == 2


def test_the_day_is_the_mexico_city_day(store: PgStore) -> None:
    late = datetime(2026, 11, 6, 5, 30, tzinfo=UTC)  # 23:30 on Nov 5 in Mexico City
    store.add(_row("q1", late))
    assert store.questions_today(TENANT, date(2026, 11, 5)) == 1
    assert store.questions_today(TENANT, date(2026, 11, 6)) == 0


def test_saving_turns_keeps_the_last_four(store: PgStore) -> None:
    start = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)
    turns = [Turn(q=f"q{i}", a=f"a{i}", ts=start + timedelta(minutes=i)) for i in range(5)]
    store.save_turns(TENANT, OWNER, "whatsapp", turns)
    assert store.turns(TENANT, OWNER, "whatsapp") == turns[1:]


def test_a_second_save_updates_the_conversation(
    store: PgStore, conn: psycopg.Connection[Any]
) -> None:
    ts = datetime(2026, 11, 5, 16, 0, tzinfo=UTC)
    store.save_turns(TENANT, OWNER, "whatsapp", [Turn(q="a", a="b", ts=ts)])
    store.save_turns(TENANT, OWNER, "whatsapp", [Turn(q="c", a="d", ts=ts)])
    count = conn.execute(
        "select count(*) from public.conversation where tenant_id = %s and user_id = %s"
        " and channel = 'whatsapp'",
        (TENANT, OWNER),
    ).fetchone()
    assert count == (1,)
    assert store.turns(TENANT, OWNER, "whatsapp") == [Turn(q="c", a="d", ts=ts)]


def test_no_conversation_means_no_turns(store: PgStore) -> None:
    assert store.turns(TENANT, uuid4(), "whatsapp") == []
