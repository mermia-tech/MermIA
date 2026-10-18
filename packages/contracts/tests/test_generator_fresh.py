import psycopg
import pytest

from mermia_contracts.tools.gen_db_models import (
    DEFAULT_MIGRATIONS_DIR,
    DEFAULT_OUTPUT,
    generate,
    main,
)

pytestmark = pytest.mark.db


def test_committed_models_equal_a_fresh_generation(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        fresh = generate(conn, DEFAULT_MIGRATIONS_DIR)
    assert fresh == DEFAULT_OUTPUT.read_text()


def test_generation_is_deterministic(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        first = generate(conn, DEFAULT_MIGRATIONS_DIR)
        second = generate(conn, DEFAULT_MIGRATIONS_DIR)
    assert first == second


def test_check_mode_passes_when_current_and_fails_when_stale(
    db_url: str, tmp_path
) -> None:
    out = tmp_path / "models.py"
    out.write_text(DEFAULT_OUTPUT.read_text())
    assert main(["--db-url", db_url, "--output", str(out), "--check"]) == 0
    out.write_text(out.read_text() + "\n# drift\n")
    assert main(["--db-url", db_url, "--output", str(out), "--check"]) == 1
    assert (
        main(["--db-url", db_url, "--output", str(tmp_path / "missing.py"), "--check"])
        == 1
    )
