"""Reading SR Excel exports: open a workbook from bytes and normalize cell values."""

from __future__ import annotations

import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import MalformedReport, UnreadableFile

Row = tuple[Any, ...]

MAX_BYTES = 10 * 1024 * 1024  # an SR report for one location and period is far smaller
MAX_NUMBER = Decimal(10) ** 12  # fits Quantity (12 integer digits) and Cents (bigint) alike
# A comma in a text number is read only as a thousands separator in a full grouping (1,250.5).
# Anything else ("0,075", "1,5") may be a decimal comma: refused, never guessed (x1000 off).
THOUSANDS = re.compile(r"[+-]?[1-9]\d{0,2}(,\d{3})+(\.\d+)?")


def open_workbook(data: bytes) -> Workbook:
    """The workbook in `data`, values only. Old .xls files (SR 8 can export them) are not read
    yet."""
    if len(data) > MAX_BYTES:
        raise UnreadableFile(
            "El archivo es demasiado grande para un reporte diario. Envíame el reporte de un "
            "solo periodo.",
            f"{len(data)} bytes > {MAX_BYTES}",
        )
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        # OLE2: an old .xls, or an .xlsx protected with a password
        raise UnreadableFile(
            "Recibí un Excel antiguo (.xls) o protegido con contraseña. Por ahora necesito el "
            "reporte como .xlsx sin contraseña: en Soft Restaurant, expórtalo a Excel 2007 o "
            "posterior.",
            "OLE2 container (.xls or encrypted .xlsx)",
        )
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # zip, XML or openpyxl errors: a file we cannot read
        raise UnreadableFile(
            "No pude abrir el archivo. Envíamelo en Excel (.xlsx): el reporte de Soft Restaurant "
            "o la plantilla de recetas.",
            f"{type(e).__name__}: {e}",
        ) from e


def rows(wb: Workbook, sheet: str, max_row: int | None = None) -> list[Row]:
    return [tuple(r) for r in wb[sheet].iter_rows(max_row=max_row, values_only=True)]


def norm(value: Any) -> str:
    """Text for matching headers: no accents, lower case, single spaces."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def text(value: Any) -> str | None:
    """A text cell as given, trimmed; None when blank."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _without_thousands(s: str, where: str) -> str:
    if "," not in s:
        return s
    if THOUSANDS.fullmatch(s):
        return s.replace(",", "")
    if any(c in s for c in "$()"):
        raise MalformedReport(
            f"El valor «{s}» en {where} tiene signo de pesos o paréntesis. Envíame el archivo "
            "con números sin formato (por ejemplo 1250.50 o -1250).",
            f"currency sign or parentheses in a number at {where}: {s!r}",
        )
    raise MalformedReport(
        f"El valor «{s}» en {where} tiene una coma que no es separador de miles; no sé si es "
        "decimal. Envíame el archivo con punto decimal (por ejemplo 0.075).",
        f"ambiguous comma in a number at {where}: {s!r}",
    )


def number(value: Any, where: str) -> Decimal:
    """An exact decimal from a numeric cell. Floats go through their shortest repr (0.1 -> 0.1)."""
    if isinstance(value, bool) or value is None:
        raise MalformedReport(
            f"Falta un número en {where}.", f"expected a number at {where}, got {value!r}"
        )
    try:
        if isinstance(value, int | Decimal):
            d = Decimal(value)
        elif isinstance(value, float):
            # 15 significant digits, Excel's precision: 284.84999999999997 is 284.85
            d = Decimal(f"{value:.15g}")
        else:
            d = Decimal(_without_thousands(str(value).strip(), where))
    except InvalidOperation as e:
        raise MalformedReport(
            f"El valor «{value}» en {where} no es un número.",
            f"not a number at {where}: {value!r}",
        ) from e
    if not d.is_finite() or abs(d) >= MAX_NUMBER:
        raise MalformedReport(
            f"El valor «{value}» en {where} no es un número válido.",
            f"non-finite or out-of-range number at {where}: {value!r}",
        )
    return d


def centavos(value: Any, where: str) -> int:
    """Pesos in a cell as integer centavos. More than 2 decimals is an error, never rounded away."""
    cents = number(value, where) * 100
    if cents != cents.to_integral_value():
        raise MalformedReport(
            f"El importe {value} en {where} tiene más de dos decimales.",
            f"amount with more than 2 decimals at {where}: {value!r}",
        )
    return int(cents)
