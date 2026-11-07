"""MR-34: api.build_weekly_report answers in the WeeklyReportData shape, on the El Güero seed.

As test_rpc_db_rest7.py: the backend's cost job and the alert evaluation of 2026-10-12 run first
(what the Monday job does before it builds the report), then the call runs as `authenticated` with
a member's claims and the seed's "today", and everything rolls back. Needs MERMIA_DB_URL.
"""

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic import TypeAdapter

from mermia_contracts.rpc import REPORT_RPCS, RpcEnvelope, WeeklyReportData

pytestmark = pytest.mark.db

TENANT = "03299e41-28bd-5779-bcc6-0e5e76580fad"
CENTRO = "705e8e51-376b-5785-adbb-405eff4e2a22"
POLANCO = "fdda5e3b-6bcd-5c48-a6de-f524be37463e"
OWNER = {"tenant_id": TENANT, "location_ids": None}
POLANCO_MANAGER = {"tenant_id": TENANT, "location_ids": [POLANCO]}
OTHER_TENANT = {"tenant_id": "aaaaaaaa-0000-7000-8000-000000000009", "location_ids": None}
# Queso Oaxaca $140 -> $280/kg on 09-28: Polanco's quesadilla gets a raise (test_rpc_db_rest7)
QUESO_DOUBLES = (
    "insert into public.ingredient_price"
    " (tenant_id, ingredient_id, unit_price_net, effective_from, source)"
    f" values ('{TENANT}', '5268568b-3d45-535f-9197-4b2f1873700e', 0.280, '2026-09-28', 'cfdi')",
)

# the same price dated Monday 10-12, the day the report is built: after the week's Sunday
QUESO_DOUBLES_ON_MONDAY = (QUESO_DOUBLES[0].replace("'2026-09-28'", "'2026-10-12'"),)


def call(
    db_url: str, args: dict[str, Any], claims: dict[str, Any], setup: tuple[str, ...] = ()
) -> Any:
    params = ", ".join(
        f'"{name}" => %s::{"jsonb" if name == "period" else "uuid"}' for name in args
    )
    values = [json.dumps(v) if k == "period" else v for k, v in args.items()]
    with psycopg.connect(db_url) as conn:
        for statement in setup:
            conn.execute(statement)  # test-only literals
        conn.execute("select app.compute_dish_costs(%s, '2026-09-01', '2026-10-12')", [TENANT])
        conn.execute("set local role service_role")
        conn.execute("select app.evaluate_cost_alerts(%s, '2026-10-12', '2026-10-12')", [TENANT])
        conn.execute("reset role")
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claims', %s, true)", [json.dumps(claims)])
        conn.execute("set local app.today = '2026-10-12'")
        row = conn.execute(f"select api.build_weekly_report({params})", values).fetchone()
        conn.rollback()
    assert row is not None
    return row[0]


ENVELOPE: TypeAdapter[Any] = TypeAdapter(RpcEnvelope[WeeklyReportData])
EXAMPLES = Path(__file__).parent / "examples" / "rpc"


def report(db_url: str, claims: dict[str, Any], **args: Any) -> Any:
    REPORT_RPCS["build_weekly_report"].args.model_validate(args)
    response = call(db_url, args, claims)
    ENVELOPE.validate_python(response)
    return response


def test_owner_last_week_is_both_locations(db_url: str) -> None:
    r = report(db_url, OWNER)
    assert r["ok"] and r["data"]["week"] == {"from": "2026-10-05", "to": "2026-10-11"}
    assert r["data"]["sales"]["net_sales"]["raw"] == 18432050 + 16092080 == 34524130
    # 34,524,130 vs 33,352,460 the week before
    assert r["data"]["sales"]["change_vs_previous"] == {"raw": 3.513, "text": "+3.5%"}
    assert r["data"]["missing_business_days"] == []


def test_the_previous_week_is_the_sales_comparison_base(db_url: str) -> None:
    r = report(db_url, OWNER, period="prev_week")
    assert r["data"]["sales"]["net_sales"]["raw"] == 33352460


def test_the_week_of_the_aguacate_jump(db_url: str) -> None:
    r = report(db_url, OWNER, period={"from": "2026-09-28", "to": "2026-10-04"})
    moves = r["data"]["cost_alerts"]["price_moves"]
    assert [(m["ingredient"], m["change"]["text"]) for m in moves] == [("Aguacate Hass", "+61.8%")]


def test_the_week_of_09_21_stops_on_its_sunday(db_url: str) -> None:
    """The aguacate jump of 09-28 belongs to the next week, not to this one."""
    r = report(db_url, OWNER, period={"from": "2026-09-21", "to": "2026-09-27"})
    moves = r["data"]["cost_alerts"]["price_moves"]
    assert [m["ingredient"] for m in moves] == ["Carne al pastor (adobada)"]
    assert r["meta"]["period_resolved"] == {"from": "2026-09-21", "to": "2026-09-27"}


def _week_costs(r: Any) -> Any:
    alerts = r["data"]["cost_alerts"]
    return (
        alerts["price_moves"],
        alerts["price_moves_total"],
        alerts["breaches"],
        alerts["breaches_total"],
        r["flags"],
    )


def _without_suggestion(r: Any, names: set[str]) -> Any:
    """The report with the [Ver márgenes] suggestions of these dishes taken out."""
    out = json.loads(json.dumps(r))
    for b in out["data"]["cost_alerts"]["breaches"]:
        if b["name"] in names:
            b["at"] = [{**e, "suggestion": None} for e in b["at"]]
    return out


