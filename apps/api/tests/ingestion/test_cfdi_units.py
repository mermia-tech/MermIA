"""MR-36: base units in one invoiced unit of a CFDI line. No database."""

from decimal import Decimal

import pytest

from mermia_api.ingestion.cfdi_units import (
    PACK_UNKNOWN,
    UNIT_MISMATCH,
    Pack,
    UnitHeld,
    base_per_unit,
    normalized_conversions,
)

KG_G = {("kg", "g"): Decimal(1000)}


@pytest.mark.parametrize(
    ("clave", "base", "expected"),
    [
        ("KGM", "g", Decimal(1000)),
        ("GRM", "g", Decimal(1)),
        ("LTR", "ml", Decimal(1000)),
        ("MLT", "ml", Decimal(1)),
        ("H87", "pza", Decimal(1)),
        ("EA", "pza", Decimal(1)),
        ("XUN", "pza", Decimal(1)),
        (" kgm ", "g", Decimal(1000)),
    ],
)
def test_sat_measurement_units_convert_to_the_base_unit(
    clave: str, base: str, expected: Decimal
) -> None:
    assert base_per_unit(clave, base, None, {}) == expected


def test_a_box_without_pack_size_is_held() -> None:
    with pytest.raises(UnitHeld) as e:
        base_per_unit("XBX", "g", None, {})
    assert e.value.code == PACK_UNKNOWN


@pytest.mark.parametrize("unit", ["caja", "kgs", ""])
def test_a_pack_in_an_unknown_unit_is_held(unit: str) -> None:
    with pytest.raises(UnitHeld) as e:
        base_per_unit("XBX", "g", Pack(Decimal(12), unit), {})
    assert e.value.code == PACK_UNKNOWN


def test_a_pack_of_zero_is_held() -> None:
    with pytest.raises(UnitHeld) as e:
        base_per_unit("XBX", "pza", Pack(Decimal(0), "pza"), {})
    assert e.value.code == PACK_UNKNOWN


@pytest.mark.parametrize(
    ("pack", "base", "expected"),
    [
        (Pack(Decimal(12), "pza"), "pza", Decimal(12)),
        (Pack(Decimal("2.5"), "kg"), "g", Decimal(2500)),
        (Pack(Decimal(24), "H87"), "pza", Decimal(24)),
        (Pack(Decimal(6), "L"), "ml", Decimal(6000)),
    ],
)
def test_a_pack_with_its_size_converts(pack: Pack, base: str, expected: Decimal) -> None:
    assert base_per_unit("XBX", base, pack, {}) == expected


@pytest.mark.parametrize(
    ("clave", "base", "expected"),
    [
        ("KGM", "g", Decimal(1000)),
        ("GRM", "g", Decimal(1)),
        ("LTR", "ml", Decimal(1000)),
        ("MLT", "ml", Decimal(1)),
    ],
)
def test_a_pack_is_ignored_for_a_sat_measurement_unit(
    clave: str, base: str, expected: Decimal
) -> None:
    assert base_per_unit(clave, base, Pack(Decimal(12), "pza"), {}) == expected


@pytest.mark.parametrize("clave", ["H87", "EA", "XUN"])
def test_a_piece_uses_the_alias_pack_in_pieces(clave: str) -> None:
    assert base_per_unit(clave, "pza", Pack(Decimal(180), "pza"), {}) == Decimal(180)


def test_a_piece_uses_the_alias_pack_in_grams() -> None:
    assert base_per_unit("H87", "g", Pack(Decimal(1), "kg"), {}) == Decimal(1000)


def test_a_piece_with_an_unreadable_pack_is_held() -> None:
    with pytest.raises(UnitHeld) as e:
        base_per_unit("H87", "pza", Pack(Decimal(12), "caja"), {})
    assert e.value.code == PACK_UNKNOWN


def test_a_piece_without_a_pack_of_a_grams_ingredient_needs_a_conversion() -> None:
    with pytest.raises(UnitHeld) as e:
        base_per_unit("H87", "g", None, KG_G)
    assert e.value.code == UNIT_MISMATCH


def test_kilos_of_a_pieces_ingredient_need_a_conversion() -> None:
    with pytest.raises(UnitHeld) as e:
        base_per_unit("KGM", "pza", None, KG_G)
    assert e.value.code == UNIT_MISMATCH


def test_a_conversion_from_the_large_unit_bridges_kinds() -> None:
    eggs = {("kg", "pza"): Decimal(16)}
    assert base_per_unit("KGM", "pza", None, eggs) == Decimal(16)
    assert base_per_unit("GRM", "pza", None, eggs) == Decimal("0.016")


def test_a_conversion_from_the_small_unit_bridges_kinds() -> None:
    eggs = {("g", "pza"): Decimal("0.016")}
    assert base_per_unit("KGM", "pza", None, eggs) == Decimal(16)


def test_a_zero_conversion_is_not_used() -> None:
    with pytest.raises(UnitHeld):
        base_per_unit("KGM", "pza", None, {("kg", "pza"): Decimal(0)})


def test_normalized_conversions_keep_known_units_and_let_later_rows_win() -> None:
    rows = [
        ("kg", "g", Decimal(1000)),
        ("KG", "PZA", Decimal(15)),
        ("caja", "pza", Decimal(12)),
        ("kg", "pza", Decimal(16)),
    ]
    assert normalized_conversions(rows) == {("kg", "g"): Decimal(1000), ("kg", "pza"): Decimal(16)}
