"""MR-33: get_cost_alerts lists the top 10 price moves, breaches and suggestions, with the totals.

Doc 13: tool results stay around 400 tokens, top N only. `price_moves_total`, `breaches_total`
and `suggestions_total` count every row, so the agent can say "y 14 más".
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mermia_contracts.rpc import COST_ALERTS_TOP_N, CostAlertsData

EXAMPLES = Path(__file__).parent / "examples" / "rpc"


def _data(name: str = "get_cost_alerts") -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((EXAMPLES / f"{name}.json").read_text())
    return copy.deepcopy(doc["response"]["data"])


def _padded(key: str, n: int, total: int) -> dict[str, Any]:
    data = _data()
    rows = data[key]
    data[key] = [rows[i % len(rows)] for i in range(n)]
    data[f"{key}_total"] = total
    return data


def test_the_cap_is_ten() -> None:
    assert COST_ALERTS_TOP_N == 10


@pytest.mark.parametrize("name", ["get_cost_alerts", "get_cost_alerts.raise"])
def test_the_examples_carry_their_totals(name: str) -> None:
    data = CostAlertsData.model_validate(_data(name))
    assert data.price_moves_total == len(data.price_moves)
    assert data.breaches_total == len(data.breaches)
    assert data.suggestions_total == len(data.suggestions)


@pytest.mark.parametrize("key", ["price_moves", "breaches", "suggestions"])
def test_a_full_list_with_more_behind_it(key: str) -> None:
    data = CostAlertsData.model_validate(_padded(key, COST_ALERTS_TOP_N, 14))
    assert len(getattr(data, key)) == COST_ALERTS_TOP_N
    assert getattr(data, f"{key}_total") == 14


@pytest.mark.parametrize("key", ["price_moves", "breaches", "suggestions"])
def test_never_more_than_the_cap(key: str) -> None:
    with pytest.raises(ValidationError):
        CostAlertsData.model_validate(_padded(key, COST_ALERTS_TOP_N + 1, COST_ALERTS_TOP_N + 1))


@pytest.mark.parametrize("key", ["price_moves", "breaches", "suggestions"])
@pytest.mark.parametrize(("n", "total"), [(2, 1), (2, 3), (9, 14)])
def test_the_list_is_the_top_of_the_total(key: str, n: int, total: int) -> None:
    """Fewer rows than the total only when the list is full; never more rows than the total."""
    with pytest.raises(ValidationError, match="top"):
        CostAlertsData.model_validate(_padded(key, n, total))


@pytest.mark.parametrize("key", ["price_moves_total", "breaches_total", "suggestions_total"])
def test_the_totals_are_required(key: str) -> None:
    data = _data()
    del data[key]
    with pytest.raises(ValidationError):
        CostAlertsData.model_validate(data)
