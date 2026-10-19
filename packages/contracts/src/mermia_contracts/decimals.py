"""Decimal types for the MR-11 contracts: exact or rejected, never silently altered.

batch.py declares strict `Decimal` fields. In Python mode they accept only `Decimal` instances,
and in JSON mode pydantic reads every JSON number through a float64, so a literal such as
`12345678901.123456` was silently altered. These types put one conversion in front of the same
strict schema (same `max_digits` and `decimal_places`), for Python input and for JSON input:

- `Decimal`: as is.
- `int` (not `bool`): exact.
- `str` like `-12.50`: exact, full database precision (no exponent, no spaces).
- `float` (what `json.loads` gives for a JSON number, and what pydantic hands over for one):
  accepted only if its shortest repr has at most 15 significant digits AND its magnitude is
  below 2**33 (about 8.6 billion). A decimal with at most 15 digits survives decimal -> float ->
  decimal, and below 2**33 two different 6-decimal values can never share a float64 (the spacing
  of floats there is under 2e-6), so a valid value is read exactly or rejected. Larger or longer
  numbers must come as an `int`, a `Decimal` or a string.
- anything else (`bool`, `None`, `nan`, `inf`): rejected.

Residual, outside the database range: a JSON number with MORE decimals than the type allows
(for example `0.1000000000000000001`) can collapse to the nearest float (`0.1`) and be accepted
instead of rejected; the difference is below 1e-15. Use `exact_json` to parse text without
floats, which also rejects it.
"""

import json
import re
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field
from pydantic_core import core_schema

_PLAIN = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_FLOAT_DIGITS = 15  # DBL_DIG: a decimal with this many digits survives decimal -> float -> decimal
_FLOAT_LIMIT = 2.0**33  # below it, float64 spacing is under 2e-6: 6-decimal values stay distinct


def _from_python(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("a bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if abs(value) >= _FLOAT_LIMIT:
            raise ValueError("float of 2**33 or more: send an int, a Decimal or a string")
        exact = Decimal(repr(value))
        if len(exact.as_tuple().digits) > _FLOAT_DIGITS:
            raise ValueError(
                f"float with over {_FLOAT_DIGITS} significant digits: send a Decimal or a string"
            )
        return exact
    if isinstance(value, str) and _PLAIN.fullmatch(value):
        return Decimal(value)
    return value  # Decimal passes; the strict schema rejects everything else


class _Exact:
    def __init__(self, max_digits: int, decimal_places: int) -> None:
        self.max_digits = max_digits
        self.decimal_places = decimal_places

    def __get_pydantic_core_schema__(self, source: Any, handler: Any) -> core_schema.CoreSchema:
        exact = core_schema.decimal_schema(
            max_digits=self.max_digits, decimal_places=self.decimal_places, strict=True
        )
        return core_schema.no_info_before_validator_function(_from_python, exact)


PercentPoints = Annotated[Decimal, _Exact(7, 4), Field(description="unit=percent_points")]
"""A percentage stored in a `numeric(7,4)` column: keeps the column's limit (999.9999)."""
ComputedPercent = Annotated[
    Decimal, _Exact(14, 4), Field(description="unit=percent_points (calculated, 4 decimals)")
]
"""A percentage the metric layer calculates for an RPC result. Ten whole digits, so a change such
as 1 to 15 units (+1400) fits; it never reaches a column, which is why it is not PercentPoints."""
Quantity = Annotated[Decimal, _Exact(18, 6), Field(description="unit=quantity")]
UnitPricePerBaseUnit = Annotated[
    Decimal,
    _Exact(20, 6),
    Field(description="unit=pesos_per_base_unit (g, ml or pza), never per purchase unit"),
]
FigureRaw = Annotated[Decimal, _Exact(24, 6)]
"""The raw value of a Figure: its unit depends on the metric asked for."""


def exact_json(text: str) -> Any:
    """Parse JSON without float64: every JSON number with a fraction becomes a `Decimal`.

    Validate the result in Python mode (`Model.model_validate(exact_json(text))`) to read values
    of any length in the database range exactly.
    """
    return json.loads(text, parse_float=Decimal)
