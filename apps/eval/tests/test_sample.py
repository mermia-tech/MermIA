from pathlib import Path

import pytest

from mermia_eval.gate import ScoredRun, write_dump
from mermia_eval.sample import main, sample_for_review

MODELS = ("openai:a", "google:b", "anthropic:c")
CATEGORIES = ("sales", "writes", "ops", "adversarial")


def _run(model: str, category: str, i: int, error: str | None = None) -> ScoredRun:
    return ScoredRun(
        model, f"{category}_{i}", category, "¿Pregunta?", f"{model} {category} {i}", [],
        None if error else {"tool": 1.0, "args": 1.0, "numbers": 1.0},
        4, None, "ok", 1.0, 0.001, error,
    )  # fmt: skip


RUNS = [_run(m, c, i) for m in MODELS for c in CATEGORIES for i in range(3)]


def test_sample_spreads_models_and_categories() -> None:
    picked = sample_for_review(RUNS)
    assert len(picked) == 10
    assert {r.model for r in picked} == set(MODELS)
    assert {r.category for r in picked} == set(CATEGORIES)
    assert sample_for_review(RUNS) == picked  # same seed, same sample


def test_errored_runs_never_sampled() -> None:
    runs = [_run("openai:a", "sales", i, error="boom") for i in range(5)] + RUNS[:2]
    assert all(r.error is None for r in sample_for_review(runs))
    assert len(sample_for_review(runs)) == 2


def test_main_prints_replies_with_a_human_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dump = tmp_path / "d.json"
    write_dump(dump, RUNS, {})
    assert main([str(dump)]) == 0
    out = capsys.readouterr().out
    assert out.count("human: _/5") == 10
    assert f"A: {sample_for_review(RUNS)[0].reply}" in out
