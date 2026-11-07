"""Filing one ingredient's price from a CFDI invoice as a pending change (MR-36).

See prices.py for the rules. The payload is FLAT, `IngredientPriceSet(...).model_dump(mode="json")`:
app.apply_ingredient_price reads payload.unit_price, payload.effective_from and payload.source, so
the nested proposal shape recipe.upsert uses would fail on approval.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from mermia_api.ingestion import price_issues as notes
from mermia_api.ingestion.batch_checks import INVOICE_ZONE
from mermia_api.ingestion.price_match import BY_NAME, Match
from mermia_api.ingestion.proposals import audit
from mermia_contracts.batch import IssueIn, PurchaseLineIn
from mermia_contracts.db.models import IngredientPriceSource
from mermia_contracts.pending import TARGET_TYPE, IngredientPriceSet, PendingKind

KIND = PendingKind.ingredient_price_set
CFDI_PARSERS = "cfdi.%"  # diff.parser of the proposals CFDI imports file (any parser version)
SOURCE = IngredientPriceSource.cfdi
REQUIRED_ROLE = "manager"  # decision 6: whoever the tenant lets approve ingredient_price.set
TTL = dt.timedelta(hours=24)  # decision 7
SUPERSEDED = "superseded"  # resolved_via of a pending change a newer proposal replaced
# Decision 4: a price equal to the price of record is not proposed; any real change is. Raise
# this (in percent points) to skip small moves too.
MIN_CHANGE_PCT = Decimal(0)
# Decision 8 (PENDING OWNER CONFIRMATION): an invoice dated before the ingredient's latest price
# is skipped with a note. False would propose it with the invoice date as effective_from.
SKIP_OLDER_INVOICES = True
BY_NAME_LABEL = "(por nombre)"  # decision 2: how MR-37 marks a match without an alias
PRICE_PLACES = Decimal("0.000001")
PCT_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class Invoice:
    batch_id: UUID
    parser: str
    cfdi_uuid: str | None
    issued_at: dt.datetime  # the invoice's date and time: the newest invoice wins
    day: dt.date  # the invoice date (Mexico City): the effective date of its prices
    supplier_name: str  # the tenant's name for the supplier, or the invoice's (a person masked)
    supplier_matched_by: str  # price_match: "rfc", "name" or "none"


@dataclass(frozen=True)
class Priced:
    """One invoice line matched to an ingredient and put in its base unit."""

    n: int  # the line's number on the invoice (1-based)
    line: PurchaseLineIn
    match: Match
    base_per_unit: Decimal
    ieps: bool  # the parser flagged an itemized IEPS (left out of the price)

    def as_json(self) -> dict[str, Any]:
        return {
            "row": self.n,
            "description": self.line.description,
            "qty": str(self.line.qty),
            "unit": self.line.unit,
            "unit_price_net": str(self.line.unit_price_net),  # per invoiced unit (decision 3)
            "base_per_unit": str(self.base_per_unit),
            "ieps_excluded": self.ieps,
        }


@dataclass(frozen=True)
class Filed:
    outcome: str  # "proposed" | "unchanged" | "already_pending" | "held"
    change_id: UUID | None = None
    notes: tuple[IssueIn, ...] = ()


@dataclass(frozen=True)
class _Record:
    unit_price_net: Decimal
    effective_from: dt.date
    source: str

    def as_json(self) -> dict[str, Any]:
        return {
            "unit_price_net": str(self.unit_price_net.quantize(PRICE_PLACES)),
            "effective_from": self.effective_from.isoformat(),
            "source": self.source,
        }


def file_price(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    invoice: Invoice,
    group: tuple[Priced, ...],
    price: Decimal,
    proposed_by: UUID | None,
) -> Filed:
    ingredient = group[0].match.ingredient
    latest = _latest_price_day(conn, tenant_id, ingredient.id)
    if SKIP_OLDER_INVOICES and latest is not None and latest > invoice.day:
        return Filed("held", notes=(notes.older_than_record(ingredient.name, invoice.day, latest),))
    newer = _newer_pending(conn, tenant_id, ingredient.id, invoice.issued_at)
    if newer is not None:
        newer_at = newer.astimezone(INVOICE_ZONE)
        return Filed("held", notes=(notes.newer_pending(ingredient.name, newer_at),))
    before = _price_of_record(conn, ingredient.id, invoice.day)
    pct = _change_pct(before, price)
    small = pct is not None and abs(pct) < MIN_CHANGE_PCT
    if before is not None and (price == before.unit_price_net or small):
        # the invoice confirms the price of record: an older import proposal is stale
        replaced = _supersede(conn, tenant_id, invoice.batch_id, ingredient.id, None, proposed_by)
        kept = (notes.pending_replaced(ingredient.name, kept_current=True),) if replaced else ()
        return Filed("unchanged", notes=kept)
    values = IngredientPriceSet(unit_price=price, effective_from=invoice.day, source=SOURCE)
    payload = values.model_dump(mode="json")
    if _identical_pending(conn, tenant_id, ingredient.id, payload):
        return Filed("already_pending")
    diff = _diff(invoice, group, before, payload, pct)
    change_id = _insert(conn, tenant_id, ingredient.id, payload, diff, proposed_by)
    audit(
        conn,
        tenant_id,
        proposed_by,
        "pending_change.propose",
        (TARGET_TYPE[KIND], ingredient.id),
        diff["before"],
        diff["after"],
        change_id,
        invoice.batch_id,
    )
    replaced = _supersede(conn, tenant_id, invoice.batch_id, ingredient.id, change_id, proposed_by)
    kept = (notes.pending_replaced(ingredient.name, kept_current=False),) if replaced else ()
    return Filed("proposed", change_id, kept)


def _change_pct(before: _Record | None, price: Decimal) -> Decimal | None:
    if before is None or before.unit_price_net == 0:
        return None
    moved = (price - before.unit_price_net) / before.unit_price_net * 100
    return moved.quantize(PCT_PLACES)


def _diff(
    invoice: Invoice,
    group: tuple[Priced, ...],
    before: _Record | None,
    payload: dict[str, Any],
    pct: Decimal | None,
) -> dict[str, Any]:
    """What MR-37 shows. Names only: never the supplier's or the buyer's RFC."""
    match = group[0].match
    return {
        "batch_id": str(invoice.batch_id),
        "parser": invoice.parser,
        "report_date": invoice.day.isoformat(),
        "issued_at": invoice.issued_at.isoformat(),  # what _newer_pending compares
        "cfdi_uuid": invoice.cfdi_uuid,
        "supplier_name": invoice.supplier_name,
        "supplier_matched_by": invoice.supplier_matched_by,
        "ingredient": {
            "id": str(match.ingredient.id),
            "name": match.ingredient.name,
            "base_unit": match.ingredient.base_unit,
        },
        "matched_by": match.how,
        "match_label": BY_NAME_LABEL if match.how == BY_NAME else None,
        "lines": [p.as_json() for p in group],
        "before": None if before is None else before.as_json(),
        "after": {
            "unit_price_net": payload["unit_price"],
            "effective_from": payload["effective_from"],
            "source": payload["source"],
        },
        "change_pct": None if pct is None else str(pct),
    }


def _insert(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    ingredient_id: UUID,
    payload: dict[str, Any],
    diff: dict[str, Any],
    proposed_by: UUID | None,
) -> UUID:
    row = conn.execute(
        """insert into public.pending_change
             (tenant_id, kind, target_type, target_id, base_version, payload, diff,
              proposed_by_user, proposed_via, required_role, expires_at)
           values (%(tenant)s, %(kind)s, %(type)s, %(target)s,
                   app.pending_base_version(%(kind)s, %(target)s, %(payload)s),
                   %(payload)s, %(diff)s, %(by)s, 'import', %(role)s, now() + %(ttl)s)
           returning id""",
        {
            "tenant": tenant_id,
            "kind": KIND.value,
            "type": TARGET_TYPE[KIND],
            "target": ingredient_id,
            "payload": Jsonb(payload),
            "diff": Jsonb(diff),
            "by": proposed_by,
            "role": REQUIRED_ROLE,
            "ttl": TTL,
        },
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _latest_price_day(
    conn: psycopg.Connection[Any], tenant_id: UUID, ingredient_id: UUID
) -> dt.date | None:
    """The date of the ingredient's latest price (benchmarks aside)."""
    row = conn.execute(
        """select max(effective_from) from public.ingredient_price
           where tenant_id = %s and ingredient_id = %s and source <> 'benchmark'""",
        (tenant_id, ingredient_id),
    ).fetchone()
    return None if row is None else row[0]


