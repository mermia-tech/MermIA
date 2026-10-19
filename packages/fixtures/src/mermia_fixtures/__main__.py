"""Regenerate the fixture files: `uv run python -m mermia_fixtures [--check]`."""

from __future__ import annotations

import argparse
import sys

from mermia_fixtures.emit import REPO, render


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if a committed file is stale")
    args = parser.parse_args()
    files = render()
    stale = [
        p
        for p, data in files.items()
        if not (REPO / p).is_file() or (REPO / p).read_bytes() != data
    ]
    if args.check:
        for p in stale:
            print(f"stale: {p}", file=sys.stderr)
        if stale:
            print("run: uv run python -m mermia_fixtures", file=sys.stderr)
        return 1 if stale else 0
    for p in stale:
        (REPO / p).parent.mkdir(parents=True, exist_ok=True)
        (REPO / p).write_bytes(files[p])
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
