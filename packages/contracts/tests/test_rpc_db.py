"""MR-17: the SQL RPCs answer in the C3 shapes, on the El Güero seed (fixtures/el_guero).

Each call runs as `authenticated` with a signed-in member's claims and the business date pinned
to the seed's "today" (2026-10-12), then the envelope is validated with RpcEnvelope[data model]
from RPCS. Needs MERMIA_DB_URL and the seed (supabase db start / db reset load it).
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

# (rpc, SQL arguments with named notation, claims): args as the agent's ToolExecutor sends them
CALLS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("get_sales_summary", {"period": "last_week", "location_id": CENTRO}, OWNER),
    ("get_sales_summary", {"period": {"from": "2026-10-01", "to": "2026-10-11"}}, OWNER),
    ("get_sales_summary", {"period": "today"}, OWNER),
    ("get_sales_summary", {"period": "last_week", "location_id": CENTRO}, POLANCO_MANAGER),
    (
        "compare_periods",
        {"metric": "net_sales", "period_a": "last_week", "period_b": "prev_week"},
        OWNER,
    ),
    (
        "compare_periods",
        {"metric": "avg_ticket", "period_a": "last_week", "period_b": "prev_week"},
        OWNER,
    ),
    ("compare_periods", {"metric": "units", "period_a": "last_7d", "period_b": "last_30d"}, OWNER),
    (
        "compare_periods",
        {"metric": "food_cost_pct", "period_a": "last_week", "period_b": "prev_week"},
        OWNER,
    ),
    ("get_top_dishes", {"period": "this_month", "metric": "units"}, OWNER),
    (
        "get_top_dishes",
        {"period": "last_30d", "metric": "revenue", "order": "asc", "limit": 10},
        OWNER,
    ),
    (
        "get_top_dishes",
        {"period": "this_month", "metric": "units", "category": "Bebidas"},
        POLANCO_MANAGER,
    ),
    ("get_top_dishes", {"period": "this_month", "metric": "margin"}, OWNER),
    ("get_data_status", {}, OWNER),
    ("get_data_status", {"location_id": POLANCO}, POLANCO_MANAGER),
]


CASTS = {"location_id": "uuid", "limit": "int"}


def call(db_url: str, rpc: str, args: dict[str, Any], claims: dict[str, Any]) -> Any:
    def cast(name: str) -> str:
        return "jsonb" if name.startswith("period") else CASTS.get(name, "text")

    params = ", ".join(f'"{name}" => %s::{cast(name)}' for name in args)
    values = [json.dumps(v) if cast(k) == "jsonb" else v for k, v in args.items()]
    with psycopg.connect(db_url) as conn:
        conn.execute("set role authenticated")
        conn.execute("select set_config('request.jwt.claims', %s, false)", [json.dumps(claims)])
        conn.execute("set app.today = '2026-10-12'")
        row = conn.execute(f"select api.{rpc}({params})", values).fetchone()
        conn.rollback()
    assert row is not None
    return row[0]


@pytest.mark.parametrize(("rpc", "args", "claims"), CALLS, ids=lambda x: json.dumps(x)[:60])
def test_response_parses_with_the_contract(
    db_url: str, rpc: str, args: dict[str, Any], claims: dict[str, Any]
) -> None:
    RPCS[rpc].args.model_validate(args)
    response = call(db_url, rpc, args, claims)
    TypeAdapter(RpcEnvelope[RPCS[rpc].data]).validate_python(response)  # type: ignore[misc,arg-type]


def test_sales_summary_matches_the_seed(db_url: str) -> None:
    r = call(db_url, "get_sales_summary", {"period": "last_week", "location_id": CENTRO}, OWNER)
    assert r["ok"] and r["data"]["net_sales"] == {"raw": 18432050, "text": "$184,320.50"}
    assert r["data"]["change_vs_previous"] == {"raw": 7.2223, "text": "+7.2%"}
    assert r["meta"]["period_resolved"] == {"from": "2026-10-05", "to": "2026-10-11"}


def test_a_location_limited_manager_cannot_ask_for_another_location(db_url: str) -> None:
    r = call(
        db_url, "get_sales_summary", {"period": "last_week", "location_id": CENTRO}, POLANCO_MANAGER
    )
    assert r["ok"] is False and r["error"]["code"] == "not_found"


def test_invalid_arguments_get_an_invalid_args_envelope(db_url: str) -> None:
    r = call(db_url, "get_top_dishes", {"period": "nope", "metric": "units"}, OWNER)
    TypeAdapter(RpcEnvelope[RPCS["get_top_dishes"].data]).validate_python(r)  # type: ignore[misc,arg-type]
    assert r["ok"] is False and r["error"]["code"] == "invalid_args"


EXAMPLES = Path(__file__).parent / "examples" / "rpc"


@pytest.mark.parametrize(
    "name",
    ["get_sales_summary", "compare_periods", "get_top_dishes", "get_data_status"],
)
def test_the_contract_example_is_what_the_rpc_answers(db_url: str, name: str) -> None:
    """The C3 examples (and so the mock server, MR-13) say what the real RPC says on the seed."""
    doc = json.loads((EXAMPLES / f"{name}.json").read_text())
    adapter = TypeAdapter(RpcEnvelope[RPCS[name].data])  # type: ignore[misc,arg-type]
    live = adapter.validate_python(call(db_url, name, doc["args"], OWNER))
    assert live == adapter.validate_python(doc["response"])
