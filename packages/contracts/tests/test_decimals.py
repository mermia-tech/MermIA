"""Decimal inputs (decimals.py): what each input type does in Python mode and in JSON mode.

The Python column matters because LLM tool input and HTTP clients hand over `json.loads` output.
"""

import json
import random
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.batch import Model
from mermia_contracts.decimals import (
    FigureRaw,
    PercentPoints,
    Quantity,
    UnitPricePerBaseUnit,
    exact_json,
)
from mermia_contracts.rpc import Money


class Price(Model):
    x: UnitPricePerBaseUnit  # numeric(20,6)


D = Decimal
OK = "ok"
NO = "rejected"

PYTHON_CASES: list[tuple[Any, Any]] = [
    (D("220.5"), D("220.5")),
    (D("220.50"), D("220.50")),  # trailing zeros survive: nothing is rounded or normalised
    (220, D("220")),
    (-3, D("-3")),
    (220.5, D("220.5")),
    (0.1, D("0.1")),  # the decimal written, not the binary expansion 0.1000000000000000055...
    (0.22, D("0.22")),
    ("220.5", D("220.5")),
    ("-0.22", D("-0.22")),
    ("12345678901234.123456", D("12345678901234.123456")),  # 20 digits, exact
    (D("12345678901234.123456"), D("12345678901234.123456")),
    (True, NO),
    (None, NO),
    ("1e3", NO),
    (" 1", NO),
    ("", NO),
    ("abc", NO),
    (b"1", NO),
    ([1], NO),
    (0.30000000000000004, NO),  # float artifact: 17 significant digits
    (12345678901234.123456, NO),  # a float cannot carry 20 digits: send a Decimal or a string
    (float("nan"), NO),
    (float("inf"), NO),
    (D("NaN"), NO),
    (D("1.0000001"), NO),  # 7 decimal places
    (1.0000001, NO),
    (D("123456789012345.1"), NO),  # 15 whole digits > 14
]


@pytest.mark.parametrize("given,expected", PYTHON_CASES, ids=lambda v: repr(v)[:40])
def test_python_mode(given: Any, expected: Any) -> None:
    if expected == NO:
        with pytest.raises(ValidationError):
            Price.model_validate({"x": given})
        return
    result = Price.model_validate({"x": given}).x
    assert result == expected
    assert str(result) == str(expected)  # same digits, same exponent


JSON_CASES: list[tuple[str, Any]] = [
    ("220", D("220")),
    ("220.5", D("220.5")),
    ("220.50", D("220.5")),  # trailing zeros are not kept in JSON numbers (same value)
    ("0.1", D("0.1")),
    ('"220.5"', D("220.5")),
    ("1234567890.123456", NO),  # valid, but 16 digits: a float cannot vouch for it (use a string)
    ('"12345678901234.123456"', D("12345678901234.123456")),  # strings are always exact
    ("true", NO),
    ("null", NO),
    ('"abc"', NO),
    ("[1]", NO),
    ("0.30000000000000004", NO),  # more than 6 decimal places
    ("1.0000001", NO),
    ("123456789012345.1", NO),
]


@pytest.mark.parametrize("text,expected", JSON_CASES)
def test_json_mode(text: str, expected: Any) -> None:
    body = '{"x": ' + text + "}"
    if expected == NO:
        with pytest.raises(ValidationError):
            Price.model_validate_json(body)
        return
    result = Price.model_validate_json(body).x
    assert result == expected


SAFE_NUMBERS = [
    given
    for given, expected in PYTHON_CASES
    if expected != NO
    and isinstance(given, int | Decimal)
    and not isinstance(given, bool)
    and len(str(given).replace(".", "")) <= 15  # beyond that a JSON number is not exact
]


@pytest.mark.parametrize("given", SAFE_NUMBERS, ids=repr)
def test_both_modes_agree_on_exact_numbers(given: Any) -> None:
    """The same number, spelled as JSON or handed over in Python, gives the same value."""
    body = '{"x": ' + str(given) + "}"
    assert Price.model_validate_json(body).x == Price.model_validate({"x": given}).x


@pytest.mark.parametrize("type_", [PercentPoints, Quantity, FigureRaw, UnitPricePerBaseUnit])
def test_every_decimal_type_takes_parsed_json_numbers(type_: Any) -> None:
    class One(Model):
        x: type_

    assert One.model_validate({"x": 7}).x == D("7")
    assert One.model_validate({"x": 7.5}).x == D("7.5")
    assert One.model_validate_json('{"x": 7.5}').x == D("7.5")


