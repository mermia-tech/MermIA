"""MR-30: one canonical phone and WhatsApp id, so the script and MR-27's sender lookup agree."""

import pytest

from mermia_api.phone import canonical_phone, canonical_wa_id, wa_id


@pytest.mark.parametrize(
    "raw",
    [
        "+525512345001",
        "+52 55 1234 5001",
        "+52 1 55 1234 5001",
        "+5215512345001",
        "+52 (55) 1234-5001",
    ],
)
def test_mexican_numbers_drop_the_old_mobile_1(raw: str) -> None:
    assert canonical_phone(raw) == "+525512345001"


def test_other_countries_are_kept_as_written() -> None:
    assert canonical_phone("+1 415 555 0100") == "+14155550100"


@pytest.mark.parametrize(
    "raw", ["5512345001", "+52 55 abc", "+52 55 1234 500", "+52 55 1234 50011"]
)
def test_bad_numbers_are_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="phone"):
        canonical_phone(raw)


def test_wa_id_is_the_canonical_number_without_plus() -> None:
    assert wa_id("+525512345001") == "525512345001"


def test_a_webhook_wa_id_with_521_maps_to_the_stored_external_id() -> None:
    """What MR-27 does with an incoming wa_id before looking up channel_identity."""
    assert canonical_wa_id("5215512345001") == wa_id(canonical_phone("+52 55 1234 5001"))
