import importlib
import os
from collections.abc import Mapping

import pytest
from fastapi.testclient import TestClient

from mermia_api.main import app


def test_health_returns_ok() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_turns_tracing_on_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from mermia_api import main
    from mermia_api.agent import llm

    seen: list[Mapping[str, str]] = []
    monkeypatch.setattr(llm, "setup_tracing", seen.append)
    importlib.reload(main)
    assert seen and seen[0] is os.environ
