import pytest
from fastapi.testclient import TestClient

from mermia_contracts.rpc import RPCS
from mermia_mock_rpc import rpcs
from mermia_mock_rpc.app import app

client = TestClient(app)


@pytest.mark.parametrize("name", list(RPCS))
def test_each_rpc_answers_its_canonical_query(name: str) -> None:
    response = client.post(f"/rpc/{name}", json=rpcs.CANONICAL[name])
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_the_answer_ignores_the_values_of_the_request() -> None:
    other = client.post("/rpc/get_sales_summary", json={"period": "today"})
    assert (
        other.json() == client.post("/rpc/get_sales_summary", json={"period": "last_week"}).json()
    )


def test_bad_args_is_422() -> None:
    assert client.post("/rpc/get_sales_summary", json={"period": "next_year"}).status_code == 422
    assert (
        client.post("/rpc/get_sales_summary", json={"period": "today", "x": 1}).status_code == 422
    )


def test_unknown_rpc_is_404() -> None:
    assert client.post("/rpc/propose_change", json={}).status_code == 404


def test_unknown_variant_is_422() -> None:
    response = client.post("/rpc/get_sales_summary?variant=nope", json={"period": "today"})
    assert response.status_code == 422


def test_variant_of_another_rpc_is_422() -> None:
    response = client.post("/rpc/get_cost_alerts?variant=ambiguous", json={})
    assert response.status_code == 422


def test_error_variant_is_ok_false() -> None:
    response = client.post("/rpc/get_sales_summary?variant=error", json={"period": "today"})
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"]["code"] == "no_data"


def test_special_variant_is_served() -> None:
    response = client.post("/rpc/get_dish_margin?variant=needs_location", json={"dish": "pastor"})
    assert response.json()["data"]["match"] == "needs_location"


def _raws(node: object) -> list[object]:
    if isinstance(node, dict):
        found = [v for k, v in node.items() if k == "raw"]
        return found + [x for v in node.values() for x in _raws(v)]
    if isinstance(node, list):
        return [x for v in node for x in _raws(v)]
    return []


@pytest.mark.parametrize("name", list(RPCS))
def test_raw_values_travel_as_json_numbers(name: str) -> None:
    body = client.post(f"/rpc/{name}", json=rpcs.CANONICAL[name]).json()
    assert all(isinstance(raw, int | float) for raw in _raws(body))


def test_every_answer_says_it_is_a_fixed_mock_answer() -> None:
    for name in RPCS:
        for variant in (None, *rpcs.VARIANTS[name]):
            url = f"/rpc/{name}" + (f"?variant={variant}" if variant else "")
            flags = client.post(url, json=rpcs.CANONICAL[name]).json()["flags"]
            assert "mock_fixed_answer" in [f["code"] for f in flags]
