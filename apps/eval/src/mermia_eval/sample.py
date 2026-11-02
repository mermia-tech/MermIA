"""`python -m mermia_eval.sample DUMP.json`: 10 replies for the human tone check (MR-20 D2),
spread across models and categories."""

import random
import sys
from collections.abc import Sequence
from pathlib import Path

from mermia_eval.gate import ScoredRun, load_dumps


def sample_for_review(runs: Sequence[ScoredRun], n: int = 10, seed: int = 20) -> list[ScoredRun]:
    """Round robin over (model, category) groups in seeded random order, so the sample spreads."""
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[ScoredRun]] = {}
    for r in runs:
        if r.error is None:
            groups.setdefault((r.model, r.category), []).append(r)
    queues = [groups[k] for k in sorted(groups)]
    rng.shuffle(queues)
    for q in queues:
        rng.shuffle(q)
    picked: list[ScoredRun] = []
    while len(picked) < n and any(queues):
        for q in queues:
            if q and len(picked) < n:
                picked.append(q.pop())
    return picked


def main(argv: Sequence[str] | None = None) -> int:
    paths = [Path(p) for p in (sys.argv[1:] if argv is None else argv)]
    if not paths:
        print("usage: python -m mermia_eval.sample DUMP.json [DUMP.json ...]", file=sys.stderr)
        return 2
    for i, r in enumerate(sample_for_review(load_dumps(paths)), 1):
        cross = "" if r.tone_cross is None else f", cross judge {r.tone_cross}"
        print(f"--- {i}. {r.model} / {r.category} / {r.case_id}")
        print(f"Q: {r.question}\nA: {r.reply}")
        print(f"judge: {r.tone}{cross} ({r.tone_reason})\nhuman: _/5\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
