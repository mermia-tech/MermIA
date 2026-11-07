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
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

BACKFILL_CHUNK_DAYS = 7
RESUME_BATCH = 100
MAX_BACKFILL_ATTEMPTS = 5  # a backfill that failed this many sweeps is given up

# Errors a later sweep can expect to get past: a lost or refused connection (class 08), deadlock,
# serialization failure, lock not available, server shutdown or startup, too many connections,
# disk full (53100) and I/O error (58030). 53200 (out of memory) is counted: it can be this query.
# Anything else (e.g. 54001 recipe too deep, 57014, 55000) fails the same way every time: counted.
TRANSIENT_SQLSTATE_CLASSES = frozenset({"08"})
TRANSIENT_SQLSTATES = frozenset(
    {"40P01", "40001", "55P03", "57P01", "57P03", "53300", "53100", "58030"}
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    chunks: int  # transactions that recomputed days (0: nothing to do)
    snapshots: int  # dish_cost_snapshot rows written


@dataclass(frozen=True)
class UnfinishedBackfill:
    pending_change_id: UUID
    attempts: int  # sweeps that failed for this backfill
    last_error: str | None  # SQLSTATE and exception class of the last failure

    @property
    def is_given_up(self) -> bool:
        """The sweep no longer retries it: an operator has to look."""
        return self.attempts >= MAX_BACKFILL_ATTEMPTS


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


def unfinished_backfills(
    conn: psycopg.Connection[Any],
    *,
    limit: int = RESUME_BATCH,
    include_given_up: bool = True,
    only: Collection[UUID] | None = None,
) -> list[UnfinishedBackfill]:
    """The backfills that are not done, fewest failures first, then oldest.

    Given-up ones (attempts >= MAX_BACKFILL_ATTEMPTS) are listed, marked `is_given_up`, unless
    `include_given_up` is false; the sweep leaves them out. `only` (a test seam) restricts the list
    to those pending changes.
    """
    ids = None if only is None else list(only)
    with conn.transaction():
        rows = conn.execute(
            "select pending_change_id, attempts, last_error from public.dish_cost_backfill "
            "where done_at is null and (%s or attempts < %s) "
            "and (%s::uuid[] is null or pending_change_id = any(%s::uuid[])) "
            "order by attempts, created_at, pending_change_id limit %s",
            (include_given_up, MAX_BACKFILL_ATTEMPTS, ids, ids, limit),
        ).fetchall()
    return [UnfinishedBackfill(UUID(str(r[0])), int(r[1]), r[2]) for r in rows]


def resume_unfinished_backfills(
    conn: psycopg.Connection[Any],
    *,
    limit: int = RESUME_BATCH,
    max_days: int = BACKFILL_CHUNK_DAYS,
    only: Collection[UUID] | None = None,
) -> ResumeResult:
    """Finish up to `limit` unfinished backfills, fewest failures first, then oldest.

    A backfill that raises a database error is logged and reported in `failed` (its record keeps
    the last committed chunk), its `attempts` goes up and `last_error` is stored, and the others
    go on. After MAX_BACKFILL_ATTEMPTS failures the sweep stops picking it (logged once, when it
    is given up). Transient errors (a lost connection, a deadlock, a lock timeout; see
    TRANSIENT_SQLSTATES) are raised without counting an attempt: the whole sweep is retried later.
    """
    done: dict[UUID, BackfillResult] = {}
    failed: dict[UUID, str] = {}
    for backfill in unfinished_backfills(conn, limit=limit, include_given_up=False, only=only):
        change = backfill.pending_change_id
        try:
            done[change] = backfill_dish_costs(conn, change, max_days=max_days)
        except psycopg.Error as error:
            if is_transient(conn, error):
                raise
            log.exception("dish cost backfill failed for pending change %s", change)
            failed[change] = str(error)
            _record_failure(conn, change, error)
        except Exception as error:  # a bug in a backfill must not stall the sweep at attempts 0
            log.exception("dish cost backfill crashed for pending change %s", change)
            failed[change] = str(error)
            _record_failure(conn, change, error)
    return ResumeResult(done=done, failed=failed)


def is_transient(conn: psycopg.Connection[Any], error: psycopg.Error) -> bool:
    """A failure of the connection or a passing condition: retry the sweep, count nothing."""
    if conn.broken or conn.closed:
        return True
    state = error.sqlstate
    if state is None:
        return False
    return state in TRANSIENT_SQLSTATES or state[:2] in TRANSIENT_SQLSTATE_CLASSES


def failure_reason(error: Exception) -> str:
    """The SQLSTATE and exception class of a failure, never its message (it can carry values)."""
    state = error.sqlstate if isinstance(error, psycopg.Error) else None
    return f"{state or 'unknown'} {type(error).__name__}"


def _record_failure(conn: psycopg.Connection[Any], change: UUID, error: Exception) -> None:
    """Count the failed attempt in its own transaction. The message is not stored: it can carry
    payload values, so only the SQLSTATE and the exception class are."""
    reason = failure_reason(error)
    with conn.transaction():
        row = conn.execute(
            "update public.dish_cost_backfill set attempts = attempts + 1, last_error = %s "
            "where pending_change_id = %s and done_at is null returning attempts",
            (reason, change),
        ).fetchone()
    if row is not None and row[0] == MAX_BACKFILL_ATTEMPTS:
        log.error(
            "dish cost backfill for pending change %s given up after %s attempts (last error %s)",
            change,
            MAX_BACKFILL_ATTEMPTS,
            reason,
        )


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
