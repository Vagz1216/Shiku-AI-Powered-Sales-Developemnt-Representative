"""Apply the PostgreSQL schema to a standard Postgres database.

Usage:
    DATABASE_URL=postgresql://user:pass@host:5432/sdr?sslmode=require \
        uv run scripts/apply_postgres_schema.py

    DATABASE_URL=... uv run scripts/apply_postgres_schema.py --seed

This is the Azure/Postgres equivalent of scripts/apply_aurora_schema.py.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "schema_pg.sql"
SEED = ROOT / "db" / "seed_pg.sql"


def split_sql(script: str) -> list[str]:
    cleaned_lines = [
        line for line in script.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    cleaned = "\n".join(cleaned_lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def apply_file(conn: psycopg.Connection, path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    with conn.cursor() as cur:
        for statement in split_sql(path.read_text(encoding="utf-8")):
            cur.execute(statement)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply SDR PostgreSQL schema.")
    parser.add_argument("--seed", action="store_true", help="Also apply db/seed_pg.sql demo data.")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgres://", "postgresql://")):
        print("Set DATABASE_URL to a PostgreSQL connection string.", file=sys.stderr)
        return 2

    with psycopg.connect(database_url) as conn:
        apply_file(conn, SCHEMA)
        if args.seed:
            apply_file(conn, SEED)
        conn.commit()

    print("PostgreSQL schema applied.")
    if args.seed:
        print("Demo seed data applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
