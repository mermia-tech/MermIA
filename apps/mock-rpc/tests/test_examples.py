"""The mock serves the C3 examples: same data and meta, whatever the fixtures compute."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mermia_mock_rpc import rpcs
from mermia_mock_rpc.app import app

EXAMPLES = Path(__file__).parents[3] / "packages" / "contracts" / "tests" / "examples" / "rpc"
FILES = sorted(EXAMPLES.glob("*.json"))
client = TestClient(app)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_every_answer_equals_its_example(path: Path) -> None:
    name, _, variant = path.stem.partition(".")
    example = json.loads(path.read_text())["response"]
    url = f"/rpc/{name}" + (f"?variant={variant}" if variant else "")
    got: dict[str, Any] = client.post(url, json=rpcs.CANONICAL[name]).json()
    got["flags"] = [f for f in got["flags"] if not f["code"].startswith("mock_")]
    assert got == example


def test_every_rpc_has_a_base_example() -> None:
    assert {p.stem for p in FILES if "." not in p.stem} == set(rpcs.CANONICAL)


def test_canonical_query_is_the_example_args() -> None:
    for name, query in rpcs.CANONICAL.items():
        assert query == json.loads((EXAMPLES / f"{name}.json").read_text())["args"]
