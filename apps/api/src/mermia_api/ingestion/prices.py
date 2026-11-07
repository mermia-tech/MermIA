"""CFDI purchase batches become ingredient_price.set pending changes (MR-36; 09 section 3).

Nothing here writes ingredient_price: a person approves each change and
app.apply_pending_change writes the price (and recomputes dish costs). For every invoice:

- The buyer's RFC must be the tenant's (decision 11: another buyer rejects the batch; a tenant
  without an RFC is a warning). See buyer_issues.
- Lines are matched to ingredients (price_match) and put in base units (cfdi_units). Unmatched
  lines get one summary note (decision 1); ambiguous ones, packs without a size (decision 14) and
  units without a conversion are held with a note.
- The lines of one ingredient merge into one price, weighted by quantity (decision 15):
  sum(qty x price per invoiced unit) / sum(qty x base units per invoiced unit), rounded once to 6
  decimals, half up (MR-11 D27). A price that rounds to zero is held.
- Prices are without IVA; an itemized IEPS is left out of the cost with the parser's warning
  (decision 9, IEPS_POLICY). Discounts are already netted by the parser.
- Per ingredient, the invoice date is the effective date and nothing is filed when: the price of
  record that day is the same (decision 4); the ingredient already has a price dated after the
  invoice (decision 8); an import proposal from a later invoice is pending; or an identical one
  is pending. Otherwise one pending_change (decision 5: one per ingredient; MR-37 groups them by
  diff.batch_id) with a FLAT payload, `IngredientPriceSet(...).model_dump(mode="json")`, which is
  what app.apply_ingredient_price reads, and its audit_log row. It supersedes older pending
  import proposals of the ingredient (never an agent's or the dashboard's).
- The diff keeps the CFDI UUID (apply_ingredient_price has no source_ref), the supplier's cleaned
  name and the invoice lines with their price per invoiced unit (decision 3, shown by MR-37).
  No RFC ever goes in the diff, the audit row or a note.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from pydantic import ValidationError

from mermia_api.ingestion import price_issues as notes
from mermia_api.ingestion.cfdi_units import PACK_UNKNOWN, UnitHeld, base_per_unit
from mermia_api.ingestion.price_file import Invoice, Priced, file_price
from mermia_api.ingestion.price_match import Ambiguous, Catalog, find_supplier, load_catalog
from mermia_api.ingestion.proposals import Proposals
from mermia_contracts.batch import IssueIn, NormalizedBatch, PurchaseIn
from mermia_contracts.pending import IngredientPriceSet

ZONE = ZoneInfo("America/Mexico_City")  # the parser's: CFDI Fecha is Mexico City time
PRICE_PLACES = Decimal("0.000001")
IEPS_LISTED = "cfdi.ieps_listed"  # the parser's warning for a line with itemized IEPS
# Decision 9 (PENDING OWNER CONFIRMATION): "exclude" proposes the price without the IEPS (the
# parser's price never includes it); "hold" files nothing for such a line until it is settled.
IEPS_POLICY = "exclude"
# Decision 11: an invoice addressed to another RFC is rejected.
REJECT_OTHER_BUYER = True


def buyer_issues(
    conn: psycopg.Connection[Any], tenant_id: UUID, batch: NormalizedBatch
) -> tuple[list[IssueIn], list[IssueIn]]:
    """(reject, warnings) from checking each invoice's buyer RFC against the tenant's."""
    row = conn.execute("select rfc from public.tenant where id = %s", (tenant_id,)).fetchone()
    tenant_rfc = None if row is None or row[0] is None else str(row[0]).strip().upper()
    buyers = {d.buyer_rfc.strip().upper() for d in batch.purchases if d.buyer_rfc is not None}
    if not buyers:
        return [], []
    if not tenant_rfc:
        return [], [notes.tenant_rfc_missing()]
    if REJECT_OTHER_BUYER and buyers != {tenant_rfc}:
        return [notes.buyer_mismatch()], []
    return [], []


def propose_prices(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    batch_id: UUID,
    batch: NormalizedBatch,
    proposed_by: UUID | None,
) -> Proposals:
    """Files an ingredient_price.set pending change for every ingredient of the batch's invoices
    whose price moved. Runs inside the loader's transaction, under its per-tenant prices lock."""
    found = [
        _propose_invoice(conn, tenant_id, batch_id, batch, doc, proposed_by)
        for doc in batch.purchases
    ]
    return Proposals(
        pending_change_ids=tuple(i for p in found for i in p.pending_change_ids),
        proposed=sum(p.proposed for p in found),
        unchanged=sum(p.unchanged for p in found),
        already_pending=sum(p.already_pending for p in found),
        held=sum(p.held for p in found),
        issues=tuple(i for p in found for i in p.issues),
    )


