from mermia_contracts.tools.gen_db_models import DEFAULT_MIGRATIONS_DIR


def test_uuid_v7_license_notice_is_kept_in_the_foundations_migration() -> None:
    (path,) = DEFAULT_MIGRATIONS_DIR.glob("*_foundations.sql")
    text = path.read_text()
    assert "Copyright (c) 2024-2025, Daniel Vérité" in text
    assert "Permission to use, copy, modify, and distribute this software" in text
    assert "In no event shall Daniel Vérité be liable" in text
    assert "Daniel Vérité specifically disclaims any warranties" in text
    assert "https://github.com/dverite/postgres-uuidv7-sql" in text


def test_migrations_are_timestamped_and_ordered() -> None:
    names = sorted(p.name for p in DEFAULT_MIGRATIONS_DIR.glob("*.sql"))
    assert [n.split("_", 1)[1] for n in names] == [
        "foundations.sql",
        "enums.sql",
        "identity_and_sources.sql",
        "ingestion.sql",
        "catalog_and_sales.sql",
        "control.sql",
        "costing.sql",
        "metrics.sql",
        "rls_location_scope.sql",
    ]
    assert all(n.split("_", 1)[0].isdigit() and len(n.split("_", 1)[0]) == 14 for n in names)
