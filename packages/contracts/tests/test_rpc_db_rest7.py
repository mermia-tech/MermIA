"""MR-24: the remaining 7 SQL RPCs answer in the C3 shapes, on the El Güero seed.

As test_rpc_db.py (MR-17), plus the backend's cost job: each call first runs
app.compute_dish_costs (as the owner role, the way the backend would), then switches to
`authenticated` with a member's claims and the seed's "today" (2026-10-12), and rolls back.
Needs MERMIA_DB_URL and the seed (supabase db reset loads it).
"""

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic import TypeAdapter

from mermia_contracts.rpc import RPCS, RpcEnvelope

pytestmark = pytest.mark.db

TENANT = "03299e41-28bd-5779-bcc6-0e5e76580fad"
CENTRO = "705e8e51-376b-5785-adbb-405eff4e2a22"
POLANCO = "fdda5e3b-6bcd-5c48-a6de-f524be37463e"
OWNER = {"tenant_id": TENANT, "location_ids": None}
POLANCO_MANAGER = {"tenant_id": TENANT, "location_ids": [POLANCO]}
OTHER_TENANT = {"tenant_id": "aaaaaaaa-0000-7000-8000-000000000009", "location_ids": None}
SATURDAY = {"from": "2026-10-10", "to": "2026-10-10"}

CALLS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("get_dish_margin", {"dish": "tacos al pastor", "location_id": CENTRO}, OWNER),
    ("get_dish_margin", {"dish": "tacos al pastor"}, OWNER),
    ("get_dish_margin", {"dish": "pastor"}, OWNER),
    ("get_dish_margin", {"dish": "tacos al pastor"}, POLANCO_MANAGER),
    ("get_dish_margin", {"dish": "pizza"}, OWNER),
    ("get_dish_margin", {"dish": "tacos al pastor"}, OTHER_TENANT),
    (
        "get_food_cost_pct",
        {"period": "yesterday", "location_id": CENTRO, "group_by": "category"},
        OWNER,
    ),
    ("get_food_cost_pct", {"period": "last_week"}, POLANCO_MANAGER),
    ("get_food_cost_pct", {"period": "last_week", "location_id": CENTRO}, POLANCO_MANAGER),
    ("get_sales_breakdown", {"period": "yesterday", "by": "payment_method"}, OWNER),
    ("get_sales_breakdown", {"period": "last_week", "by": "weekday"}, OWNER),
    ("get_sales_breakdown", {"period": "last_30d", "by": "category"}, POLANCO_MANAGER),
    ("get_sales_breakdown", {"period": "last_week", "by": "staff"}, OWNER),
    ("get_sales_breakdown", {"period": "yesterday", "by": "hour"}, OTHER_TENANT),
    ("get_cancellations", {"period": SATURDAY, "kind": "cancellations"}, OWNER),
    ("get_cancellations", {"period": "last_week", "kind": "discounts"}, OWNER),
    ("get_cancellations", {"period": "last_week"}, POLANCO_MANAGER),
    ("get_cancellations", {"period": "last_week"}, OTHER_TENANT),
    ("compare_locations", {"metric": "net_sales", "period": "last_week"}, OWNER),
    ("compare_locations", {"metric": "food_cost_pct", "period": "last_week"}, OWNER),
    ("compare_locations", {"metric": "avg_ticket", "period": "last_30d"}, POLANCO_MANAGER),
    (
        "compare_locations",
        {"metric": "units", "period": "this_month", "location_ids": [CENTRO]},
        OWNER,
    ),
    (
        "compare_locations",
        {"metric": "net_sales", "period": "last_week", "location_ids": [CENTRO]},
        POLANCO_MANAGER,
    ),
    ("get_menu_engineering", {"period": "last_30d", "location_id": CENTRO}, OWNER),
    ("get_menu_engineering", {"period": "last_week"}, POLANCO_MANAGER),
    ("get_menu_engineering", {"period": "last_week"}, OTHER_TENANT),
    ("get_cost_alerts", {"since": "last_30d", "location_id": CENTRO}, OWNER),
    ("get_cost_alerts", {}, OWNER),
    ("get_cost_alerts", {"since": "last_30d"}, POLANCO_MANAGER),
    ("get_cost_alerts", {"since": "last_30d"}, OTHER_TENANT),
]

JSONB_ARGS = {"period", "since", "period_a", "period_b"}
CASTS = {"location_id": "uuid", "location_ids": "uuid[]"}


def call(db_url: str, rpc: str, args: dict[str, Any], claims: dict[str, Any]) -> Any:
    def cast(name: str) -> str:
        return "jsonb" if name in JSONB_ARGS else CASTS.get(name, "text")

    params = ", ".join(f'"{name}" => %s::{cast(name)}' for name in args)
    values = [json.dumps(v) if cast(k) == "jsonb" else v for k, v in args.items()]
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "select app.compute_dish_costs(%s, '2026-09-01', '2026-10-12')", [TENANT]
        )  # the backend's cost job, rolled back with the rest
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claims', %s, true)", [json.dumps(claims)])
        conn.execute("set local app.today = '2026-10-12'")
        row = conn.execute(f"select api.{rpc}({params})", values).fetchone()
        conn.rollback()
    assert row is not None
    return row[0]


