"""What the importers share when they turn a batch into pending changes (recipes, prices).

Nothing here writes the target tables: a person approves each pending change and
app.apply_pending_change applies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from mermia_contracts.batch import IssueIn


@dataclass(frozen=True)
class Proposals:
    pending_change_ids: tuple[UUID, ...]
    proposed: int
    unchanged: int
    already_pending: int  # identical to a pending proposal: not filed again
    held: int
    issues: tuple[IssueIn, ...]


NO_PROPOSALS = Proposals((), 0, 0, 0, 0, ())


def audit(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    actor: UUID | None,
    action: str,
    entity: tuple[str, UUID],
    before: dict[str, Any] | None,
    after: dict[str, Any],
    change_id: UUID,
    batch_id: UUID,
) -> None:
    """One audit_log row for a pending change an import filed or superseded."""
    conn.execute(
        """insert into public.audit_log
             (tenant_id, actor_user_id, actor_kind, action, entity_type, entity_id, before, after,
              pending_change_id, batch_id)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            tenant_id,
            actor,
            "user" if actor is not None else "system",
            action,
            *entity,
            None if before is None else Jsonb(before),
            Jsonb(after),
            change_id,
            batch_id,
        ),
    )
