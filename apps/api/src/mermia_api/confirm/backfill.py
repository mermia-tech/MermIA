"""Recompute the older dish costs of an applied price change, after commit (MR-32, D3).

A tap recomputes today's dish costs inside the apply, so the reply shows fresh numbers. A price
that starts earlier also changes the days from its effective date (at most 400 days back) to
yesterday. The apply records those days in `public.dish_cost_backfill`, in the same commit. The
confirmation service (MR-37) calls `backfill_dish_costs` in the background once the apply has
committed, and `resume_unfinished_backfills` on startup or periodically, so a backfill cut short by
a crash or a deploy is finished later.

Each call to `app.backfill_dish_costs` recomputes one chunk of at most `max_days` days, walking back
from the record's `next_before`, moves the record and commits on its own. So the per-tenant
dish_cost_snapshot lock is held for a few seconds at most and a concurrent tap's today-recompute
waits little. Run it on a service-role connection with no transaction open: inside an open
transaction each chunk is only a savepoint, and the lock is held until the caller commits.

It is idempotent: a rerun resumes from the record (a finished backfill does nothing), and every
chunk rewrites its days from the current prices and recipes.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

BACKFILL_CHUNK_DAYS = 7
RESUME_BATCH = 100

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    chunks: int  # transactions that recomputed days (0: nothing to do)
    snapshots: int  # dish_cost_snapshot rows written


@dataclass(frozen=True)
class ResumeResult:
    done: dict[UUID, BackfillResult]  # backfills run to the end by this call
    failed: dict[UUID, str]  # backfills that raised, with the error; they stay unfinished


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
    previous: dt.date | None = None
    while True:
        chunk = _next_chunk(conn, pending_change_id, max_days)
        if chunk["from"] is None:
            return BackfillResult(chunks, snapshots)
        chunks += 1
        snapshots += int(chunk["snapshots"])
        if chunk["next_before"] is None:
            return BackfillResult(chunks, snapshots)
        following = dt.date.fromisoformat(chunk["next_before"])
        if previous is not None and following >= previous:  # never loop on the same days
            raise RuntimeError(f"backfill did not move back from {previous} (got {following})")
        previous = following


def unfinished_backfills(conn: psycopg.Connection[Any], *, limit: int = RESUME_BATCH) -> list[UUID]:
    """The pending changes whose backfill is not done, oldest first."""
    with conn.transaction():
        rows = conn.execute(
            "select pending_change_id from public.dish_cost_backfill where done_at is null "
            "order by created_at, pending_change_id limit %s",
            (limit,),
        ).fetchall()
    return [UUID(str(row[0])) for row in rows]


def resume_unfinished_backfills(
    conn: psycopg.Connection[Any],
    *,
    limit: int = RESUME_BATCH,
    max_days: int = BACKFILL_CHUNK_DAYS,
) -> ResumeResult:
    """Finish up to `limit` unfinished backfills, oldest first.

    A backfill that raises a database error is logged and reported in `failed` (its record keeps
    the last committed chunk), and the others go on. Operational errors (a lost connection, a
    deadlock, a lock timeout) are raised: the whole sweep is retried later.
    """
    done: dict[UUID, BackfillResult] = {}
    failed: dict[UUID, str] = {}
    for change in unfinished_backfills(conn, limit=limit):
        try:
            done[change] = backfill_dish_costs(conn, change, max_days=max_days)
        except psycopg.OperationalError:
            raise
        except psycopg.Error as error:
            log.exception("dish cost backfill failed for pending change %s", change)
            failed[change] = str(error)
    return ResumeResult(done=done, failed=failed)


def _next_chunk(
    conn: psycopg.Connection[Any], pending_change_id: UUID, max_days: int
) -> dict[str, Any]:
    with conn.transaction():
        row = conn.execute(
            "select app.backfill_dish_costs(%s, %s)", (pending_change_id, max_days)
        ).fetchone()
    if row is None:  # a function call always returns one row
        raise RuntimeError("app.backfill_dish_costs returned no row")
    chunk: dict[str, Any] = row[0]
    return chunk
