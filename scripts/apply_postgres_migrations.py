"""Apply PostgreSQL-safe incremental migrations.

This runner is intended for existing managed PostgreSQL databases after the
initial `db/schema_pg.sql` bootstrap. The older migration files include some
SQLite-only syntax, so this script deliberately starts at migration 013 where
the tracked files are Postgres-safe and idempotent.

Usage:
    DATABASE_URL=postgresql://user:pass@host:5432/sdr?sslmode=require \
        uv run scripts/apply_postgres_migrations.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"
POSTGRES_SAFE_START = 13

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def split_sql(script: str) -> list[str]:
    cleaned_lines = [
        line
        for line in script.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    cleaned = "\n".join(cleaned_lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def migration_number(path: Path) -> int | None:
    prefix = path.name.split("_", 1)[0]
    return int(prefix) if prefix.isdigit() else None


def migration_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        number = migration_number(path)
        if number is not None and number >= POSTGRES_SAFE_START:
            files.append(path)
    return files


def ensure_migration_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )


def applied_versions(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {str(row[0]) for row in rows}


def apply_migration(conn: psycopg.Connection, path: Path) -> None:
    for statement in split_sql(path.read_text(encoding="utf-8")):
        conn.execute(statement)
    conn.execute(
        "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
        (path.name,),
    )


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        from config.settings import settings

        database_url = settings.database_url or ""
    if not database_url.startswith(("postgres://", "postgresql://")):
        print("Set DATABASE_URL to a PostgreSQL connection string.", file=sys.stderr)
        return 2

    files = migration_files()
    if not files:
        print("No PostgreSQL-safe migrations found.")
        return 0

    with psycopg.connect(database_url) as conn:
        ensure_migration_table(conn)
        applied = applied_versions(conn)
        pending = [path for path in files if path.name not in applied]
        for path in pending:
            apply_migration(conn, path)
            print(f"Applied {path.name}")
        conn.commit()

    if not pending:
        print("PostgreSQL migrations already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