def _suggestion_follows_its_figures(e: Any, target_pct: float) -> bool:
    """A breach entry's suggestion is priced on that entry's cost and menu price: its current
    price is the entry's menu price and its target price is the cost at the target food cost with
    the dish's IVA (within centavo rounding)."""
    s = e["suggestion"]
    if s is None:
        return True
    gross, net, cost = e["price_gross"]["raw"], e["net_price"]["raw"], e["cost"]["raw"]
    target = cost * gross / net * 100 / target_pct
    return bool(s["current_price"]["raw"] == gross and abs(s["target_price"]["raw"] - target) <= 2)


def test_a_price_dated_after_sunday_does_not_move_last_weeks_report(db_url: str) -> None:
    """W2: the 9:00 and the 12:00 report agree even if a Monday-dated price lands in between:
    same price moves, breaches, figures and flags. The Monday price re-prices the suggestions of
    the dishes it touches (Alambre de res and Volcán de pastor use Queso Oaxaca); those no longer
    match the week's figures, so [Ver márgenes] leaves them out (N1) and they stay in
    `suggestions` only."""
    before = call(db_url, {}, OWNER)
    after = call(db_url, {}, OWNER, QUESO_DOUBLES_ON_MONDAY)
    moved = {"Alambre de res", "Volcán de pastor"}
    assert _week_costs(after) == _week_costs(_without_suggestion(before, moved))
    assert after["data"]["cost_alerts"]["price_moves_total"] == 0
    for r in (before, after):
        for b in r["data"]["cost_alerts"]["breaches"]:
            assert all(_suggestion_follows_its_figures(e, b["target"]["raw"]) for e in b["at"])
    listed = {(s["name"], s["location_id"]) for s in after["data"]["cost_alerts"]["suggestions"]}
    assert {("Alambre de res", CENTRO), ("Volcán de pastor", CENTRO)} <= listed


def test_ver_margenes_comes_from_the_payload(db_url: str) -> None:
    """Doc 12 1b: "*1. Costra de pastor* — costo $29.80, precio $89.00 → *38.8%*", then the
    suggestion."""
    data = report(db_url, OWNER)["data"]
    names = {loc["location_id"]: loc["name"] for loc in data["locations"]}
    assert names == {CENTRO: "Centro", POLANCO: "Polanco"}
    torta = next(b for b in data["cost_alerts"]["breaches"] if b["name"] == "Torta de pastor")
    e = torta["at"][0]
    line = (
        f"{torta['name']} ({names[e['location_id']]}) — costo {e['cost']['text']},"
        f" precio {e['price_gross']['text']} → {e['food_cost']['text']}"
    )
    assert line == "Torta de pastor (Centro) — costo $34.49, precio $80.00 → 50.0%"
    assert e["net_price"]["raw"] == round(8000 / 1.16)
    assert e["suggestion"]["location_id"] == e["location_id"] == CENTRO
    assert e["suggestion"]["rationale_code"] == "review_portion_cost"


def test_ver_margenes_lists_every_location_over_target(db_url: str) -> None:
    """N2: with Queso Oaxaca at $280/kg the quesadilla is over target at both locations: Centro
    50.0 % at $45 (no suggestion) and Polanco 45.0 % at $50, raise to $55. Both lines show."""
    data = call(db_url, {}, OWNER, QUESO_DOUBLES)["data"]
    WeeklyReportData.model_validate(data)
    quesadilla = next(
        b for b in data["cost_alerts"]["breaches"] if b["name"] == "Quesadilla de queso"
    )
    assert quesadilla["food_cost"] == quesadilla["at"][0]["food_cost"]
    lines = [
        (
            e["location_id"],
            e["price_gross"]["text"],
            e["food_cost"]["text"],
            e["suggestion"] and e["suggestion"]["suggested_price"]["text"],
        )
        for e in quesadilla["at"]
    ]
    assert lines == [(CENTRO, "$45.00", "50.0%", None), (POLANCO, "$50.00", "45.0%", "$55.00")]


def test_a_polanco_manager_gets_polanco_only(db_url: str) -> None:
    r = report(db_url, POLANCO_MANAGER)
    assert r["data"]["sales"]["net_sales"]["raw"] == 16092080
    assert {s["location_id"] for s in r["data"]["cost_alerts"]["suggestions"]} == {POLANCO}
    assert {e["location_id"] for b in r["data"]["cost_alerts"]["breaches"] for e in b["at"]} == {
        POLANCO
    }
    assert r["data"]["locations"] == [{"location_id": POLANCO, "name": "Polanco"}]
    denied = report(db_url, POLANCO_MANAGER, location_id=CENTRO)
    assert denied["ok"] is False and denied["error"]["code"] == "not_found"


def test_another_tenant_gets_nothing(db_url: str) -> None:
    r = report(db_url, OTHER_TENANT)
    assert r["ok"] is False and r["error"]["code"] == "no_data"
    assert report(db_url, OTHER_TENANT, location_id=CENTRO)["error"]["code"] == "not_found"


def test_a_week_that_has_not_ended_is_invalid(db_url: str) -> None:
    r = report(db_url, OWNER, period={"from": "2026-10-12", "to": "2026-10-18"})
    assert r["ok"] is False and r["error"]["code"] == "invalid_args"


@pytest.mark.parametrize(
    ("file", "setup"),
    [("build_weekly_report", ()), ("build_weekly_report.raise", QUESO_DOUBLES)],
)
def test_the_contract_example_is_what_the_rpc_answers(
    db_url: str, file: str, setup: tuple[str, ...]
) -> None:
    """The examples (and so the mock MR-38 builds against) say what the real RPC says."""
    doc = json.loads((EXAMPLES / f"{file}.json").read_text())
    live = call(db_url, doc["args"], OWNER, setup)
    assert ENVELOPE.validate_python(live) == ENVELOPE.validate_python(doc["response"])
