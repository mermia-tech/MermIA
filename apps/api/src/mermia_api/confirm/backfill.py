"""Recompute the older dish costs of an applied price change, after commit (MR-32, D3).

A tap recomputes today's dish costs inside the apply, so the reply shows fresh numbers. A price
that starts earlier also changes the days from its effective date (at most 400 days back) to
yesterday. The confirmation service (MR-37) calls `backfill_dish_costs` in the background once the
apply has committed.

Each call to `app.backfill_dish_costs` recomputes one chunk of at most `max_days` days, walking back
from yesterday, and commits on its own. So the per-tenant dish_cost_snapshot lock is held for a few
seconds at most and a concurrent tap's today-recompute waits little. Run it on a service-role
connection with no transaction open: inside an open transaction each chunk is only a savepoint, and
the lock is held until the caller commits.

It is idempotent: every chunk rewrites its days from the current prices and recipes, so a rerun
(after a crash, or twice by mistake) gives the same numbers.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

BACKFILL_CHUNK_DAYS = 7


@dataclass(frozen=True)
class BackfillResult:
    chunks: int  # transactions that recomputed days (0: nothing to do)
    snapshots: int  # dish_cost_snapshot rows written


def backfill_dish_costs(
    conn: psycopg.Connection[Any],
    pending_change_id: UUID,
    *,
    max_days: int = BACKFILL_CHUNK_DAYS,
) -> BackfillResult:
    """Recompute the days an applied price change left to the backfill, one chunk per commit.

    Raises the database error for an unknown change (P0002) or one that is not applied (55000).
    """
    chunks = 0
    snapshots = 0
    before: dt.date | None = None
    while True:
        chunk = _next_chunk(conn, pending_change_id, before, max_days)
        if chunk["from"] is None:
            return BackfillResult(chunks, snapshots)
        chunks += 1
        snapshots += int(chunk["snapshots"])
        if chunk["next_before"] is None:
            return BackfillResult(chunks, snapshots)
        following = dt.date.fromisoformat(chunk["next_before"])
        if before is not None and following >= before:  # never loop on the same days
            raise RuntimeError(f"backfill did not move back from {before} (got {following})")
        before = following


def _next_chunk(
    conn: psycopg.Connection[Any], pending_change_id: UUID, before: dt.date | None, max_days: int
) -> dict[str, Any]:
    with conn.transaction():
        row = conn.execute(
            "select app.backfill_dish_costs(%s, %s, %s)", (pending_change_id, before, max_days)
        ).fetchone()
    if row is None:  # a function call always returns one row
        raise RuntimeError("app.backfill_dish_costs returned no row")
    chunk: dict[str, Any] = row[0]
    return chunk