def _propose_invoice(
    conn: psycopg.Connection[Any],
    tenant_id: UUID,
    batch_id: UUID,
    batch: NormalizedBatch,
    doc: PurchaseIn,
    proposed_by: UUID | None,
) -> Proposals:
    supplier = find_supplier(conn, tenant_id, doc.supplier)
    issues: list[IssueIn] = [] if supplier else [notes.supplier_unknown(doc.supplier.name)]
    catalog = load_catalog(conn, tenant_id, supplier.id if supplier else None)
    ieps_rows = {i.row_ref for i in batch.issues if i.code == IEPS_LISTED}
    priced, held = _price_lines(doc, catalog, ieps_rows, issues)
    invoice = Invoice(
        batch_id=batch_id,
        parser=batch.parser,
        cfdi_uuid=None if doc.cfdi_uuid is None else str(doc.cfdi_uuid),
        day=doc.issued_at.astimezone(ZONE).date(),
        supplier_name=supplier.name if supplier else doc.supplier.name,
    )
    counts: Counter[str] = Counter()
    ids: list[UUID] = []
    for group in _groups(priced):
        price = _merged_price(group)
        if price is None:
            issues.append(notes.price_out_of_range(group[0].match.ingredient.name))
            held += len(group)
            continue
        filed = file_price(conn, tenant_id, invoice, group, price, proposed_by)
        issues.extend(filed.notes)
        if filed.outcome == "held":
            held += len(group)
            continue
        counts[filed.outcome] += 1
        if filed.change_id is not None:
            ids.append(filed.change_id)
    return Proposals(
        tuple(ids),
        counts["proposed"],
        counts["unchanged"],
        counts["already_pending"],
        held,
        tuple(issues),
    )


def _price_lines(
    doc: PurchaseIn, catalog: Catalog, ieps_rows: set[str | None], issues: list[IssueIn]
) -> tuple[list[Priced], int]:
    """The lines matched and put in base units, and how many were held or unmatched. Notes for
    the others go to `issues`; the unmatched get one summary note (decision 1)."""
    priced: list[Priced] = []
    unmatched: list[str] = []
    held = 0
    for n, line in enumerate(doc.lines, start=1):
        try:
            match = catalog.match(line.description)
        except Ambiguous:
            issues.append(notes.ambiguous(n, line.description))
            held += 1
            continue
        if match is None:
            unmatched.append(line.description)
            continue
        ieps = str(n) in ieps_rows
        if ieps and IEPS_POLICY == "hold":
            issues.append(notes.ieps_held(n, line.description))
            held += 1
            continue
        ingredient = match.ingredient
        try:
            per_unit = base_per_unit(
                line.unit, ingredient.base_unit, match.pack, catalog.conversions(ingredient.id)
            )
        except UnitHeld as e:
            issues.append(
                notes.pack_unknown(n, line.description, line.unit)
                if e.code == PACK_UNKNOWN
                else notes.unit_mismatch(
                    n, line.description, line.unit, ingredient.name, ingredient.base_unit
                )
            )
            held += 1
            continue
        priced.append(Priced(n, line, match, per_unit, ieps))
    if unmatched:
        issues.append(notes.unmatched(unmatched))
    return priced, held + len(unmatched)


def _groups(priced: list[Priced]) -> list[tuple[Priced, ...]]:
    """The priced lines by ingredient, in the order each ingredient first appears."""
    by_ingredient: dict[UUID, list[Priced]] = {}
    for p in priced:
        by_ingredient.setdefault(p.match.ingredient.id, []).append(p)
    return [tuple(lines) for lines in by_ingredient.values()]


def _merged_price(group: tuple[Priced, ...]) -> Decimal | None:
    """Pesos per base unit for the ingredient across its lines, weighted by quantity, rounded
    once (decision 15). None when it is zero or out of the contract's range."""
    pesos = sum((p.line.qty * p.line.unit_price_net for p in group), Decimal(0))
    base = sum((p.line.qty * p.base_per_unit for p in group), Decimal(0))
    price = (pesos / base).quantize(PRICE_PLACES, ROUND_HALF_UP)
    try:
        IngredientPriceSet(unit_price=price, effective_from=dt.date.today())
    except ValidationError:
        return None
    return price
