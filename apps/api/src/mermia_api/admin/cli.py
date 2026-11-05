"""CLI for concierge onboarding (MR-30):

    uv run python -m mermia_api.admin <spec.yaml> --operator <handle> [--dry-run]

Connects with MERMIA_DB_URL (or --db-url): the postgres connection, never a client key. One
transaction; --dry-run applies everything and rolls it back. --operator (who runs it) goes into
every audit row's request_id. Prints the database as host:port/dbname (never the password) and
phone numbers masked. Exit codes: 0 done, 1 refused (nothing saved), 2 bad arguments or an
invalid spec. Supabase Auth users (Phase 2 dashboard) are not created here.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from pydantic import ValidationError

from mermia_api.admin.onboard import OnboardingError, Summary, check_operator, onboard
from mermia_api.admin.spec import OnboardingSpec, load_spec

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2


def db_label(url: str) -> str:
    """host:port/dbname of a connection string, without user or password."""
    try:
        info = conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        return "(unparsable database URL)"
    return f"{info.get('host', 'localhost')}:{info.get('port', 5432)}/{info.get('dbname', '')}"


def render(summary: Summary, db: str, dry_run: bool) -> str:
    head = f"MermIA onboarding: {summary.tenant_name} ({summary.tenant_id}) on {db}"
    lines = [head + (" -- DRY RUN, nothing saved" if dry_run else "")]
    width = max(len(c.label) for c in summary.changes)
    for c in summary.changes:
        detail = f"  {c.detail}" if c.detail else ""
        lines.append(f"  {c.entity:<10} {c.label:<{width}}  {c.action:<9}{detail}".rstrip())
    lines += [f"  note: {n}" for n in summary.notes]
    created = any(c.entity == "tenant" and c.action == "created" for c in summary.changes)
    if created and not dry_run:
        lines.append(f"  next: add tenant.id: {summary.tenant_id} to the spec before rerunning it")
    counts = {
        a: sum(c.action == a for c in summary.changes) for a in ("created", "updated", "unchanged")
    }
    totals = ", ".join(f"{n} {a}" for a, n in counts.items())
    lines.append(f"{totals}; {summary.audit_rows} audit rows; run {summary.run_id}")
    return "\n".join(lines)


def validation_lines(error: ValidationError) -> list[str]:
    """Where and why, never the input itself (it holds phone numbers)."""
    return [f"  {'.'.join(str(p) for p in e['loc']) or 'spec'}: {e['msg']}" for e in error.errors()]


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m mermia_api.admin",
        description="Creates or updates a tenant, its locations and its users from a spec file.",
    )
    parser.add_argument("spec", type=Path, help="YAML or JSON spec (see admin/example.yaml)")
    parser.add_argument(
        "--operator", required=True, type=operator, help="your handle, recorded in the audit log"
    )
    parser.add_argument("--dry-run", action="store_true", help="apply, report, then roll back")
    parser.add_argument("--db-url", default=os.environ.get("MERMIA_DB_URL"))
    return parser.parse_args(argv)


def operator(value: str) -> str:
    try:
        return check_operator(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def run(args: argparse.Namespace, spec: OnboardingSpec) -> Summary:
    with psycopg.connect(args.db_url) as conn, conn.transaction(force_rollback=args.dry_run):
        return onboard(conn, spec, operator=args.operator)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db_url:
        print("set MERMIA_DB_URL or pass --db-url", file=sys.stderr)
        return EXIT_USAGE
    try:
        spec = load_spec(args.spec)
    except ValidationError as e:
        print(f"{args.spec.name}: invalid spec", *validation_lines(e), sep="\n", file=sys.stderr)
        return EXIT_USAGE
    except (OSError, ValueError) as e:
        print(f"{args.spec.name}: {e}", file=sys.stderr)
        return EXIT_USAGE
    try:
        summary = run(args, spec)
    except OnboardingError as e:
        print(f"refused, nothing saved: {e}", file=sys.stderr)
        return EXIT_REFUSED
    except psycopg.Error as e:
        reason = e.diag.message_primary or (str(e).splitlines() or [type(e).__name__])[0]
        print(f"database error, nothing saved: {reason}", file=sys.stderr)
        return EXIT_REFUSED
    print(render(summary, db_label(args.db_url), args.dry_run))
    return EXIT_OK