def _price_of_record(
    conn: psycopg.Connection[Any], ingredient_id: UUID, day: dt.date
) -> _Record | None:
    row = conn.execute(
        "select unit_price_net, effective_from, source::text from app.price_of_record(%s, %s)",
        (ingredient_id, day),
    ).fetchone()
    return None if row is None else _Record(row[0], row[1], row[2])


def _live_imports() -> str:
    """Live CFDI import proposals of the ingredient; other import kinds are never touched."""
    return """tenant_id = %(tenant)s and kind = %(kind)s and target_id = %(target)s
              and status = 'pending' and proposed_via = 'import'
              and diff ->> 'parser' like %(parsers)s
              and (expires_at is null or expires_at > now())"""


def _newer_pending(
    conn: psycopg.Connection[Any], tenant_id: UUID, ingredient_id: UUID, issued_at: dt.datetime
) -> dt.datetime | None:
    """When the latest live CFDI proposal for the ingredient from a later invoice was issued."""
    row = conn.execute(
        f"""select max((diff ->> 'issued_at')::timestamptz) from public.pending_change
            where {_live_imports()} and (diff ->> 'issued_at')::timestamptz > %(at)s""",
        {
            "tenant": tenant_id,
            "kind": KIND.value,
            "target": ingredient_id,
            "parsers": CFDI_PARSERS,
            "at": issued_at,
        },
    ).fetchone()
    return None if row is None else row[0]


