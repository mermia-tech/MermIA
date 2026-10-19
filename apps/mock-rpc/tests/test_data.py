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
