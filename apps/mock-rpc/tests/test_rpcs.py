from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter

from mermia_contracts.rpc import RPCS, RpcEnvelope
from mermia_mock_rpc import data, rpcs

CASES = [
    (name, variant) for name, variants in rpcs.VARIANTS.items() for variant in (None, *variants)
]


def _data(name: str, variant: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = rpcs.build(name, variant)["data"]
    return out


def test_the_registry_covers_the_eleven_rpcs() -> None:
    assert list(rpcs.VARIANTS) == list(RPCS) == list(rpcs.CANONICAL)


@pytest.mark.parametrize(("name", "variant"), CASES, ids=lambda v: str(v))
def test_every_answer_is_valid_c3(name: str, variant: str | None) -> None:
    RPCS[name].args.model_validate(rpcs.CANONICAL[name])
    TypeAdapter(RpcEnvelope[RPCS[name].data]).validate_python(rpcs.build(name, variant))  # type: ignore[misc,arg-type]


@pytest.mark.parametrize("name", list(RPCS))
def test_error_variant_has_no_data(name: str) -> None:
    envelope = rpcs.build(name, "error")
    assert envelope["ok"] is False
    assert envelope.get("data") is None


def test_sales_summary_is_centro_last_week() -> None:
    d = _data("get_sales_summary")
    assert d["net_sales"] == {"raw": 18432050, "text": "$184,320.50"}
    assert d["change_vs_previous"]["text"] == "+7.2%"


def test_nulls_variant_is_synthetic_and_says_so() -> None:
    envelope = rpcs.build("get_sales_summary", "nulls")
    assert envelope["data"]["tickets"] is None
    assert "synthetic" in envelope["flags"][0]["message"]


def test_compare_periods_is_centro_against_the_week_before() -> None:
    d = _data("compare_periods")
    assert (d["a"]["raw"], d["b"]["raw"]) == (18432050, 17190500)


def test_changes_between_figures_carry_their_sign() -> None:
    assert _data("compare_periods")["abs_change"]["text"] == "+$12,415.50"
    assert _data("compare_locations")["rows"][1]["diff_vs_best"]["text"] == "-$23,399.70"


def test_compare_locations_ranks_centro_first() -> None:
    rows = _data("compare_locations")["rows"]
    assert [r["name"] for r in rows] == ["Centro", "Polanco"]
    assert rows[0]["value"]["raw"] == 18432050


def test_top_dishes_this_month() -> None:
    rows = _data("get_top_dishes")["rows"]
    assert rows[0]["name"] == "Tacos al pastor (orden de 3)"
    assert rows[0]["value"]["raw"] == 1208


def test_payment_breakdown_adds_up_and_has_no_tickets() -> None:
    d = _data("get_sales_breakdown")
    assert d["by"] == "payment_method"
    assert all(r["tickets"] is None for r in d["rows"])
    day = next(
        r
        for r in data.table("daily_sales_agg")
        if r["location_id"] == data.LOCATIONS["L1"] and r["business_date"] == "2026-10-11"
    )
    assert sum(r["net_sales"]["raw"] for r in d["rows"]) == day["net_sales"]


def test_no_tickets_variant_is_by_category() -> None:
    assert _data("get_sales_breakdown", "no_tickets")["by"] == "category"


def test_cancellation_saturday() -> None:
    d = _data("get_cancellations")
    assert (d["count"], d["amount"]["raw"]) == (17, 265500)
    assert {k: v for k, v in d["by_staff"][0].items() if k in ("name", "count")} == {
        "name": "Pepe",
        "count": 8,
    }


def test_pastor_margin_is_on_the_net_price() -> None:
    d = _data("get_dish_margin")
    assert d["match"] == "resolved"
    assert (d["cost"]["raw"], d["net_price"]["raw"], d["margin"]["raw"]) == (1840, 5603, 3763)
    assert d["margin_pct"]["text"] == "67.2%"
    assert d["food_cost"]["text"] == "32.8%"
    assert Decimal(str(d["margin_pct"]["raw"])) + Decimal(str(d["food_cost"]["raw"])) == 100


def test_dish_margin_ambiguous_and_needs_location() -> None:
    assert len(_data("get_dish_margin", "ambiguous")["candidates"]) == 4
    assert len(_data("get_dish_margin", "needs_location")["locations"]) == 2


def test_food_cost_yesterday_is_37_5() -> None:
    d = _data("get_food_cost_pct")
    assert d["theoretical"]["text"] == "37.5%"
    assert d["coverage"]["text"] == "71.4%"


def test_menu_engineering_classifies_every_costed_dish() -> None:
    quadrants = _data("get_menu_engineering")["quadrants"]
    assert [q["name"] for q in quadrants] == ["star", "plowhorse", "puzzle", "dog"]
    assert sum(q["count"] for q in quadrants) == 15


def test_cost_alerts_report_the_two_price_jumps() -> None:
    moves = _data("get_cost_alerts")["price_moves"]
    assert [m["ingredient"] for m in moves] == ["Carne al pastor (adobada)", "Aguacate Hass"]
    assert moves[0]["new_unit_price"]["text"] == "$195.00/kg"


def test_data_status_has_no_missing_days() -> None:
    assert _data("get_data_status")["missing_business_days"] == []
