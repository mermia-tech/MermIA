"""The 11 read RPCs, answered once each with the C3 contract examples.

The examples in `packages/contracts/tests/examples/rpc/` are the reference (aligned with the
El Güero seed and, for four RPCs, pinned to the live SQL), so the mock serves them as they are:
one fixed answer per RPC, the same whatever the request says. Variants: the example files named
`<rpc>.<variant>.json`, plus a generic `error` on every RPC. The answers are validated with the
C3 models before they are sent (app.py) and in the tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mermia_contracts.rpc import RPCS

Answer = dict[str, Any]
EXAMPLES = (
    Path(__file__).resolve().parents[4] / "packages" / "contracts" / "tests" / "examples" / "rpc"
)


def _examples() -> dict[tuple[str, str | None], dict[str, Any]]:
    found = {}
    for path in sorted(EXAMPLES.glob("*.json")):
        name, _, variant = path.stem.partition(".")
        found[(name, variant or None)] = json.loads(path.read_text())
    return found


_FILES = _examples()

# The args of each base example are the query the fixed answer is for.
CANONICAL: dict[str, Answer] = {name: _FILES[(name, None)]["args"] for name in RPCS}

VARIANTS: dict[str, tuple[str, ...]] = {
    name: ("error", *(v for (n, v) in _FILES if n == name and v and v != "error")) for name in RPCS
}


def build(name: str, variant: str | None = None) -> Answer:
    """The envelope of RPC `name`; `variant` must be one of `VARIANTS[name]` or None.

    Every answer carries a `mock_fixed_answer` flag: the request values are not used."""
    if variant is not None and variant not in VARIANTS[name]:
        raise KeyError(variant)
    example = _FILES.get((name, variant))
    if example is not None:
        answer: Answer = json.loads(json.dumps(example["response"]))  # a copy
    else:  # the generic `error` of an RPC that has no error example
        meta = {"as_of": _FILES[(name, None)]["response"]["meta"]["as_of"]}
        error = {"code": "no_data", "message": "Mock: the forced `error` variant"}
        answer = {"ok": False, "error": error, "flags": [], "meta": meta}
    message = (
        f"Mock: fixed answer to {json.dumps(CANONICAL[name])}; the request values are not used."
    )
    answer["flags"] = [*answer["flags"], {"code": "mock_fixed_answer", "message": message}]
    return answer
