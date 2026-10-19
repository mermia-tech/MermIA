"""125-token budget per tool (08 C4).

NOT MEASURED YET. The real count_tokens measurement needs an Anthropic API key and is deferred
to the LLM eval ticket (proposed: MR-20). The tests that need the measurement carry the
`tokens` marker, so the default run deselects them: run them with `pytest -m tokens` once
`schemas/tool_tokens.json` exists. The rest check the measuring code with a fake counter.
"""

import json
import os
from collections.abc import Sequence
from typing import Any

import pytest

from mermia_contracts.agent_tools import TOKEN_LIMIT, ToolDef, tool_definitions, tools_sha256
from mermia_contracts.tools.measure_tool_tokens import (
    SNAPSHOT,
    api_counter,
    measure,
    problems,
)

MISSING = "no measurement yet: run measure_tool_tokens with ANTHROPIC_API_KEY set"


def _snapshot() -> dict[str, Any]:
    assert SNAPSHOT.exists(), MISSING
    snap: dict[str, Any] = json.loads(SNAPSHOT.read_text())
    return snap


def test_limit_is_125() -> None:
    assert TOKEN_LIMIT == 125


@pytest.mark.tokens
def test_snapshot_matches_the_current_tools() -> None:
    snap = _snapshot()
    assert snap["tools_sha256"] == tools_sha256(), "tools changed: measure again"
    assert snap["limit"] == TOKEN_LIMIT


@pytest.mark.tokens
def test_every_tool_is_measured_and_within_the_limit() -> None:
    per_tool = _snapshot()["per_tool"]
    assert list(per_tool) == [t["name"] for t in tool_definitions()]
    over = {n: m for n, m in per_tool.items() if m > TOKEN_LIMIT}
    assert not over, f"over {TOKEN_LIMIT} tokens: {over}"


def _fake_count(tools: Sequence[ToolDef]) -> int:
    """100 fixed tokens plus the JSON length of each tool, so marginal cost is checkable."""
    return 100 + sum(len(json.dumps(t)) for t in tools)


def test_marginal_cost_cancels_the_fixed_part() -> None:
    result = measure(_fake_count, "fake", "0")
    first = tool_definitions()[0]
    assert result["per_tool"][first["name"]] == len(json.dumps(first))
    assert result["overhead"] == _fake_count([result["baseline_tool"]])
    assert result["total"] == sum(result["per_tool"].values())


def test_problems_reports_excess_and_drift() -> None:
    saved = {"per_tool": {"a": 100, "b": 100}}
    fresh = {"per_tool": {"a": 126, "b": 103, "c": 5}}
    found = problems(fresh, saved)
    assert any("a: 126" in p and "> 125" in p for p in found)
    assert any(p.startswith("b: measured 103") for p in found)
    assert any(p.startswith("c: measured 5, snapshot None") for p in found)
    assert problems({"per_tool": {"a": 101}}, {"per_tool": {"a": 100}}) == []


@pytest.mark.tokens
def test_live_counts_match_the_snapshot() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set")
    snap = _snapshot()
    fresh = measure(api_counter(snap["model"]), snap["model"], "live")
    assert problems(fresh, snap) == []
