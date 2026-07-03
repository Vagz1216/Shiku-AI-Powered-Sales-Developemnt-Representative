"""Compare two SDR databases without printing secrets.

This is intended for release checks before deploying code that changed schema or
seed data expectations.

Usage:
    LOCAL_DATABASE_URL=postgresql://... LIVE_DATABASE_URL=postgresql://... \
        uv run scripts/compare_databases.py

The script also supports SQLite URLs for local development, but production
migration checks are most useful when both sides are PostgreSQL.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg


IGNORED_TABLE_PREFIXES = ("pg_", "sql_")
IGNORED_TABLES = {"sqlite_sequence"}


@dataclass(frozen=True)
class Column:
    table: str
    name: str
    data_type: str
    nullable: bool
    default: str | None


@dataclass
class Snapshot:
    label: str
    engine: str
    tables: set[str]
    columns: dict[tuple[str, str], Column]
    indexes: set[str]
    migrations: set[str]
    row_counts: dict[str, int | None]


def is_postgres(url: str) -> bool:
    return url.startswith(("postgres://", "postgresql://"))


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite:///") or url == ":memory:"


def sqlite_path(url: str) -> str:
    if url == ":memory:":
        return url
    return url.removeprefix("sqlite:///")


def connect(url: str):
    if is_postgres(url):
        return psycopg.connect(url)
    if is_sqlite(url):
        return sqlite3.connect(sqlite_path(url))
    raise ValueError("Only postgresql://, postgres://, and sqlite:/// URLs are supported.")


def postgres_snapshot(label: str, conn: psycopg.Connection, include_counts: bool) -> Snapshot:
    table_rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    ).fetchall()
    tables = {row[0] for row in table_rows if not row[0].startswith(IGNORED_TABLE_PREFIXES)}

    column_rows = conn.execute(
        """
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """
    ).fetchall()
    columns = {
        (row[0], row[1]): Column(
            table=row[0],
            name=row[1],
            data_type=row[2],
            nullable=row[3] == "YES",
            default=row[4],
        )
        for row in column_rows
        if row[0] in tables
    }

    index_rows = conn.execute(
        """
        SELECT tablename, indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY tablename, indexname
        """
    ).fetchall()
    indexes = {f"{row[0]}.{row[1]}" for row in index_rows if row[0] in tables}

    migrations = set()
    if "schema_migrations" in tables:
        migrations = {str(row[0]) for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

    return Snapshot(
        label=label,
        engine="postgres",
        tables=tables,
        columns=columns,
        indexes=indexes,
        migrations=migrations,
        row_counts=row_counts(conn, tables, include_counts),
    )


def sqlite_snapshot(label: str, conn: sqlite3.Connection, include_counts: bool) -> Snapshot:
    conn.row_factory = sqlite3.Row
    table_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    tables = {
        row["name"]
        for row in table_rows
        if row["name"] not in IGNORED_TABLES and not row["name"].startswith(IGNORED_TABLE_PREFIXES)
    }

    columns: dict[tuple[str, str], Column] = {}
    indexes: set[str] = set()
    for table in sorted(tables):
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall():
            columns[(table, row["name"])] = Column(
                table=table,
                name=row["name"],
                data_type=row["type"],
                nullable=not bool(row["notnull"]),
                default=row["dflt_value"],
            )
        for row in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
            indexes.add(f"{table}.{row['name']}")

    migrations = set()
    if "schema_migrations" in tables:
        migrations = {str(row["version"]) for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

    return Snapshot(
        label=label,
        engine="sqlite",
        tables=tables,
        columns=columns,
        indexes=indexes,
        migrations=migrations,
        row_counts=row_counts(conn, tables, include_counts),
    )


def row_counts(conn: Any, tables: set[str], include_counts: bool) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    if not include_counts:
        return counts
    for table in sorted(tables):
        try:
            row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            counts[table] = int(row[0])
        except Exception:
            counts[table] = None
    return counts


def snapshot(label: str, url: str, include_counts: bool) -> Snapshot:
    with connect(url) as conn:
        if is_postgres(url):
            return postgres_snapshot(label, conn, include_counts)
        return sqlite_snapshot(label, conn, include_counts)


def print_section(title: str, rows: list[str]) -> None:
    print(f"\n## {title}")
    if not rows:
        print("OK")
        return
    for row in rows:
        print(f"- {row}")


def compare(left: Snapshot, right: Snapshot) -> int:
    print(f"# Database Comparison: {left.label} -> {right.label}")
    print(f"Engines: {left.label}={left.engine}, {right.label}={right.engine}")

    left_only_tables = sorted(left.tables - right.tables)
    right_only_tables = sorted(right.tables - left.tables)
    print_section(f"Tables only in {left.label}", left_only_tables)
    print_section(f"Tables only in {right.label}", right_only_tables)

    left_only_columns = sorted(left.columns.keys() - right.columns.keys())
    right_only_columns = sorted(right.columns.keys() - left.columns.keys())
    changed_columns = []
    for key in sorted(left.columns.keys() & right.columns.keys()):
        lcol = left.columns[key]
        rcol = right.columns[key]
        if (lcol.data_type, lcol.nullable, normalize_default(lcol.default)) != (
            rcol.data_type,
            rcol.nullable,
            normalize_default(rcol.default),
        ):
            changed_columns.append(
                f"{key[0]}.{key[1]}: "
                f"{left.label}=({lcol.data_type}, nullable={lcol.nullable}, default={normalize_default(lcol.default)}) "
                f"{right.label}=({rcol.data_type}, nullable={rcol.nullable}, default={normalize_default(rcol.default)})"
            )

    print_section(f"Columns only in {left.label}", [f"{table}.{column}" for table, column in left_only_columns])
    print_section(f"Columns only in {right.label}", [f"{table}.{column}" for table, column in right_only_columns])
    print_section("Changed column definitions", changed_columns)

    print_section(f"Indexes only in {left.label}", sorted(left.indexes - right.indexes))
    print_section(f"Indexes only in {right.label}", sorted(right.indexes - left.indexes))

    if left.migrations or right.migrations:
        print_section(f"Migrations only in {left.label}", sorted(left.migrations - right.migrations))
        print_section(f"Migrations only in {right.label}", sorted(right.migrations - left.migrations))

    if left.row_counts or right.row_counts:
        count_rows = []
        for table in sorted(left.tables | right.tables):
            lcount = left.row_counts.get(table)
            rcount = right.row_counts.get(table)
            if lcount != rcount:
                count_rows.append(f"{table}: {left.label}={lcount}, {right.label}={rcount}")
        print_section("Row count differences", count_rows)

    has_drift = bool(
        left_only_tables
        or right_only_tables
        or left_only_columns
        or right_only_columns
        or changed_columns
        or (left.indexes - right.indexes)
        or (right.indexes - left.indexes)
        or (left.migrations - right.migrations)
        or (right.migrations - left.migrations)
    )
    return 1 if has_drift else 0


def normalize_default(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split())


def redacted_location(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.startswith("postgres"):
        return f"{parsed.scheme}://***@{parsed.hostname or 'unknown'}/{parsed.path.lstrip('/') or 'unknown'}"
    if parsed.scheme == "sqlite":
        return f"sqlite:///{Path(sqlite_path(url)).name}"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare local and live SDR database schema/data shape.")
    parser.add_argument("--left-env", default="LOCAL_DATABASE_URL", help="Environment variable for the source/local DB URL.")
    parser.add_argument("--right-env", default="LIVE_DATABASE_URL", help="Environment variable for the target/live DB URL.")
    parser.add_argument("--left-label", default="local")
    parser.add_argument("--right-label", default="live")
    parser.add_argument("--schema-only", action="store_true", help="Skip row count comparison.")
    args = parser.parse_args()

    left_url = os.environ.get(args.left_env)
    right_url = os.environ.get(args.right_env)
    if not left_url or not right_url:
        print(
            f"Set both {args.left_env} and {args.right_env}. "
            "Do not pass secrets as command-line arguments.",
            file=sys.stderr,
        )
        return 2

    print(f"Reading {args.left_label}: {redacted_location(left_url)}")
    print(f"Reading {args.right_label}: {redacted_location(right_url)}")
    left = snapshot(args.left_label, left_url, include_counts=not args.schema_only)
    right = snapshot(args.right_label, right_url, include_counts=not args.schema_only)
    return compare(left, right)


if __name__ == "__main__":
    raise SystemExit(main())
