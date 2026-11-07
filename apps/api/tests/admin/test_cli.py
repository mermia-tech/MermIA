"""CLI paths that need no database: they must pass in CI without MERMIA_DB_URL."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mermia_api.admin import cli

OPERATOR = "test-operator"
SPEC = {
    "tenant": {"name": "Taquería La Prueba"},
    "locations": [{"name": "Centro", "closed_days": []}],
    "users": [{"name": "Ana", "phone": "+525500000001", "role": "owner"}],
}


def test_the_cli_reports_an_invalid_spec(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({**SPEC, "users": []}))
    assert cli.main([str(path), "--dry-run", "--operator", OPERATOR]) == 2
    assert "users" in capsys.readouterr().err


def test_the_cli_needs_an_operator(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(SPEC))
    with pytest.raises(SystemExit) as exit_:
        cli.main([str(path), "--dry-run"])
    assert exit_.value.code == 2
    with pytest.raises(SystemExit):
        cli.main([str(path), "--dry-run", "--operator", "two words"])
