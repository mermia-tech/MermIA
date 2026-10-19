import re
from pathlib import Path

from mermia_contracts.tools.gen_db_models import (
    DEFAULT_MIGRATIONS_DIR,
    DEFAULT_OUTPUT,
    compute_migrations_hash,
)


def test_header_hash_matches_the_migrations() -> None:
    header = DEFAULT_OUTPUT.read_text()
    match = re.search(r"migrations_sha256: ([0-9a-f]{64})", header)
    assert match, "generated file has no migrations_sha256 header"
    assert compute_migrations_hash(DEFAULT_MIGRATIONS_DIR) == match.group(1), (
        "migrations changed since the models were generated: run gen_db_models"
    )


def test_hash_changes_when_a_byte_changes(tmp_path: Path) -> None:
    (tmp_path / "1_a.sql").write_text("select 1;")
    before = compute_migrations_hash(tmp_path)
    (tmp_path / "1_a.sql").write_text("select 2;")
    assert compute_migrations_hash(tmp_path) != before


def test_hash_changes_when_a_file_is_added_or_renamed(tmp_path: Path) -> None:
    (tmp_path / "1_a.sql").write_text("select 1;")
    before = compute_migrations_hash(tmp_path)
    (tmp_path / "2_b.sql").write_text("")
    with_extra = compute_migrations_hash(tmp_path)
    assert with_extra != before
    (tmp_path / "2_b.sql").rename(tmp_path / "2_c.sql")
    assert compute_migrations_hash(tmp_path) != with_extra


def test_hash_ignores_other_files(tmp_path: Path) -> None:
    (tmp_path / "1_a.sql").write_text("select 1;")
    before = compute_migrations_hash(tmp_path)
    (tmp_path / "notes.txt").write_text("not a migration")
    assert compute_migrations_hash(tmp_path) == before
