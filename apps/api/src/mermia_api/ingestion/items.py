"""Matching an import line to the tenant's catalog: shared by the batch loader and the recipe
importer, so a dish is found the same way for its sales and for its recipe."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from mermia_contracts.keys import normalize_name


def find_item(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    location_id: UUID | None,
    external_id: str | None,
    name: str,
) -> tuple[UUID | None, str | None]:
    """The catalog item an import line means, and how it matched: "code+name", "name", or
    "code" (same SR code, another name). SR codes are per install, so in a chain a code alone
    may be another location's dish: a "code" match is not used, the line gets its own item."""
    row = conn.execute(
        """select id, (%s::text is not null and external_id = %s),
                  normalized_name = %s
           from public.menu_item
           where tenant_id = %s and (location_id is null or location_id = %s)
             and ((%s::text is not null and external_id = %s) or normalized_name = %s)
           order by (normalized_name = %s) desc, (external_id = %s) desc nulls last,
                    location_id nulls last
           limit 1""",
        (
            external_id,
            external_id,
            normalize_name(name),
            tenant_id,
            location_id,
            external_id,
            external_id,
            normalize_name(name),
            normalize_name(name),
            external_id,
        ),
    ).fetchone()
    if row is None:
        return None, None
    by_code, by_name = bool(row[1]), bool(row[2])
    how = "code+name" if by_code and by_name else "name" if by_name else "code"
    return UUID(str(row[0])), how
