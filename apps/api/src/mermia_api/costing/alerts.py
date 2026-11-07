"""Run the cost alert rules for a tenant (MR-33, 03 "Alert thresholds").

The rules live in SQL next to the costing engine (`app.evaluate_cost_alerts`, migration
20261108090300_cost_alerts.sql): price jumps and margin breaches become `public.alert` rows, urgent
ones marked for a same-day message (U3; sending is MR-37 / MR-38). Nothing is ever applied: the
evaluator writes no pending change, menu price or suggestion.

The backend calls `evaluate_cost_alerts` once a day per tenant, after the day's dish costs are
computed, and `evaluate_cost_alerts_range` to catch up on missed days (oldest first, so breach
episodes and urgency read the days in order). Urgency is judged against the business day the
run happens (`today`), never the day evaluated, so a catch-up over old days marks nothing urgent.
A margin breach is urgent only on a confirmed dish cost (owner decision 2026-11-07): one on an
estimated cost is recorded with its `confidence` for the weekly report, never sent the same day.
Run it on a service-role connection with no transaction open: each day commits on its own. It is
idempotent: a rerun adds nothing.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import psycopg

MAX_RANGE_DAYS = 400  # as app.compute_dish_costs


def evaluate_cost_alerts(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    on_date: dt.date,
    today: dt.date | None = None,
) -> int:
    """Write the tenant's alerts for one business day; return how many were added.

    `today` is the day the run happens; None means the tenant's business today.
    """
    with conn.transaction():
        row = conn.execute(
            "select app.evaluate_cost_alerts(%s, %s, %s)", (tenant_id, on_date, today)
        ).fetchone()
    if row is None:  # a function call always returns one row
        raise RuntimeError("app.evaluate_cost_alerts returned no row")
    return int(row[0])


def tenant_today(conn: psycopg.Connection[Any], tenant_id: UUID) -> dt.date:
    """The tenant's business day today, as the database sees it.

    Read in its own transaction: a bare execute would leave one open, so every later day of a
    range would run as a savepoint inside it and nothing would commit until the end.
    """
    with conn.transaction():
        row = conn.execute("select app.tenant_today(%s)", (tenant_id,)).fetchone()
    if row is None or row[0] is None:  # a function call always returns one row
        raise RuntimeError("app.tenant_today returned no day")
    day: dt.date = row[0]
    return day


def evaluate_cost_alerts_range(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    start: dt.date,
    end: dt.date,
    today: dt.date | None = None,
) -> int:
    """Evaluate every day of [start, end], oldest first; return how many alerts were added.

    Every day is judged against one `today` (None: the tenant's business today, read once before
    the first day), so a catch-up that runs past midnight does not change its mind halfway.
    """
    if end < start:
        raise ValueError(f"invalid range {start} .. {end}")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise ValueError(f"at most {MAX_RANGE_DAYS} days ({start} .. {end})")
    run_day = today if today is not None else tenant_today(conn, tenant_id)
    days = (start + dt.timedelta(days=n) for n in range((end - start).days + 1))
    return sum(evaluate_cost_alerts(conn, tenant_id, day, run_day) for day in days)
