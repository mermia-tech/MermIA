from pathlib import Path
from typing import Any

import pytest

from mermia_eval.gate import ScoredRun, format_gate, gate_rows, load_dumps, percentile, write_dump

LUNA, LITE = "openai:gpt-5.6-luna", "google:gemini-3.5-flash-lite"
PERFECT = {"tool": 1.0, "args": 1.0, "numbers": 1.0}


def _run(model: str = LUNA, category: str = "sales", **kw: Any) -> ScoredRun:
    fields: dict[str, Any] = {
        "model": model,
        "case_id": "c",
        "category": category,
        "question": "¿Cuánto vendí?",
        "reply": "Vendiste $10.00",
        "calls": [],
        "scores": dict(PERFECT),
        "tone": 5,
        "tone_cross": None,
        "tone_reason": "",
        "seconds": 1.0,
        "cost": 0.001,
        "error": None,
    }
    return ScoredRun(**(fields | kw))


def _err(model: str = LUNA) -> ScoredRun:
    return _run(model, scores=None, tone=None, error="boom")


def _all(runs: list[ScoredRun], model: str = LUNA) -> Any:
    return next(r for r in gate_rows(runs) if r.model == model and r.category == "all")


def test_percentile_nearest_rank() -> None:
    assert percentile(range(1, 21), 0.5) == 10
    assert percentile(range(1, 21), 0.95) == 19
    assert percentile([4.0], 0.95) == 4.0


def test_all_pass() -> None:
    row = _all([_run(), _run(), _run()])
    assert row.passed is True
    assert (row.tool, row.p50, row.cost, row.runs, row.errors) == (1.0, 1.0, 0.001, 3, 0)


@pytest.mark.parametrize(
    ("runs", "failing"),
    [
        ([_run(scores=PERFECT | {"tool": 0.0})] + [_run()] * 9, "tool"),
        ([_run(scores=PERFECT | {"args": 0.0})] + [_run()] * 9, "args"),
        ([_run(scores=PERFECT | {"numbers": 0.0}), _run(), _run()], "numbers"),
        ([_run(tone=3)] * 3, "tone_mean"),
        ([_run(tone=2)] + [_run()] * 9, "tone_min"),
        ([_run(seconds=4.0)] * 3, "p50"),
        ([_run(seconds=1.0), _run(seconds=1.0), _run(seconds=9.0)], "p95"),
        ([_run(cost=0.004)] * 3, "cost"),
    ],
)
def test_each_threshold_fails_alone(runs: list[ScoredRun], failing: str) -> None:
    row = _all(runs)
    assert [k for k, ok in row.checks.items() if not ok] == [failing]


def test_errors_not_scored_and_counted() -> None:
    row = _all([_err()] + [_run()] * 19)
    assert (row.tool, row.errors, row.runs) == (1.0, 1, 20)
    assert row.checks["errors"] is True
    assert _all([_err(), _err()] + [_run()] * 18).checks["errors"] is False


def test_every_run_errored() -> None:
    row = _all([_err(), _err()])
    assert (row.tool, row.numbers, row.tone_mean, row.p50, row.cost) == (None,) * 5
    assert row.passed is False
    assert "-" in format_gate([row])


def test_missing_price_fails_cost() -> None:
    row = _all([_run(), _run(cost=None)])
    assert row.cost is None and row.checks["cost"] is False
    assert "n/a" in format_gate([row])


def test_no_tone_is_not_measured() -> None:
    row = _all([_run(tone=None)] * 2)
    assert row.tone_mean is None and row.checks["tone_mean"] is False
    assert _all([_run(), _run(tone=None)]).checks["tone_mean"] is False  # incomplete


def test_tone_gate_uses_lower_judge() -> None:
    assert _run(tone=5, tone_cross=3).tone_gate == 3
    assert _run(tone=None, tone_cross=None).tone_gate is None


def test_rows_per_category() -> None:
    rows = gate_rows([_run(category="writes"), _run(category="sales")])
    assert [r.category for r in rows] == ["all", "sales", "writes"]


def test_format_gate_names_failing_checks() -> None:
    table = format_gate(gate_rows([_run(cost=0.004)]))
    assert "fail: cost" in table and LUNA in table
    assert "PASS" in format_gate(gate_rows([_run()]))


def test_dump_roundtrip_and_model_replacement(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write_dump(a, [_run(LUNA), _run(LITE), _run(LITE)], {"git_commit": "x"})
    write_dump(b, [_run(LITE, reply="rerun")], {"git_commit": "y"})
    runs = load_dumps([a, b])
    assert [(r.model, r.reply) for r in runs] == [(LUNA, "Vendiste $10.00"), (LITE, "rerun")]
    assert load_dumps([a])[0] == _run(LUNA)
