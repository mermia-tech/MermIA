"""CFDI 4.0 supplier invoice (factura de ingreso), the XML the SAT stamps (Anexo 20).

Input: the root element from xmldoc.parse_xml. Output: one purchase batch with one PurchaseIn
whose lines are the invoice's Conceptos. Pure: no database, no matching to ingredients (MR-36
PR B turns the lines into price proposals).

- Only CFDI 4.0, type I (ingreso), in MXN. Credit notes, payment complements, transfers, payroll,
  CFDI 3.3 and other currencies are refused with a Spanish message.
- unit_price_net is pesos per invoiced unit (ClaveUnidad), without IVA, as ValorUnitario already
  is. A line discount is netted in: (Importe - Descuento) / Cantidad, rounded once to 6 decimals.
- IVA (002) is ignored. Itemized IEPS (003) is a warning: whether it is part of the cost is for the
  accountant to confirm.
- Numbers must be written as the SAT writes them (digits and a decimal point): never guessed.
- The buyer's RFC (Receptor) is required but not returned yet: checking it against the tenant
  needs a contract field (PR B).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

from mermia_api.ingestion.errors import MalformedReport
from mermia_api.ingestion.xlsx import MAX_NUMBER
from mermia_contracts.batch import (
    Grain,
    IssueIn,
    NormalizedBatch,
    Period,
    PurchaseIn,
    PurchaseLineIn,
    SupplierIn,
    Totals,
)
from mermia_contracts.db.models import IssueSeverity, PurchaseDocKind, SourceKind, SupplierKind

PARSER = "cfdi.factura@v1"
CFDI = "{http://www.sat.gob.mx/cfd/4}"
TFD = "{http://www.sat.gob.mx/TimbreFiscalDigital}"
ANY_COMPROBANTE = re.compile(r"\{http://www\.sat\.gob\.mx/cfd/(\d+)\}Comprobante")
# Fecha has no offset; it is the issuer's local time. PROVISIONAL: Mexico City time, which is
# right for most of the country (no DST since 2022) but not for Baja California or Quintana Roo.
ZONE = ZoneInfo("America/Mexico_City")
FECHA = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
SAT_UUID = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
PLAIN = re.compile(r"\d+(\.\d+)?")  # the SAT's own pattern: no sign, comma, exponent or space
MAX_LINES = 500  # far above a real supplier invoice; bounds the work per file
PRICE = Decimal("0.000001")
CENT = Decimal("0.01")
IMPORTE_TOLERANCE = Decimal("0.01")
IEPS = "003"
OTHER_TYPES = {
    "E": "una nota de crédito (egreso)",
    "P": "un complemento de pago",
    "T": "un CFDI de traslado",
    "N": "un recibo de nómina",
}


@dataclass(frozen=True)
class _Line:
    line: PurchaseLineIn
    importe: Decimal
    descuento: Decimal
    issues: tuple[IssueIn, ...]


def matches(root: Element) -> bool:
    """Any CFDI Comprobante, so that a CFDI 3.3 is refused by name instead of as unknown."""
    return ANY_COMPROBANTE.fullmatch(root.tag) is not None


# --- reading attributes ------------------------------------------------------------------


def _required(el: Element, name: str, where: str) -> str:
    value = el.get(name)
    if value is None or not value.strip():
        raise MalformedReport(f"Falta {name} {where}.", f"missing {name} {where}")
    return value


def _decimal(el: Element, name: str, where: str, places: int) -> Decimal:
    """A non-negative amount with at most `places` decimals, written as the SAT writes it."""
    raw = _required(el, name, where)
    if not PLAIN.fullmatch(raw):
        raise MalformedReport(
            f"El valor «{raw}» de {name} {where} no está escrito como lo pide el SAT: solo "
            "dígitos y punto decimal, sin signos, comas ni espacios (por ejemplo 1250.50).",
            f"not a plain number: {name} {where} = {raw!r}",
        )
    value = Decimal(raw)
    if value >= MAX_NUMBER:
        raise MalformedReport(
            f"El valor {raw} de {name} {where} es demasiado grande.",
            f"out of range: {name} {where} = {raw!r}",
        )
    if value != value.quantize(Decimal(1).scaleb(-places)):
        raise MalformedReport(
            f"El valor {raw} de {name} {where} tiene más de {places} decimales.",
            f"more than {places} decimals: {name} {where} = {raw!r}",
        )
    return value


def _optional(el: Element, name: str, where: str, places: int) -> Decimal:
    return Decimal(0) if el.get(name) is None else _decimal(el, name, where, places)


def _cents(amount: Decimal) -> int:
    return int(amount * 100)  # amounts read with places=2 are exact centavos


def _child(root: Element, name: str) -> Element:
    el = root.find(f"{CFDI}{name}")
    if el is None:
        raise MalformedReport(f"La factura no trae el {name}.", f"no {name} element")
    return el


# --- the Comprobante ---------------------------------------------------------------------


def _check_kind(root: Element) -> None:
    m = ANY_COMPROBANTE.fullmatch(root.tag)
    version = (root.get("Version") or "").strip()
    if m is None or m[1] != "4" or version != "4.0":
        shown = f"CFDI {version}" if version else "de otra versión de CFDI"
        raise MalformedReport(
            f"Esta factura es {shown}; necesito la versión 4.0. Pídele a tu proveedor la "
            "factura en CFDI 4.0.",
            f"CFDI namespace {root.tag!r}, Version {version!r}",
        )
    tipo = _required(root, "TipoDeComprobante", "del comprobante")
    if tipo in OTHER_TYPES:
        raise MalformedReport(
            f"Este XML es {OTHER_TYPES[tipo]}. Por ahora solo leo facturas de compra (tipo I, "
            "ingreso).",
            f"TipoDeComprobante {tipo}",
        )
    if tipo != "I":
        raise MalformedReport(
            f"El TipoDeComprobante «{tipo}» de la factura no es válido.",
            f"TipoDeComprobante {tipo!r}",
        )
    moneda = _required(root, "Moneda", "del comprobante")
    if moneda != "MXN":
        raise MalformedReport(
            f"Esta factura está en {moneda}; por ahora solo leo facturas en pesos (MXN).",
            f"Moneda {moneda!r}",
        )


def _issued_at(root: Element) -> dt.datetime:
    raw = _required(root, "Fecha", "del comprobante")
    bad = MalformedReport(
        f"La Fecha de la factura «{raw}» no tiene el formato del SAT (aaaa-mm-ddThh:mm:ss).",
        f"bad Fecha {raw!r}",
    )
    if not FECHA.fullmatch(raw):
        raise bad
    try:
        return dt.datetime.fromisoformat(raw).replace(tzinfo=ZONE)
    except ValueError as e:
        raise bad from e


def _uuid(root: Element) -> UUID:
    timbre = root.find(f"{CFDI}Complemento/{TFD}TimbreFiscalDigital")
    raw = None if timbre is None else timbre.get("UUID")
    if raw is None or not raw.strip():
        raise MalformedReport(
            "Esta factura no está timbrada: no trae el Timbre Fiscal Digital con su UUID. "
            "Pídele a tu proveedor el XML timbrado por el SAT.",
            "no TimbreFiscalDigital UUID",
        )
    if not SAT_UUID.fullmatch(raw):
        raise MalformedReport(
            f"El UUID del timbre «{raw}» no es válido.", f"bad TimbreFiscalDigital UUID {raw!r}"
        )
    return UUID(raw)


def _supplier(root: Element) -> SupplierIn:
    emisor = _child(root, "Emisor")
    return SupplierIn(
        name=_required(emisor, "Nombre", "del Emisor").strip(),
        rfc=_required(emisor, "Rfc", "del Emisor").strip(),
        kind=SupplierKind.cfdi,
    )


def _require_buyer(root: Element) -> None:
    # PR B checks this RFC against the tenant's (needs PurchaseIn.buyer_rfc, a contract change).
    _required(_child(root, "Receptor"), "Rfc", "del Receptor")


# --- the Conceptos -----------------------------------------------------------------------


def _warning(code: str, message_es: str, n: int) -> IssueIn:
    return IssueIn(severity=IssueSeverity.warning, code=code, message_es=message_es, row_ref=str(n))


def _line_issues(el: Element, n: int, off_by: Decimal) -> tuple[IssueIn, ...]:
    issues: list[IssueIn] = []
    if off_by > IMPORTE_TOLERANCE:
        issues.append(
            _warning(
                "cfdi.importe_mismatch",
                f"En el concepto {n}, Cantidad por ValorUnitario no coincide con Importe.",
                n,
            )
        )
    traslados = el.iterfind(f"{CFDI}Impuestos/{CFDI}Traslados/{CFDI}Traslado")
    if any(t.get("Impuesto") == IEPS for t in traslados):
        issues.append(
            _warning(
                "cfdi.ieps_listed",
                f"El concepto {n} trae IEPS desglosado; por ahora no lo sumo al costo.",
                n,
            )
        )
    return tuple(issues)


def _line(el: Element, n: int) -> _Line:
    where = f"del concepto {n}"
    description = _required(el, "Descripcion", where).strip()
    qty = _decimal(el, "Cantidad", where, 6)
    if qty == 0:
        raise MalformedReport(
            f"La Cantidad del concepto {n} es cero.", f"zero Cantidad at concepto {n}"
        )
    unit = _required(el, "ClaveUnidad", where).strip()
    valor = _decimal(el, "ValorUnitario", where, 6)
    importe = _decimal(el, "Importe", where, 6)
    descuento = _optional(el, "Descuento", where, 6)
    if descuento > importe:
        raise MalformedReport(
            f"El Descuento del concepto {n} es mayor que su Importe.",
            f"Descuento > Importe at concepto {n}",
        )
    price = valor
    if descuento:
        price = ((importe - descuento) / qty).quantize(PRICE, ROUND_HALF_UP)
    line = PurchaseLineIn(
        description=description,
        qty=qty.quantize(PRICE),
        unit=unit,
        unit_price_net=price.quantize(PRICE),
    )
    issues = _line_issues(el, n, abs(qty * valor - importe))
    return _Line(line, importe, descuento, issues)


def _lines(root: Element) -> list[_Line]:
    conceptos = root.findall(f"{CFDI}Conceptos/{CFDI}Concepto")
    if not conceptos:
        raise MalformedReport("La factura no trae conceptos.", "no Concepto elements")
    if len(conceptos) > MAX_LINES:
        raise MalformedReport(
            f"La factura trae más de {MAX_LINES} conceptos. Envíame facturas más pequeñas.",
            f"{len(conceptos)} conceptos > {MAX_LINES}",
        )
    return [_line(el, n) for n, el in enumerate(conceptos, start=1)]


def _check_sum(given: Decimal, name: str, parts: list[Decimal], label: str) -> None:
    """The Comprobante's `name` must be the sum of the lines' amounts, rounded to centavos."""
    summed = sum(parts, Decimal(0)).quantize(CENT, ROUND_HALF_UP)
    if given != summed:
        raise MalformedReport(
            f"El {name} de la factura ({given}) no es la suma de {label} ({summed}).",
            f"{name} {given} != sum of lines {summed}",
        )


# --- the batch ---------------------------------------------------------------------------


def parse(root: Element) -> NormalizedBatch:
    _check_kind(root)
    issued_at = _issued_at(root)
    supplier = _supplier(root)
    _require_buyer(root)
    cfdi_uuid = _uuid(root)
    lines = _lines(root)
    subtotal = _decimal(root, "SubTotal", "del comprobante", 2)
    _check_sum(subtotal, "SubTotal", [x.importe for x in lines], "los Importe de los conceptos")
    descuento = _optional(root, "Descuento", "del comprobante", 2)
    _check_sum(
        descuento, "Descuento", [x.descuento for x in lines], "los descuentos de los conceptos"
    )
    total = _decimal(root, "Total", "del comprobante", 2)
    doc = PurchaseIn(
        supplier=supplier,
        kind=PurchaseDocKind.cfdi,
        cfdi_uuid=cfdi_uuid,
        issued_at=issued_at,
        subtotal=_cents(subtotal),
        total=_cents(total),
        lines=[x.line for x in lines],
    )
    day = issued_at.date()
    return NormalizedBatch(
        parser=PARSER,
        source_kind=SourceKind.cfdi,
        period=Period.model_validate({"from": day, "to": day}),
        grain=Grain.purchase,
        totals=Totals(lines=len(lines)),
        purchases=[doc],
        issues=[issue for x in lines for issue in x.issues],
    )
