"""CLI for concierge onboarding (MR-30):

    uv run python -m mermia_api.admin <spec.yaml> [--dry-run] [--auth-users] [--allow-remote-auth]

Connects with MERMIA_DB_URL (or --db-url): the postgres connection, never a client key. One
transaction; --dry-run applies everything and rolls it back. --auth-users also needs
MERMIA_API_URL and MERMIA_SERVICE_ROLE_KEY and is skipped in a dry run. Prints the database as
host:port/dbname (never the password) and phone numbers masked. Exit codes: 0 done, 1 refused
(nothing saved), 2 bad arguments or an invalid spec.
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

from mermia_api.admin.auth import AuthAdmin, AuthAdminError, SupabaseAuthAdmin
from mermia_api.admin.onboard import OnboardingError, Summary, onboard
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
    parser.add_argument("--dry-run", action="store_true", help="apply, report, then roll back")
    parser.add_argument(
        "--auth-users", action="store_true", help="link users with an email to Supabase Auth"
    )
    parser.add_argument(
        "--allow-remote-auth", action="store_true", help="allow a non-loopback MERMIA_API_URL"
    )
    parser.add_argument("--db-url", default=os.environ.get("MERMIA_DB_URL"))
    return parser.parse_args(argv)


def auth_client(args: argparse.Namespace) -> AuthAdmin | None:
    if not args.auth_users or args.dry_run:
        return None
    url, key = os.environ.get("MERMIA_API_URL"), os.environ.get("MERMIA_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("--auth-users needs MERMIA_API_URL and MERMIA_SERVICE_ROLE_KEY")
    return SupabaseAuthAdmin(url, key, allow_remote=args.allow_remote_auth)


def run(args: argparse.Namespace, spec: OnboardingSpec, auth: AuthAdmin | None) -> Summary:
    with psycopg.connect(args.db_url) as conn, conn.transaction(force_rollback=args.dry_run):
        return onboard(conn, spec, auth=auth)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db_url:
        print("set MERMIA_DB_URL or pass --db-url", file=sys.stderr)
        return EXIT_USAGE
    try:
        spec = load_spec(args.spec)
        auth = auth_client(args)
    except ValidationError as e:
        print(f"{args.spec.name}: invalid spec", *validation_lines(e), sep="\n", file=sys.stderr)
        return EXIT_USAGE
    except (OSError, ValueError) as e:
        print(f"{args.spec.name}: {e}", file=sys.stderr)
        return EXIT_USAGE
    try:
        summary = run(args, spec, auth)
    except (OnboardingError, AuthAdminError) as e:
        print(f"refused, nothing saved: {e}", file=sys.stderr)
        return EXIT_REFUSED
    except psycopg.Error as e:
        reason = e.diag.message_primary or (str(e).splitlines() or [type(e).__name__])[0]
        print(f"database error, nothing saved: {reason}", file=sys.stderr)
        return EXIT_REFUSED
    print(render(summary, db_label(args.db_url), args.dry_run))
    if args.auth_users and args.dry_run:
        print("  note: --auth-users is skipped in a dry run")
    return EXIT_OK