def envelope(name: str) -> TypeAdapter[Any]:
    return TypeAdapter(RpcEnvelope[RPCS[name].data])  # type: ignore[misc,arg-type]


@pytest.mark.parametrize(("rpc", "args", "claims"), CALLS, ids=lambda x: json.dumps(x)[:60])
def test_response_parses_with_the_contract(
    db_url: str, rpc: str, args: dict[str, Any], claims: dict[str, Any]
) -> None:
    RPCS[rpc].args.model_validate(args)
    envelope(rpc).validate_python(call(db_url, rpc, args, claims))


def test_invalid_arguments_get_an_invalid_args_envelope(db_url: str) -> None:
    r = call(db_url, "get_sales_breakdown", {"period": "last_week", "by": "table"}, OWNER)
    envelope("get_sales_breakdown").validate_python(r)
    assert r["ok"] is False and r["error"]["code"] == "invalid_args"


def test_every_cost_answer_carries_its_confidence(db_url: str) -> None:
    """03 C.5: never a cost figure without its tag (a field, or one cost_* flag)."""
    margin = call(
        db_url, "get_dish_margin", {"dish": "tacos al pastor", "location_id": CENTRO}, OWNER
    )
    assert margin["data"]["confidence"] in {"confirmed", "estimated"}
    for rpc, args in [
        ("get_food_cost_pct", {"period": "yesterday"}),
        ("compare_locations", {"metric": "food_cost_pct", "period": "last_week"}),
        ("get_menu_engineering", {"period": "last_30d"}),
        ("get_cost_alerts", {"since": "last_30d"}),
        ("get_top_dishes", {"period": "last_30d", "metric": "margin"}),
        (
            "compare_periods",
            {"metric": "food_cost_pct", "period_a": "yesterday", "period_b": "last_week"},
        ),
    ]:
        flags = [f["code"] for f in call(db_url, rpc, args, OWNER)["flags"]]
        assert sum(code in {"cost_confirmed", "cost_estimated"} for code in flags) == 1, rpc


EXAMPLES = Path(__file__).parent / "examples" / "rpc"


def example_and_live(db_url: str, name: str, file: str | None = None) -> tuple[Any, Any]:
    doc = json.loads((EXAMPLES / f"{file or name}.json").read_text())
    adapter = envelope(name)
    return (
        adapter.validate_python(doc["response"]),
        adapter.validate_python(call(db_url, name, doc["args"], OWNER)),
    )


@pytest.mark.parametrize(
    ("name", "file"),
    [
        ("compare_locations", None),
        ("get_cancellations", None),
        ("get_sales_breakdown", "get_sales_breakdown.no_tickets"),
        ("get_dish_margin", "get_dish_margin.needs_location"),
    ],
)
def test_the_contract_example_is_what_the_rpc_answers(
    db_url: str, name: str, file: str | None
) -> None:
    """These C3 examples (and so the mock server) say exactly what the real RPC says."""
    example, live = example_and_live(db_url, name, file)
    assert live == example


# The examples below were written before the engine and the seed's confidence existed; the
# figures agree with the seed, the listed parts do not (see the PR's contract questions).


def test_dish_margin_example_figures(db_url: str) -> None:
    example, live = example_and_live(db_url, "get_dish_margin")
    keep = {"confidence", "cost_drivers"}  # example: confirmed, one driver; seed: estimated, 3
    assert live.data.model_dump(exclude=keep) == example.data.model_dump(exclude=keep)
    assert live.data.cost_drivers[0] == example.data.cost_drivers[0]
    assert live.meta == example.meta


def test_ambiguous_dish_example_has_the_same_candidates(db_url: str) -> None:
    example, live = example_and_live(db_url, "get_dish_margin", "get_dish_margin.ambiguous")
    assert {c.name for c in live.data.candidates} == {c.name for c in example.data.candidates}
    assert live.data.candidates[0] == example.data.candidates[0]


def test_food_cost_example_figures(db_url: str) -> None:
    example, live = example_and_live(db_url, "get_food_cost_pct")
    assert live.data == example.data and live.meta == example.meta  # flags: cost_estimated


def test_menu_engineering_example_figures(db_url: str) -> None:
    example, live = example_and_live(db_url, "get_menu_engineering")
    assert live.data == example.data and live.meta == example.meta


def test_sales_breakdown_example_figures(db_url: str) -> None:
    example, live = example_and_live(db_url, "get_sales_breakdown")
    # payment_mix holds amounts only: tickets per method are null (MR-11 D23)
    assert [r.model_dump(exclude={"tickets"}) for r in live.data.rows] == [
        r.model_dump(exclude={"tickets"}) for r in example.data.rows
    ]
    assert all(r.tickets is None for r in live.data.rows)


def test_cost_alerts_example_figures(db_url: str) -> None:
    example, live = example_and_live(db_url, "get_cost_alerts")
    assert live.data.price_moves == example.data.price_moves
    assert live.data.breaches == example.data.breaches
    assert live.data.suggestions == []  # the backend writes price_suggestion; the seed has none
