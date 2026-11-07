"""The row checks the contract leaves to the loader (MR-10 spec 8.2, 03 B.5): moved out of
loader.py unchanged, plus the purchase grain (MR-36).

A batch is rejected for an unsupported grain, rows of another grain, rows dated outside its
period, or totals that differ from its rows. A catalog has no money, units or dated rows; a
purchase batch has no sales money or units, and each invoice's date (Mexico City) must be in the
period.
"""

from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo

from mermia_contracts.batch import Grain, IssueIn, NormalizedBatch
from mermia_contracts.db.models import IssueSeverity

SUPPORTED = {
    Grain.item_daily: "item_sales",
    Grain.daily: "daily_sales",
    Grain.catalog: "recipes",
    Grain.purchase: "purchases",
}
ROW_LISTS = ("menu_items", "item_sales", "daily_sales", "tickets", "purchases", "recipes")
ALONE = (Grain.catalog, Grain.purchase)  # grains that come without menu_items
INVOICE_ZONE = ZoneInfo("America/Mexico_City")  # the CFDI parser's zone for Fecha


def _error(code: str, message_es: str) -> IssueIn:
    return IssueIn(severity=IssueSeverity.error, code=code, message_es=message_es)


def check_rows(batch: NormalizedBatch) -> list[IssueIn]:
    """Errors in the batch's rows that reject it."""
    rows_name = SUPPORTED.get(batch.grain)
    if rows_name is None:
        return [_error("batch.grain_unsupported", "Todavía no puedo cargar este tipo de reporte.")]
    reject: list[IssueIn] = []
    allowed = (rows_name,) if batch.grain in ALONE else (rows_name, "menu_items")
    if any(n not in allowed and getattr(batch, n) for n in ROW_LISTS):
        reject.append(
            _error("batch.grain_mismatch", "El archivo mezcla tipos de datos que no van juntos.")
        )
    if batch.grain == Grain.item_daily and any(
        x.period_from != x.period_to for x in batch.item_sales
    ):
        reject.append(
            _error(
                "batch.items_multi_day",
                "Necesito los productos vendidos de un solo día por archivo; este reporte "
                "cubre varios días.",
            )
        )
    lines, net, units, outside = _figures(batch)
    if outside:
        reject.append(
            _error(
                "batch.rows_outside_period", "Hay filas con fechas fuera del periodo del reporte."
            )
        )
    t = batch.totals
    if (
        t.lines != lines
        or (t.net_sales is not None and t.net_sales != net)
        or (t.units is not None and units is not None and t.units != units)
    ):
        reject.append(
            _error(
                "batch.totals_mismatch",
                "Los totales del reporte no cuadran con sus renglones; no lo cargué.",
            )
        )
    return reject


def _figures(batch: NormalizedBatch) -> tuple[int, int, Decimal | None, int]:
    """(lines, net sales, units, rows outside the period) as the batch's rows give them."""
    p = batch.period
    if batch.grain == Grain.item_daily:
        outside = sum(1 for x in batch.item_sales if x.period_from < p.from_ or x.period_to > p.to)
        return (
            len(batch.item_sales),
            sum(x.net for x in batch.item_sales),
            sum((x.units for x in batch.item_sales), Decimal(0)),
            outside,
        )
    if batch.grain == Grain.catalog:
        return len(batch.recipes), 0, None, 0
    if batch.grain == Grain.purchase:  # an invoice's lines; its money is not sales
        days = [d.issued_at.astimezone(INVOICE_ZONE).date() for d in batch.purchases]
        outside = sum(1 for day in days if not p.from_ <= day <= p.to)
        return sum(len(d.lines) for d in batch.purchases), 0, None, outside
    outside = sum(1 for x in batch.daily_sales if not p.from_ <= x.business_date <= p.to)
    return len(batch.daily_sales), sum(x.net_sales for x in batch.daily_sales), None, outside
