"""The generated models agree with the live database, read through a different path."""

import enum
import types
import typing

import psycopg
import pytest

from mermia_contracts.db import models

pytestmark = pytest.mark.db


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def allows_none(annotation: object) -> bool:
    return type(None) in typing.get_args(annotation) or (
        isinstance(annotation, types.UnionType) and type(None) in annotation.__args__
    )


def test_every_table_and_column_is_modelled(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            """select table_name, column_name, is_nullable
               from information_schema.columns where table_schema = 'public'
               order by table_name, ordinal_position"""
        ).fetchall()
    tables: dict[str, list[tuple[str, bool]]] = {}
    for table, column, nullable in rows:
        tables.setdefault(table, []).append((column, nullable == "YES"))
    assert len(tables) == 40
    for table, columns in tables.items():
        cls = getattr(models, f"{pascal(table)}Row")
        fields = cls.model_fields
        assert list(fields) == [c for c, _ in columns], table
        for column, nullable in columns:
            field = fields[column]
            assert field.is_required() == (not nullable), f"{table}.{column}"
            assert allows_none(field.annotation) == nullable, f"{table}.{column}"


def test_every_enum_has_the_database_labels(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            """select t.typname, e.enumlabel from pg_type t
               join pg_enum e on e.enumtypid = t.oid
               where t.typnamespace = 'app'::regnamespace
               order by t.typname, e.enumsortorder"""
        ).fetchall()
    expected: dict[str, list[str]] = {}
    for name, label in rows:
        expected.setdefault(name, []).append(label)
    modelled = {
        name: cls
        for name, cls in vars(models).items()
        if isinstance(cls, type) and issubclass(cls, enum.StrEnum) and cls is not enum.StrEnum
    }
    assert len(expected) == len(modelled) == 24
    for name, labels in expected.items():
        assert [m.value for m in modelled[pascal(name)]] == labels, name
