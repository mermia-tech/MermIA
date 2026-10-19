"""Reading SR Excel exports: open a workbook from bytes and normalize cell values."""

from __future__ import annotations

import io
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

from mermia_api.ingestion.errors import MalformedReport, UnreadableFile

Row = tuple[Any, ...]


def open_workbook(data: bytes) -> Workbook:
    """The workbook in `data`, values only. Old .xls files (SR 8 can export them) are not read
    yet."""
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise UnreadableFile(
            "Recibí un archivo de Excel antiguo (.xls). Por ahora necesito el reporte guardado "
            "como .xlsx: en Soft Restaurant, expórtalo a Excel 2007 o posterior.",
            "legacy .xls (OLE2) file",
        )
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
        raise UnreadableFile(
            "No pude abrir el archivo. Envíame el reporte de Soft Restaurant en Excel (.xlsx).",
            f"{type(e).__name__}: {e}",
        ) from e


def rows(wb: Workbook, sheet: str) -> list[Row]:
    return [tuple(r) for r in wb[sheet].iter_rows(values_only=True)]


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


def number(value: Any, where: str) -> Decimal:
    """An exact decimal from a numeric cell. Floats go through their shortest repr (0.1 -> 0.1)."""
    if isinstance(value, bool) or value is None:
        raise MalformedReport(
            f"Falta un número en {where}.", f"expected a number at {where}, got {value!r}"
        )
    if isinstance(value, int | Decimal):
        return Decimal(value)
    try:
        return Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value).strip())
    except InvalidOperation as e:
        raise MalformedReport(
            f"El valor «{value}» en {where} no es un número.",
            f"not a number at {where}: {value!r}",
        ) from e


def centavos(value: Any, where: str) -> int:
    """Pesos in a cell as integer centavos. More than 2 decimals is an error, never rounded away."""
    cents = number(value, where) * 100
    if cents != cents.to_integral_value():
        raise MalformedReport(
            f"El importe {value} en {where} tiene más de dos decimales.",
            f"amount with more than 2 decimals at {where}: {value!r}",
        )
    return int(cents)
