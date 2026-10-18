"""Generate db/models.py from the migrated database, deterministically.

Usage:
    python -m mermia_contracts.tools.gen_db_models [--db-url URL] [--check]

The database must already have the migrations applied (`supabase db reset`). The output
has no timestamps and does not depend on an external formatter, so it is byte-identical
across machines. Its header records the SHA-256 of the migrations it was generated from.
`--check` regenerates in memory and fails if the committed file differs.
"""

from __future__ import annotations

import argparse
import hashlib
import keyword
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import psycopg

from mermia_contracts.db.overrides import OVERRIDES

GENERATOR_VERSION = 1
DEFAULT_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
PACKAGE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
DEFAULT_OUTPUT = PACKAGE_ROOT / "src" / "mermia_contracts" / "db" / "models.py"

SIMPLE_TYPES = {
    "uuid": "UUID",
    "text": "str",
    "varchar": "str",
    "bpchar": "str",
    "int2": "int",
    "int4": "int",
    "bool": "bool",
    "date": "dt.date",
    "timestamptz": "AwareDatetime",
    "bytea": "bytes",
}
# (postgres type, type modifier text, unit tag) -> alias from db/types.py
BIGINT_ALIASES = {"unit=centavos": "Cents", "unit=bytes": "Bytes"}
NUMERIC_ALIASES = {
    ("numeric(18,6)", "unit=quantity"): "Quantity",
    ("numeric(20,10)", "unit=quantity"): "Factor",
    ("numeric(20,6)", "unit=pesos_per_base_unit"): "UnitPricePesosPerBaseUnit",
    ("numeric(20,6)", "unit=pesos_per_purchase_unit"): "UnitPricePesosPerPurchaseUnit",
    ("numeric(7,4)", "unit=percent_points"): "PercentPoints",
    ("numeric(5,4)", "unit=fraction"): "Fraction",
    ("numeric(12,6)", "unit=usd"): "Usd",
}


@dataclass(frozen=True)
class Column:
    name: str
    pg_type: str
    sql_type: str
    is_enum: bool
    array_of: str | None
    not_null: bool
    comment: str | None


@dataclass(frozen=True)
class Table:
    name: str
    comment: str | None
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class EnumType:
    name: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class Schema:
    enums: tuple[EnumType, ...]
    tables: tuple[Table, ...]


def compute_migrations_hash(migrations_dir: Path) -> str:
    """SHA-256 over the sorted migration file names and contents."""
    digest = hashlib.sha256()
    for path in sorted(migrations_dir.glob("*.sql")):
        digest.update(path.name.encode() + b"\n")
        digest.update(path.read_bytes() + b"\n")
    return digest.hexdigest()


ENUMS_SQL = """
select t.typname::text, array_agg(e.enumlabel::text order by e.enumsortorder)
from pg_type t join pg_enum e on e.enumtypid = t.oid
where t.typnamespace = 'app'::regnamespace
group by t.typname order by t.typname
"""

TABLES_SQL = """
select c.relname::text, obj_description(c.oid, 'pg_class')
from pg_class c
where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
order by c.relname
"""

COLUMNS_SQL = """
select c.relname::text, a.attname::text, t.typname::text, t.typtype::text,
       format_type(a.atttypid, a.atttypmod), te.typname::text, a.attnotnull,
       col_description(c.oid, a.attnum)
from pg_attribute a
join pg_class c on c.oid = a.attrelid
join pg_type t on t.oid = a.atttypid
left join pg_type te on te.oid = t.typelem and t.typcategory = 'A'
where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
  and a.attnum > 0 and not a.attisdropped
order by c.relname, a.attnum
"""


def introspect(conn: psycopg.Connection) -> Schema:
    enums = tuple(
        EnumType(name, tuple(labels)) for name, labels in conn.execute(ENUMS_SQL)
    )
    table_comments: dict[str, str | None] = dict(conn.execute(TABLES_SQL).fetchall())
    columns: dict[str, list[Column]] = {name: [] for name in table_comments}
    for rel, name, typ, typtype, sql_type, elem, not_null, comment in conn.execute(
        COLUMNS_SQL
    ):
        columns[rel].append(
            Column(
                name=name,
                pg_type=typ,
                sql_type=sql_type,
                is_enum=typtype == "e",
                array_of=elem,
                not_null=not_null,
                comment=comment,
            )
        )
    tables = tuple(
        Table(name, table_comments[name], tuple(columns[name]))
        for name in sorted(table_comments)
    )
    return Schema(enums, tables)


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def member_name(label: str) -> str:
    return label + "_" if keyword.iskeyword(label) else label


