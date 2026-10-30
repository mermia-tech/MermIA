"""The MR-20 gate: every run of every model, checked against the docs/kickoff/13 §H3 thresholds,
overall and per category. `python -m mermia_eval.gate out/a.json [out/b.json ...]` reprints it
from run dumps."""

import dataclasses
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
from statistics import fmean
from typing import Any, Final, get_args

from mermia_eval.cases import Category

THRESHOLDS: Final = {
    "tool": 0.95,  # minimum
    "args": 0.95,  # minimum
    "numbers": 1.0,  # minimum: no invented figure in any run
    "tone_mean": 4.0,  # minimum, 1-5
    "tone_min": 3,  # minimum, 1-5
    "p50": 3.0,  # maximum seconds
    "p95": 8.0,  # maximum seconds
    "cost": 0.003,  # maximum mean USD per question
    "errors": 0.05,  # maximum share of runs (MR-20 spec: high error rate is not eligible)
}


@dataclass
class ScoredRun:
    model: str
    case_id: str
    category: str
    question: str
    reply: str
    calls: list[dict[str, Any]]
    scores: dict[str, float] | None  # tool, args, numbers; None when the run errored
    tone: int | None
    tone_cross: int | None  # second judge, for the judge's own vendor
    tone_reason: str
    seconds: float
    cost: float | None
    error: str | None

    @property
    def tone_gate(self) -> int | None:
        tones = [t for t in (self.tone, self.tone_cross) if t is not None]
        return min(tones) if tones else None


@dataclass
class GateRow:
    model: str
    category: str  # "all" or a case category
    tool: float | None
    args: float | None
    numbers: float | None
    tone_mean: float | None
    tone_min: float | None
    p50: float | None
    p95: float | None
    cost: float | None
    runs: int
    errors: int
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def percentile(values: Sequence[float] | range, q: float) -> float:
    """Nearest rank: the smallest value with at least q of the values at or below it."""
    ordered = sorted(values)
    return ordered[ceil(q * len(ordered)) - 1]


def _row(model: str, category: str, runs: Sequence[ScoredRun]) -> GateRow:
    ok = [r for r in runs if r.error is None and r.scores is not None]

    def mean(key: str) -> float | None:
        return fmean(r.scores[key] for r in ok if r.scores) if ok else None

    tones = [r.tone_gate for r in ok]
    judged = [t for t in tones if t is not None]
    seconds = [r.seconds for r in ok]
    costs = [r.cost for r in ok]
    row = GateRow(
        model,
        category,
        tool=mean("tool"),
        args=mean("args"),
        numbers=mean("numbers"),
        tone_mean=fmean(judged) if judged else None,
        tone_min=min(judged) if judged else None,
        p50=percentile(seconds, 0.5) if ok else None,
        p95=percentile(seconds, 0.95) if ok else None,
        cost=fmean(c for c in costs if c is not None) if ok and None not in costs else None,
        runs=len(runs),
        errors=len(runs) - len(ok),
    )
    complete = bool(ok) and len(judged) == len(ok)  # an unjudged run leaves tone unmeasured

    def at_least(v: float | None, key: str) -> bool:
        return v is not None and v >= THRESHOLDS[key]

    def at_most(v: float | None, key: str) -> bool:
        return v is not None and v <= THRESHOLDS[key]

    row.checks = {
        "tool": at_least(row.tool, "tool"),
        "args": at_least(row.args, "args"),
        "numbers": at_least(row.numbers, "numbers"),
        "tone_mean": complete and at_least(row.tone_mean, "tone_mean"),
        "tone_min": complete and at_least(row.tone_min, "tone_min"),
        "p50": at_most(row.p50, "p50"),
        "p95": at_most(row.p95, "p95"),
        "cost": at_most(row.cost, "cost"),
        "errors": row.errors <= THRESHOLDS["errors"] * row.runs,
    }
    return row


def gate_rows(runs: Sequence[ScoredRun]) -> list[GateRow]:
    """Per model: one "all" row, then one row per category present, in Category order."""
    rows = []
    for model in dict.fromkeys(r.model for r in runs):
        mine = [r for r in runs if r.model == model]
        rows.append(_row(model, "all", mine))
        for category in get_args(Category):
            if group := [r for r in mine if r.category == category]:
                rows.append(_row(model, category, group))
    return rows


def _fmt(v: float | None, spec: str) -> str:
    return "-" if v is None else format(v, spec)


def format_gate(rows: Sequence[GateRow]) -> str:
    lines = [
        f"{'model':<32}{'category':<14}{'tool':>5}{'args':>6}{'nums':>6}{'tone':>6}{'tmin':>5}"
        f"{'p50':>6}{'p95':>6}{'usd':>9}{'runs':>5}{'err':>4}  result"
    ]
    for r in rows:
        cost = "n/a" if r.cost is None and r.runs > r.errors else _fmt(r.cost, ".5f")
        failed = [k for k, ok in r.checks.items() if not ok]
        lines.append(
            f"{r.model:<32}{r.category:<14}{_fmt(r.tool, '.2f'):>5}{_fmt(r.args, '.2f'):>6}"
            f"{_fmt(r.numbers, '.2f'):>6}{_fmt(r.tone_mean, '.2f'):>6}{_fmt(r.tone_min, '.0f'):>5}"
            f"{_fmt(r.p50, '.1f'):>6}{_fmt(r.p95, '.1f'):>6}{cost:>9}{r.runs:>5}{r.errors:>4}"
            f"  {'fail: ' + ','.join(failed) if failed else 'PASS'}"
        )
    return "\n".join(lines)


def write_dump(path: Path, runs: Sequence[ScoredRun], meta: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"meta": dict(meta), "runs": [dataclasses.asdict(r) for r in runs]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def load_dumps(paths: Sequence[Path]) -> list[ScoredRun]:
    """Runs from several dumps; a model found in a later dump replaces all its earlier runs
    (so a model rerun alone is not counted twice)."""
    runs: list[ScoredRun] = []
    for path in paths:
        new = [ScoredRun(**r) for r in json.loads(path.read_text())["runs"]]
        rerun = {r.model for r in new}
        runs = [r for r in runs if r.model not in rerun] + new
    return runs


def main(argv: Sequence[str] | None = None) -> int:
    paths = [Path(p) for p in (sys.argv[1:] if argv is None else argv)]
    if not paths:
        print("usage: python -m mermia_eval.gate DUMP.json [DUMP.json ...]", file=sys.stderr)
        return 2
    print(format_gate(gate_rows(load_dumps(paths))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
