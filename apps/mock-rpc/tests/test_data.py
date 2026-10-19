from decimal import Decimal

from mermia_mock_rpc import data


def test_money_formats_centavos() -> None:
    assert data.money(18432050) == "$184,320.50"


def test_pct_signed() -> None:
    assert data.pct(Decimal("7.2"), signed=True) == "+7.2%"


def test_centro_week_total_matches_expected() -> None:
    rows = [
        r
        for r in data.table("daily_sales_agg")
        if r["location_id"] == data.LOCATIONS["L1"]
        and "2026-10-05" <= r["business_date"] <= "2026-10-11"
    ]
    assert sum(r["net_sales"] for r in rows) == 18432050


def test_signed_money_shows_the_sign_of_a_change() -> None:
    assert data.money(1241550, signed=True) == "+$12,415.50"
    assert data.money(-2339970, signed=True) == "-$23,399.70"
    assert data.money(0, signed=True) == "$0.00"
