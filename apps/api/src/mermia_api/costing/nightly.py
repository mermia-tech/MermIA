"""The nightly dish-cost job (MR-100): every tenant's dish costs for each location's own today.

Only approval taps and their backfills write `dish_cost_snapshot`. A day nobody approves anything
would have no costs, so margins, food cost %, alerts and the weekly report go blank for it. This job
fills, for every tenant in `public.tenant`, every active dish's row at each location's own business
today, and a short catch-up window before it (`days`, default 2: yesterday and today, at most 400).

- Insert only (`app.fill_dish_costs`): a row that exists keeps its id and values, a rerun writes
  nothing. The rows it writes are the ones `app.compute_dish_costs` writes for those days.
- Tenants one at a time. Each tenant's window is cut into chunks of at most 31 days, newest first,
  one transaction each: the per-tenant lock is held for one chunk only.
- A tenant that fails is logged and reported in `failed` (SQLSTATE and exception class only, as
  MR-87's backfill sweep), tagged transient or not with the sweep's split; the run goes on with the
  next tenant. A broken connection is raised: nothing else can run. Every tenant is retried on the
  next run (the job is idempotent).

Run it on a service-role connection with no transaction open (inside an open transaction each
chunk is only a savepoint and the locks are held until the caller commits).

CLI (connects with MERMIA_DB_URL or --db-url; exit 0 done, 1 a tenant failed, 2 bad arguments):

    uv run python -m mermia_api.costing.nightly [--days N] [--today YYYY-MM-DD]

Not scheduled yet (no Procrastinate). Hourly is cheap (a rerun only checks for missing rows) and
picks up each time zone soon after its midnight and each new dish soon after an upload:

    5 * * * * cd /app && uv run python -m mermia_api.costing.nightly >> /var/log/nightly.log 2>&1
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import time
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

from mermia_api.admin.cli import db_label
from mermia_api.confirm.backfill import failure_reason, is_transient

DEFAULT_DAYS = 2  # yesterday and today
MAX_DAYS = 400  # the engine's longest range
MAX_CHUNK_DAYS = 31  # days per transaction (app.fill_dish_costs refuses more)
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantRun:
    from_date: dt.date | None  # None: a tenant without locations, nothing to cost
    to_date: dt.date | None
    chunks: int  # transactions run
    snapshots: int  # dish_cost_snapshot rows written
    seconds: float


@dataclass(frozen=True)
class TenantFailure:
    reason: str  # SQLSTATE and exception class, never the message
    is_transient: bool  # a passing condition (deadlock, lock timeout): the next run should pass


@dataclass(frozen=True)
class NightlyResult:
    done: dict[UUID, TenantRun]
    failed: dict[UUID, TenantFailure]

    @property
    def snapshots(self) -> int:
        return sum(run.snapshots for run in self.done.values())


def run_nightly_dish_costs(
    conn: psycopg.Connection[Any],
    *,
    today: dt.date | None = None,
    days: int = DEFAULT_DAYS,
    only: Collection[UUID] | None = None,
) -> NightlyResult:
    """Fill every tenant's dish costs over the last `days` days up to each location's today.

    `today` replaces every location's business today (app.today), e.g. to rerun a missed night.
    `only` narrows the tenants read from `public.tenant` (ids not there are ignored).
    """
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}, got {days}")
    done: dict[UUID, TenantRun] = {}
    failed: dict[UUID, TenantFailure] = {}
    for tenant in _tenants(conn, only):
        try:
            done[tenant] = _run_tenant(conn, tenant, today, days)
        except psycopg.Error as error:
            if conn.broken or conn.closed:
                raise
            failed[tenant] = TenantFailure(failure_reason(error), is_transient(conn, error))
            log.exception("nightly dish costs failed for tenant %s", tenant)
        except Exception as error:  # a bug for one tenant must not stop the others
            failed[tenant] = TenantFailure(failure_reason(error), is_transient=False)
            log.exception("nightly dish costs crashed for tenant %s", tenant)
    return NightlyResult(done=done, failed=failed)


def plan_chunks(from_date: dt.date, to_date: dt.date) -> list[tuple[dt.date, dt.date]]:
    """[from_date, to_date] in chunks of at most MAX_CHUNK_DAYS days, newest first."""
    chunks = []
    hi = to_date
    while hi >= from_date:
        lo = max(from_date, hi - dt.timedelta(days=MAX_CHUNK_DAYS - 1))
        chunks.append((lo, hi))
        hi = lo - dt.timedelta(days=1)
    return chunks


def _tenants(conn: psycopg.Connection[Any], only: Collection[UUID] | None) -> list[UUID]:
    ids = None if only is None else list(only)
    with conn.transaction():
        rows = conn.execute(
            "select id from public.tenant where %s::uuid[] is null or id = any(%s::uuid[]) "
            "order by created_at, id",
            (ids, ids),
        ).fetchall()
    return [UUID(str(r[0])) for r in rows]


def _run_tenant(
    conn: psycopg.Connection[Any], tenant: UUID, today: dt.date | None, days: int
) -> TenantRun:
    start = time.perf_counter()
    with _transaction(conn, today):
        row = conn.execute(
            "select from_date, to_date from app.nightly_dish_cost_range(%s, %s)", (tenant, days)
        ).fetchone()
    if row is None or row[0] is None:
        return TenantRun(None, None, 0, 0, time.perf_counter() - start)
    from_date, to_date = row
    chunks = plan_chunks(from_date, to_date)
    snapshots = sum(_fill_chunk(conn, tenant, lo, hi, today) for lo, hi in chunks)
    run = TenantRun(from_date, to_date, len(chunks), snapshots, time.perf_counter() - start)
    log.info(
        "nightly dish costs: tenant %s, %s..%s (%d days, %d chunks), %d rows in %.2fs",
        tenant,
        from_date,
        to_date,
        (to_date - from_date).days + 1,
        run.chunks,
        run.snapshots,
        run.seconds,
    )
    return run


def _fill_chunk(
    conn: psycopg.Connection[Any], tenant: UUID, lo: dt.date, hi: dt.date, today: dt.date | None
) -> int:
    with _transaction(conn, today):
        row = conn.execute("select app.fill_dish_costs(%s, %s, %s)", (tenant, lo, hi)).fetchone()
    if row is None:  # a function call always returns one row
        raise RuntimeError("app.fill_dish_costs returned no row")
    return int(row[0])


@contextmanager
def _transaction(conn: psycopg.Connection[Any], today: dt.date | None) -> Iterator[None]:
    """One transaction, with app.today set for it when the caller fixed the date."""
    with conn.transaction():
        if today is not None:
            conn.execute("select set_config('app.today', %s, true)", (today.isoformat(),))
        yield


# --- CLI --------------------------------------------------------------------------------------


def _days(value: str) -> int:
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if not 1 <= days <= MAX_DAYS:
        raise argparse.ArgumentTypeError(f"days must be between 1 and {MAX_DAYS}")
    return days


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value!r}") from None


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m mermia_api.costing.nightly",
        description="Fills every tenant's dish costs up to each location's own business today.",
    )
    parser.add_argument(
        "--days", type=_days, default=DEFAULT_DAYS, help="window ending today (1-400, default 2)"
    )
    parser.add_argument("--today", type=_date, help="treat this date as every location's today")
    parser.add_argument("--db-url", default=os.environ.get("MERMIA_DB_URL"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db_url:
        print("set MERMIA_DB_URL or pass --db-url", file=sys.stderr)
        return EXIT_USAGE
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start = time.perf_counter()
    with psycopg.connect(args.db_url, autocommit=False) as conn:
        result = run_nightly_dish_costs(conn, today=args.today, days=args.days)
    print(
        f"nightly dish costs on {db_label(args.db_url)}: {len(result.done)} tenants, "
        f"{result.snapshots} rows, {len(result.failed)} failed, "
        f"{time.perf_counter() - start:.1f}s"
    )
    for tenant, failure in result.failed.items():
        kind = "transient" if failure.is_transient else "permanent"
        print(f"  failed {tenant}: {failure.reason} ({kind})", file=sys.stderr)
    return EXIT_FAILED if result.failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
