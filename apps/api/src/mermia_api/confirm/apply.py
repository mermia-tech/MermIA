"""Apply an approved pending change (MR-32; C5 `apply_pending_change`, MR-10 spec 7.5.7).

The seam the confirmation service (MR-37) calls when a person taps Confirmar. It runs on a
service-role connection: `app.apply_pending_change` is executable by service_role only and does
every check in the database (membership, authorization, status, expiry, version), the write, the
dish-cost recompute and the audit rows, in one transaction. `args.user_id` is the approver's
`app_user.id`, resolved by the caller from the channel identity.

Business outcomes come back as an `ApplyResult` (never raised). With no transaction open on
`conn` the call commits on its own; inside one it is a savepoint and the caller commits.
"""

from __future__ import annotations

from typing import Any

import psycopg

from mermia_contracts.pending import ApplyPendingChangeArgs, ApplyResult


def apply_pending_change(
    conn: psycopg.Connection[Any], args: ApplyPendingChangeArgs
) -> ApplyResult:
    with conn.transaction():
        row = conn.execute(
            "select app.apply_pending_change(%s, %s)", (args.id, args.user_id)
        ).fetchone()
    if row is None:  # a function call always returns one row
        raise RuntimeError("app.apply_pending_change returned no row")
    return ApplyResult.model_validate(row[0])
