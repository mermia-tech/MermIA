"""The committed schemas match the models; --check notices drift."""

import json
from pathlib import Path

from mermia_contracts.agent_tools import tool_definitions
from mermia_contracts.rpc import RPCS
from mermia_contracts.tools.export_schemas import DEFAULT_OUTPUT, main, stale_files


def test_committed_schemas_are_fresh() -> None:
    assert stale_files(DEFAULT_OUTPUT) == [], "run: python -m mermia_contracts.tools.export_schemas"


def test_one_args_and_response_schema_per_rpc() -> None:
    names = {p.name for p in DEFAULT_OUTPUT.glob("rpc.*.json")}
    assert names == {f"rpc.{n}.{kind}.json" for n in RPCS for kind in ("args", "response")}


def test_tools_file_matches_the_tool_definitions() -> None:
    assert json.loads((DEFAULT_OUTPUT / "agent.tools.json").read_text()) == tool_definitions()


def test_check_flags_a_changed_or_missing_file(tmp_path: Path) -> None:
    assert main(["--output", str(tmp_path)]) == 0
    assert main(["--output", str(tmp_path), "--check"]) == 0
    (tmp_path / "agent.request.json").write_text("{}\n")
    assert main(["--output", str(tmp_path), "--check"]) == 1
    (tmp_path / "agent.request.json").unlink()
    assert main(["--output", str(tmp_path), "--check"]) == 1


def test_output_is_deterministic(tmp_path: Path) -> None:
    main(["--output", str(tmp_path)])
    first = {p.name: p.read_text() for p in tmp_path.iterdir()}
    main(["--output", str(tmp_path)])
    assert {p.name: p.read_text() for p in tmp_path.iterdir()} == first