def test_digit_limits_are_per_type() -> None:
    class Pct(Model):
        x: PercentPoints  # numeric(7,4)

    assert Pct.model_validate({"x": "999.9999"}).x == D("999.9999")
    for too_much in ("999.99999", "1000.0000"):
        with pytest.raises(ValidationError):
            Pct.model_validate({"x": too_much})


@pytest.mark.parametrize("given", [100.0, "100", True, None, 1.5])
def test_money_stays_strict_in_python_mode(given: Any) -> None:
    """Centavos are integers: a float, a string or a bool is never accepted as money."""
    with pytest.raises(ValidationError):
        Money.model_validate({"raw": given, "text": "x"})


@pytest.mark.parametrize("text", ["100.0", '"100"', "true", "null", "1.5"])
def test_money_stays_strict_in_json_mode(text: str) -> None:
    with pytest.raises(ValidationError):
        Money.model_validate_json('{"raw": ' + text + ', "text": "x"}')


# --- precision policy: a JSON number is read exactly or rejected, never altered --------------


def _literals(rng: random.Random, count: int) -> list[str]:
    """Decimal literals with at most 6 decimals (the database range), small to 10**14."""
    out = []
    for _ in range(count):
        whole = int(10 ** rng.uniform(0, 14))
        decimals = rng.choice([0, 1, 2, 3, 6])
        frac = rng.randrange(10**decimals) if decimals else 0
        out.append(f"{whole}.{frac:0{decimals}d}" if decimals else str(whole))
    return out


def _reads(literal: str) -> tuple[Decimal | None, Decimal | None]:
    """The value each entry point reads from `{"x": literal}`, or None when it rejects it."""
    body = '{"x": ' + literal + "}"
    out: list[Decimal | None] = []
    for read in (Price.model_validate_json, lambda text: Price.model_validate(json.loads(text))):
        try:
            out.append(read(body).x)
        except ValidationError:
            out.append(None)
    return out[0], out[1]


def test_a_json_number_is_exact_or_rejected_never_altered() -> None:
    """50 000 random literals, both entry points: the value read equals the literal or fails."""
    rng = random.Random(20261018)
    literals = _literals(rng, 50_000)
    literals += [  # around the float limits
        f"{(2**33) + k}.{rng.randrange(10**6):06d}" for k in range(-50, 50)
    ] + ["999999999999999.9", "12345678901234.100001", "8589934591.999999", "8589934592.000001"]
    accepted = 0
    for literal in literals:
        from_text, from_dict = _reads(literal)
        for got in (from_text, from_dict):
            assert got is None or got == D(literal), (literal, got)
        accepted += from_text is not None
    assert accepted > 25_000  # the guard is not just rejecting everything


@pytest.mark.parametrize(
    "literal",
    ["12345678901.123456", "12345678901234.100001", "123456789012345.5", "8589934592.5"],
)
def test_literals_a_float_cannot_hold_are_rejected_as_json_numbers(literal: str) -> None:
    with pytest.raises(ValidationError):
        Price.model_validate_json('{"x": ' + literal + "}")
    with pytest.raises(ValidationError):
        Price.model_validate(json.loads('{"x": ' + literal + "}"))


@pytest.mark.parametrize(
    "literal",
    [
        "12345678901.123456",
        "12345678901234.123456",
        "12345678901234.100001",
        "99999999999999.999999",
    ],
)
def test_the_same_values_are_exact_as_strings_and_through_exact_json(literal: str) -> None:
    assert Price.model_validate_json('{"x": "' + literal + '"}').x == D(literal)
    assert Price.model_validate({"x": literal}).x == D(literal)
    assert Price.model_validate(exact_json('{"x": ' + literal + "}")).x == D(literal)


def test_exact_json_still_enforces_the_database_range() -> None:
    for too_long in ("1.0000001", "123456789012345.1"):
        with pytest.raises(ValidationError):
            Price.model_validate(exact_json('{"x": ' + too_long + "}"))


def test_residual_extra_decimals_below_float_resolution_collapse() -> None:
    """The one case not caught (the policy's stated limit), outside the database range.

    A JSON number with more decimals than the type allows can collapse to the nearest float
    and be accepted as the short value; exact_json and strings reject it. The difference is
    below 1e-15, and no valid value (at most 6 decimals) is affected: see the test above.
    """
    literal = "0.1000000000000000001"
    assert Price.model_validate_json('{"x": ' + literal + "}").x == D("0.1")
    with pytest.raises(ValidationError):
        Price.model_validate(exact_json('{"x": ' + literal + "}"))
    with pytest.raises(ValidationError):
        Price.model_validate_json('{"x": "' + literal + '"}')
