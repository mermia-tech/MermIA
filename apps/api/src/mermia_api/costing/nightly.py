"""The nightly dish-cost job (MR-100): every tenant's dish costs for each location's own today.

Only approval taps and their backfills write `dish_cost_snapshot`. A day nobody approves anything
would have no costs, so margins, food cost %, alerts and the weekly report go blank for it. This job
fills, for every tenant in `public.tenant`, every active dish's row at each location's own business
today, and a short catch-up window before it (`days`, default 2: yesterday and today, at most 400).

- Insert only (`app.fill_dish_costs`): a row that exists keeps its id and values, a rerun writes
  nothing. The rows it writes are the ones `app.compute_dish_costs` writes for those days.
- Insert only, so a snapshot made stale outside approval taps and backfills is not refreshed here.
  Any other path that writes costing inputs directly (e.g. a future CFDI ingest writing prices) must
  call the recompute itself.
- Tenants one at a time. Each tenant's window is cut into chunks of at most 7 days, newest first,
  one transaction each: the per-tenant lock is held for one chunk (about 1-3 s) only. Each
  transaction sets `lock_timeout` to 5 s, so a chunk waiting on the lock (or a tap waiting behind
  it) fails fast; the failure is transient and the run goes on.
- A tenant that fails is logged and reported in `failed` (SQLSTATE and exception class only, as
  MR-87's backfill sweep), tagged transient or not with the sweep's split; the run goes on with the
  next tenant. A broken connection is raised: nothing else can run. Every tenant is retried on the
  next run (the job is idempotent).

Entry points (MR-102), both on their own connection, as service_role, logging one summary line:

- `run_job(db_url)`: the scheduled run, every tenant. It takes a job-wide advisory lock and returns
  None (runs nothing) when another run holds it.
- `refresh_tenant(db_url, tenant_id)`: one tenant, without the job lock (so the hourly run never
  delays it), e.g. after an approved upload or before a tenant's weekly report (a rerun that finds
  nothing missing takes about 0.01 s). It refuses a tenant that is not in `public.tenant`. Callers
  pass ids read from `public.tenant` or from an approved upload, never from user or agent input. A
  busy tenant lock comes back as a transient failure in `failed`, not an exception; the next hourly
  run fills what is missing.

Every transaction (`_transaction`) runs `set local role service_role` and sets `lock_timeout` and
`statement_timeout` (60 s), so the job never runs as a superuser even if the session role is lost.
The job lock is a session lock: it needs a direct or session-mode DB URL (not the transaction-mode
pooler on port 6543), or the lock and the role could land on different backends.

`run_nightly_dish_costs` takes an open connection instead: give it a service-role connection with
no transaction open (inside an open transaction each chunk is only a savepoint and the locks are
held until the caller commits).

CLI, `run_job` with exit codes (connects with MERMIA_DB_URL; exit 0 done or skipped, 1 a tenant
failed or the role switch failed, 2 bad arguments):

    uv run python -m mermia_api.costing.nightly [--days N] [--today YYYY-MM-DD]

Scheduling (Dev B, #38): call `run_job(db_url)` hourly with the default 2 days. A rerun only checks
for missing rows, so hourly picks up each time zone soon after its midnight and each new dish soon
after an upload; a 2-day run takes about 33-49 s for 50 tenants. A long catch-up (after an outage)
is run by hand with the CLI and `--days N`, never by the schedule (30 days takes 5-9 min for 50).

Caller rules for the weekly report and the scheduler (Dev B, #38):

a. The Monday weekly report calls `refresh_tenant(db_url, tenant_id, days=8)`: today minus 7 is the
   previous Monday, so `days=7` would miss it. Hourly runs keep DEFAULT_DAYS=2.
b. A transient failure (e.g. a busy tenant lock) in `failed`: retry once, then build the report
   anyway; its missing-days section shows any gap.
c. `run_job` and `refresh_tenant` block on psycopg. Call them from a sync Procrastinate task or a
   thread, never directly inside an async handler.
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
MAX_CHUNK_DAYS = 7  # days per transaction (app.fill_dish_costs allows 31): lock held ~1-3 s
LOCK_TIMEOUT = "5s"  # a chunk (or a tap behind it) waits this long for the tenant lock
STATEMENT_TIMEOUT = "60s"  # one chunk's longest run; 57014 is permanent in the sweep's split
JOB_LOCK_KEY = "mermia:nightly_dish_costs"  # job-wide advisory lock: one run at a time
JOB_ROLE = "service_role"
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

log = logging.getLogger(__name__)


class ServiceRoleError(RuntimeError):
    """The session could not drop to service_role; the message has the SQLSTATE and class only."""


class UnknownTenantError(ValueError):
    """refresh_tenant was given an id that is not in public.tenant."""


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
    _check_days(days)
    done: dict[UUID, TenantRun] = {}
    failed: dict[UUID, TenantFailure] = {}
    for tenant in _tenants(conn, only):
        try:
            done[tenant] = _run_tenant(conn, tenant, today, days)
        except psycopg.Error as error:
            if conn.broken or conn.closed:
                raise
            failed[tenant] = TenantFailure(failure_reason(error), is_transient(conn, error))
            log.error("nightly dish costs failed for tenant %s: %s", tenant, failed[tenant].reason)
        except Exception as error:  # a bug for one tenant must not stop the others
            failed[tenant] = TenantFailure(failure_reason(error), is_transient=False)
            log.error("nightly dish costs crashed for tenant %s: %s", tenant, failed[tenant].reason)
    return NightlyResult(done=done, failed=failed)


def _check_days(days: int) -> None:
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}, got {days}")


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
    with _transaction(conn, None):
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
    """One transaction as service_role with short lock and statement timeouts; app.today is set
    if the caller fixed the date."""
    with conn.transaction():
        conn.execute(f"set local role {JOB_ROLE}")
        conn.execute(f"set local statement_timeout = '{STATEMENT_TIMEOUT}'")
        conn.execute(f"set local lock_timeout = '{LOCK_TIMEOUT}'")
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
        description="Fills every tenant's dish costs up to each location's own business today. "
        "MERMIA_DB_URL must be a direct or session-mode URL, not the pooler on port 6543.",
    )
    parser.add_argument(
        "--days", type=_days, default=DEFAULT_DAYS, help="window ending today (1-400, default 2)"
    )
    parser.add_argument("--today", type=_date, help="treat this date as every location's today")
    return parser.parse_args(argv)


def become_service_role(conn: psycopg.Connection[Any]) -> None:
    """Drop to service_role for the session, so the job never runs as a superuser."""
    with conn.transaction():
        conn.execute(f"set role {JOB_ROLE}")


def try_job_lock(conn: psycopg.Connection[Any]) -> bool:
    """Take the job-wide session advisory lock; False when another run holds it."""
    with conn.transaction():
        row = conn.execute(
            "select pg_try_advisory_lock(hashtextextended(%s, 0))", (JOB_LOCK_KEY,)
        ).fetchone()
    return bool(row and row[0])


# --- entry points (MR-102) ----------------------------------------------------------------------


def run_job(
    db_url: str, *, today: dt.date | None = None, days: int = DEFAULT_DAYS
) -> NightlyResult | None:
    """The scheduled run: every tenant, one run at a time. None when another run holds the lock.

    Raises ServiceRoleError when the session cannot become service_role, and psycopg errors when
    the database cannot be reached or the connection breaks (nothing else can run).
    """
    _check_days(days)
    start = time.perf_counter()
    with _connect(db_url) as conn:
        _become_service_role(conn)
        if not try_job_lock(conn):
            log.warning("another nightly dish-cost run holds the job lock; skipping this run")
            return None
        result = run_nightly_dish_costs(conn, today=today, days=days)
    _log_summary(f"nightly dish costs on {db_label(db_url)}", result, start)
    return result


def refresh_tenant(
    db_url: str, tenant_id: UUID, *, today: dt.date | None = None, days: int = DEFAULT_DAYS
) -> NightlyResult:
    """One tenant's missing dish costs, without the job lock. Trusted callers only: `tenant_id`
    comes from public.tenant or an approved upload, never from user or agent input.

    Raises UnknownTenantError for an id not in public.tenant. A failure of the tenant itself (e.g.
    its lock is busy) is reported in `failed`, tagged transient or not, and not raised.
    """
    if not isinstance(tenant_id, UUID):
        raise TypeError(f"tenant_id must be a UUID, got {type(tenant_id).__name__}")
    _check_days(days)
    start = time.perf_counter()
    with _connect(db_url) as conn:
        _become_service_role(conn)
        if not _tenants(conn, [tenant_id]):
            raise UnknownTenantError(f"no tenant {tenant_id}")
        result = run_nightly_dish_costs(conn, today=today, days=days, only=[tenant_id])
    _log_summary(f"dish-cost refresh for tenant {tenant_id} on {db_label(db_url)}", result, start)
    return result


@contextmanager
def _connect(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(db_url, autocommit=False) as conn:
        yield conn


def _become_service_role(conn: psycopg.Connection[Any]) -> None:
    try:
        become_service_role(conn)
    except psycopg.Error as error:
        raise ServiceRoleError(f"cannot switch to {JOB_ROLE}: {failure_reason(error)}") from None


def _log_summary(label: str, result: NightlyResult, start: float) -> None:
    log.info(
        "%s: %d tenants, %d rows, %d failed, %.1fs",
        label,
        len(result.done),
        result.snapshots,
        len(result.failed),
        time.perf_counter() - start,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    db_url = os.environ.get("MERMIA_DB_URL")
    if not db_url:
        print("set MERMIA_DB_URL", file=sys.stderr)
        return EXIT_USAGE
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = run_job(db_url, today=args.today, days=args.days)
    except ServiceRoleError as error:
        print(error, file=sys.stderr)
        return EXIT_FAILED
    if result is None:
        return EXIT_OK
    for tenant, failure in result.failed.items():
        kind = "transient" if failure.is_transient else "permanent"
        print(f"  failed {tenant}: {failure.reason} ({kind})", file=sys.stderr)
    return EXIT_FAILED if result.failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
