"""The Spanish notes the CFDI price importer leaves on a batch (MR-36).

They are import_issue rows the manager reads (and the agent may summarize), so they name the
supplier and the ingredient by their cleaned names only: never an RFC, and never the name of a
supplier who is a person (see price_match.invoice_supplier_name).
"""

from __future__ import annotations

import datetime as dt

from mermia_api.ingestion.safe_text import shown
from mermia_contracts.batch import IssueIn
from mermia_contracts.db.models import IssueSeverity

# Decision 1 (PENDING OWNER CONFIRMATION): unmatched lines get one summary line and no action.
UNMATCHED_SEVERITY = IssueSeverity.info
MAX_LISTED = 5  # the unmatched note names this many lines, then counts the rest


def _issue(severity: IssueSeverity, code: str, message_es: str, n: int | None = None) -> IssueIn:
    row_ref = None if n is None else str(n)
    return IssueIn(severity=severity, code=code, message_es=message_es, row_ref=row_ref)


def _concepto(n: int, description: str) -> str:
    return f"El concepto {n} («{shown(description)}»)"


def _listed(names: list[str]) -> str:
    """At most MAX_LISTED names quoted, then how many more."""
    quoted = [f"«{shown(n)}»" for n in names[:MAX_LISTED]]
    rest = len(names) - len(quoted)
    if rest:
        return f"{', '.join(quoted)} y {rest} más"
    return quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} y {quoted[-1]}"


def buyer_mismatch() -> IssueIn:
    return _issue(
        IssueSeverity.error,
        "cfdi.buyer_mismatch",
        "Esta factura no está a nombre de tu restaurante: el RFC del receptor no es el tuyo. "
        "No tomé sus precios.",
    )


def tenant_rfc_missing() -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "cfdi.tenant_rfc_missing",
        "No tengo registrado el RFC de tu restaurante, así que no pude revisar que la factura "
        "esté a tu nombre.",
    )


def buyer_rfc_missing() -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "cfdi.buyer_rfc_missing",
        "La factura no trae el RFC del receptor, así que no pude revisar que esté a tu nombre.",
    )


def supplier_unknown(name: str | None) -> IssueIn:
    """`name` is None for a person (a 4-letter RFC): their name never goes in a note."""
    who = "este proveedor (persona física)" if name is None else f"«{shown(name)}»"
    return _issue(
        IssueSeverity.info,
        "cfdi.supplier_unknown",
        f"No tengo a {who} entre tus proveedores; busqué sus conceptos por nombre.",
    )


def unmatched(descriptions: list[str]) -> IssueIn:
    count = len(descriptions)
    what = "este concepto" if count == 1 else f"estos {count} conceptos"
    return _issue(
        UNMATCHED_SEVERITY,
        "cfdi.line_unmatched",
        f"No encontré en tu catálogo {what} de la factura: {_listed(descriptions)}. "
        "No tomé su precio.",
    )


def ambiguous(n: int, description: str) -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "cfdi.ingredient_ambiguous",
        f"{_concepto(n, description)} coincide con varios insumos de tu catálogo; no tomé su "
        "precio.",
        n,
    )


def pack_unknown(n: int, description: str, unit: str) -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "cfdi.unit_pack_unknown",
        f"{_concepto(n, description)} viene por «{shown(unit)}» y no sé cuánto trae cada uno; "
        "no tomé su precio.",
        n,
    )


def unit_mismatch(n: int, description: str, unit: str, ingredient: str, base_unit: str) -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "cfdi.unit_mismatch",
        f"{_concepto(n, description)} viene en «{shown(unit)}», pero «{ingredient}» se mide en "
        f"{base_unit} y no sé cómo convertirlo; no tomé su precio.",
        n,
    )


def ieps_held(n: int, description: str) -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "cfdi.ieps_held",
        f"{_concepto(n, description)} trae IEPS; no tomé su precio hasta confirmar si el IEPS es "
        "parte del costo.",
        n,
    )


def price_out_of_range(ingredient: str) -> IssueIn:
    return _issue(
        IssueSeverity.warning,
        "cfdi.price_out_of_range",
        f"El precio de «{ingredient}» en esta factura queda fuera de rango; no lo tomé.",
    )


def older_than_record(ingredient: str, invoice_day: dt.date, record_day: dt.date) -> IssueIn:
    return _issue(
        IssueSeverity.info,
        "cfdi.price_older",
        f"El precio de «{ingredient}» de esta factura ({invoice_day:%d/%m/%Y}) es anterior al "
        f"que ya tengo (del {record_day:%d/%m/%Y}); no lo cambié.",
    )


def newer_pending(ingredient: str, pending_at: dt.datetime) -> IssueIn:
    """`pending_at` is the newer invoice's date and time, in Mexico City."""
    return _issue(
        IssueSeverity.warning,
        "cfdi.newer_pending",
        f"Ya hay un cambio de precio pendiente para «{ingredient}» de una factura más reciente "
        f"({pending_at:%d/%m/%Y %H:%M}); no lo reemplacé.",
    )


def pending_replaced(ingredient: str, kept_current: bool) -> IssueIn:
    instead = (
        "lo descarté porque esta factura trae el precio actual."
        if kept_current
        else "lo reemplacé por el de esta factura."
    )
    return _issue(
        IssueSeverity.info,
        "cfdi.pending_replaced",
        f"Ya había un cambio de precio pendiente para «{ingredient}»; {instead}",
    )