def python_type(table: str, col: Column, used: set[str]) -> str:
    """The annotation for a column, without the `| None` part."""
    override = OVERRIDES.get((table, col.name))
    if override:
        used.add(override)
        return override
    if col.array_of:
        inner = element_type(col.array_of)
        used.add(inner)
        return f"list[{inner}]"
    if col.is_enum:
        return pascal(col.pg_type)
    if col.pg_type == "int8":
        return BIGINT_ALIASES.get(col.comment or "", "int")
    if col.pg_type == "numeric":
        return NUMERIC_ALIASES.get((col.sql_type, col.comment or ""), "Decimal")
    if col.pg_type == "jsonb":
        return "JsonValue"
    try:
        return SIMPLE_TYPES[col.pg_type]
    except KeyError:
        raise SystemExit(f"{table}.{col.name}: unsupported type {col.sql_type}")


def element_type(pg_elem: str) -> str:
    try:
        return SIMPLE_TYPES[pg_elem.lstrip("_")]
    except KeyError:
        raise SystemExit(f"unsupported array element type {pg_elem}")


ALIAS_NAMES = (
    "Bytes", "Cents", "Factor", "Fraction", "PercentPoints", "Quantity", "Usd",
    "UnitPricePesosPerBaseUnit", "UnitPricePesosPerPurchaseUnit",
)  # fmt: skip


def render(schema: Schema, migrations_hash: str) -> str:
    body: list[str] = []
    used: set[str] = set()

    for enum in schema.enums:
        body += ["", "", f"class {pascal(enum.name)}(StrEnum):"]
        body += [f'    {member_name(lb)} = "{lb}"' for lb in enum.labels]

    for table in schema.tables:
        body += ["", "", f"class {pascal(table.name)}Row(RowModel):"]
        body += [f'    """Row of public.{table.name}. {table.comment}."""', ""]
        for col in table.columns:
            annotation = python_type(table.name, col, used)
            used.add(annotation.split("[")[0])
            if col.not_null:
                body.append(f"    {col.name}: {annotation}")
            else:
                body.append(f"    {col.name}: {annotation} | None = None")

    overrides = sorted({v for v in OVERRIDES.values() if v in used})
    stdlib = ["import datetime as dt"] if "dt.date" in used else []
    stdlib += ["from decimal import Decimal"] if "Decimal" in used else []
    stdlib += ["from enum import StrEnum"] if schema.enums else []
    stdlib += ["from uuid import UUID"] if "UUID" in used else []
    pyd = [n for n in ("AwareDatetime", "JsonValue") if n in used]
    third = [import_line("pydantic", pyd)] if pyd else []
    first: list[str] = []
    if overrides:
        first.append(import_line("mermia_contracts.db.overrides", overrides))
    aliases = sorted(a for a in ALIAS_NAMES if a in used) + ["RowModel"]
    first.append(import_line("mermia_contracts.db.types", sorted(aliases)))

    header = [
        '"""Row models of the public schema. GENERATED: do not edit.',
        "",
        "Regenerate with `python -m mermia_contracts.tools.gen_db_models` after",
        "`supabase db reset`. Source of truth: supabase/migrations.",
        "",
        f"generator_version: {GENERATOR_VERSION}",
        f"migrations_sha256: {migrations_hash}",
        '"""',
        "",
        "",
    ]
    groups = ["\n".join(g) for g in (stdlib, third, first) if g]
    return "\n".join(header) + "\n\n".join(groups) + "\n" + "\n".join(body) + "\n"


def import_line(module: str, names: Sequence[str]) -> str:
    """One import statement, wrapped the way `ruff format` wraps it."""
    line = f"from {module} import {', '.join(names)}"
    if len(line) <= 88:
        return line
    inner = "".join(f"    {name},\n" for name in names)
    return f"from {module} import (\n{inner})"


def generate(conn: psycopg.Connection, migrations_dir: Path) -> str:
    return render(introspect(conn), compute_migrations_hash(migrations_dir))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--db-url", default=os.environ.get("MERMIA_DB_URL", DEFAULT_DB_URL)
    )
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    with psycopg.connect(args.db_url) as conn:
        text = generate(conn, args.migrations_dir)

    if args.check:
        current = args.output.read_text() if args.output.exists() else ""
        if current != text:
            print(f"{args.output} is stale: regenerate it.", file=sys.stderr)
            return 1
        print(f"{args.output} is up to date.")
        return 0
    args.output.write_text(text)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
