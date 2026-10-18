"""Types and nullability of NormalizedBatch and its input types (spec 10.3)."""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from mermia_contracts.batch import (
    DailySalesIn,
    ItemSalesIn,
    NormalizedBatch,
    PaymentIn,
    PurchaseLineIn,
    RecipeIn,
    RecipeLineIn,
    TicketIn,
)

D = dt.date(2026, 10, 12)
NOW = dt.datetime(2026, 10, 12, 12, 0, tzinfo=dt.UTC)


def batch_kwargs(**over):
    base = {
        "parser": "sr.example@v1",
        "source_kind": "sr_report",
        "period": {"from": D, "to": D},
        "grain": "item_daily",
        "totals": {"lines": 0},
    }
    return {**base, **over}


def item_sales(**over):
    base = {
        "item_name": "Taco",
        "period_from": D,
        "period_to": D,
        "units": Decimal(1),
        "gross": 100,
        "discount": 0,
        "net": 100,
    }
    return {**base, **over}


def test_minimal_batch_defaults() -> None:
    batch = NormalizedBatch(**batch_kwargs())
    assert batch.contract_version == 1
    assert batch.quality.value == "file"
    assert batch.location_hint is None
    for name in (
        "menu_items",
        "item_sales",
        "daily_sales",
        "tickets",
        "purchases",
        "recipes",
        "issues",
    ):
        assert getattr(batch, name) == []


@pytest.mark.parametrize("bad", [12.5, "100", True, None])
def test_cents_reject_floats_strings_bools_and_null(bad) -> None:
    with pytest.raises(ValidationError):
        ItemSalesIn(**item_sales(gross=bad))


def test_cents_accept_negative_values_for_refunds() -> None:
    assert ItemSalesIn(**item_sales(net=-500)).net == -500


@pytest.mark.parametrize("bad", [1.5, 2, "1.5"])
def test_quantities_require_decimal_in_python_mode(bad) -> None:
    with pytest.raises(ValidationError):
        ItemSalesIn(**item_sales(units=bad))


def test_quantity_scale_and_precision_are_enforced() -> None:
    assert ItemSalesIn(**item_sales(units=Decimal("1.123456"))).units == Decimal(
        "1.123456"
    )
    with pytest.raises(ValidationError):
        ItemSalesIn(**item_sales(units=Decimal("1.1234567")))
    with pytest.raises(ValidationError):
        ItemSalesIn(**item_sales(units=Decimal("1" * 13)))  # 13 integer digits > 12


def test_unit_price_keeps_six_decimals_and_percent_points_four() -> None:
    line = PurchaseLineIn(
        description="PASTOR KG",
        qty=Decimal(5),
        unit="KGM",
        unit_price_net=Decimal("200.123456"),
    )
    assert line.unit_price_net == Decimal("200.123456")
    with pytest.raises(ValidationError):
        PurchaseLineIn(
            description="x",
            qty=Decimal(1),
            unit="KGM",
            unit_price_net=Decimal("1.1234567"),
        )
    ok = RecipeLineIn(
        ingredient_name="a",
        qty_base=Decimal(1),
        unit="g",
        yield_override_pct=Decimal("85.5"),
    )
    assert ok.yield_override_pct == Decimal("85.5")
    with pytest.raises(ValidationError):
        RecipeLineIn(
            ingredient_name="a",
            qty_base=Decimal(1),
            unit="g",
            yield_override_pct=Decimal("1.12345"),
        )


def test_instants_must_carry_a_time_zone() -> None:
    kwargs = {
        "external_id": "N-1",
        "business_date": D,
        "subtotal": 1,
        "total": 1,
        "status": "paid",
        "opened_at": NOW,
    }
    TicketIn(**kwargs)
    with pytest.raises(ValidationError):
        TicketIn(**{**kwargs, "opened_at": dt.datetime(2026, 10, 12, 12, 0)})


def test_ticket_closed_before_opened_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TicketIn(
            external_id="N-1",
            business_date=D,
            subtotal=1,
            total=1,
            status="paid",
            opened_at=NOW,
            closed_at=NOW - dt.timedelta(minutes=1),
        )


def test_blank_required_text_is_rejected_like_the_database_does() -> None:
    with pytest.raises(ValidationError):
        ItemSalesIn(**item_sales(item_name="   "))
    with pytest.raises(ValidationError):
        RecipeIn(menu_item_name="", yield_qty=Decimal(1), lines=[])
    assert ItemSalesIn(**item_sales(item_external_id=None)).item_external_id is None


def test_optional_fields_accept_none_and_omission() -> None:
    daily = DailySalesIn(business_date=D, net_sales=100)
    for name in (
        "tax",
        "tickets",
        "guests",
        "discounts",
        "cancellations_amount",
        "cancellations_count",
        "tips",
    ):
        assert getattr(daily, name) is None, name
    assert daily.payment_mix == {}


def test_required_fields_are_required() -> None:
    with pytest.raises(ValidationError):
        DailySalesIn(business_date=D)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        PaymentIn(method="cash")  # type: ignore[call-arg]


def test_counts_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        DailySalesIn(business_date=D, net_sales=1, tickets=-1)
    with pytest.raises(ValidationError):
        NormalizedBatch(**batch_kwargs(totals={"lines": -1}))


def test_a_recipe_needs_at_least_one_line() -> None:
    with pytest.raises(ValidationError):
        RecipeIn(menu_item_name="Taco", yield_qty=Decimal(1), lines=[])
