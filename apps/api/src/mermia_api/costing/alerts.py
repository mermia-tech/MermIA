"""Run the cost alert rules for a tenant (MR-33, 03 "Alert thresholds").

The rules live in SQL next to the costing engine (`app.evaluate_cost_alerts`, migration
20261106100000_cost_alerts.sql): price jumps and margin breaches become `public.alert` rows, urgent
ones marked for a same-day message (U3; sending is MR-37 / MR-38). Nothing is ever applied: the
evaluator writes no pending change, menu price or suggestion.

The backend calls `evaluate_cost_alerts` once a day per tenant, after the day's dish costs are
computed, and `evaluate_cost_alerts_range` to catch up on missed days (oldest first, so breach
episodes and urgency read the days in order). Run it on a service-role connection with no
transaction open: each day commits on its own. It is idempotent: a rerun adds nothing.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import psycopg

MAX_RANGE_DAYS = 400  # as app.compute_dish_costs


def evaluate_cost_alerts(conn: psycopg.Connection[Any], tenant_id: UUID, on_date: dt.date) -> int:
    """Write the tenant's alerts for one business day; return how many were added."""
    with conn.transaction():
        row = conn.execute(
            "select app.evaluate_cost_alerts(%s, %s)", (tenant_id, on_date)
        ).fetchone()
    if row is None:  # a function call always returns one row
        raise RuntimeError("app.evaluate_cost_alerts returned no row")
    return int(row[0])


def evaluate_cost_alerts_range(
    conn: psycopg.Connection[Any], tenant_id: UUID, start: dt.date, end: dt.date
) -> int:
    """Evaluate every day of [start, end], oldest first; return how many alerts were added."""
    if end < start:
        raise ValueError(f"invalid range {start} .. {end}")
    if (end - start).days >= MAX_RANGE_DAYS:
        raise ValueError(f"at most {MAX_RANGE_DAYS} days ({start} .. {end})")
    days = (start + dt.timedelta(days=n) for n in range((end - start).days + 1))
    return sum(evaluate_cost_alerts(conn, tenant_id, day) for day in days)