def _identical_pending(
    conn: psycopg.Connection[Any], tenant_id: UUID, ingredient_id: UUID, payload: dict[str, Any]
) -> bool:
    """A live pending change of any origin already proposes this exact price and date."""
    row = conn.execute(
        """select 1 from public.pending_change
           where tenant_id = %s and kind = %s and target_id = %s and status = 'pending'
             and (expires_at is null or expires_at > now()) and payload = %s
             and base_version is not distinct from
                 app.pending_base_version(kind, target_id, payload)
           limit 1""",
        (tenant_id, KIND.value, ingredient_id, Jsonb(payload)),
    ).fetchone()
    return row is not None


def _supersede(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    batch_id: UUID,
    ingredient_id: UUID,
    change_id: UUID | None,
    proposed_by: UUID | None,
) -> bool:
    """The newest invoice wins: every other live CFDI proposal of the ingredient expires
    (resolved_via 'superseded'). An agent's or the dashboard's proposal is never touched.
    `change_id` is None when the invoice confirms the price of record. True if any expired."""
    rows = conn.execute(
        f"""update public.pending_change
            set status = 'expired', resolved_at = now(), resolved_via = %(via)s
            where {_live_imports()} and id is distinct from %(new)s
            returning id""",
        {
            "via": SUPERSEDED,
            "tenant": tenant_id,
            "kind": KIND.value,
            "target": ingredient_id,
            "parsers": CFDI_PARSERS,
            "new": change_id,
        },
    ).fetchall()
    for (old_id,) in rows:
        audit(
            conn,
            tenant_id,
            proposed_by,
            "pending_change.supersede",
            ("pending_change", old_id),
            {"status": "pending"},
            {
                "status": "expired",
                "resolved_via": SUPERSEDED,
                "superseded_by": None if change_id is None else str(change_id),
            },
            old_id,
            batch_id,
        )
    return bool(rows)
