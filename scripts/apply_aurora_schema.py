#!/usr/bin/env python3
"""Apply db/schema_pg.sql (and optionally db/seed_pg.sql) via Aurora Data API.

Requires: AWS credentials with rds-data:ExecuteStatement on the cluster;
           DB_CLUSTER_ARN, DB_SECRET_ARN, DB_NAME, AWS_REGION (default us-west-2).

Usage:
  uv run scripts/apply_aurora_schema.py
  uv run scripts/apply_aurora_schema.py --seed
"""

from __future__ import annotations

import argparse
import os
import re
import sys


def _strip_sql_comments(sql: str) -> str:
    out = []
    for line in sql.splitlines():
        s = line.strip()
        if s.startswith("--"):
            continue
        out.append(line)
    return "\n".join(out)


def _split_statements(sql: str) -> list[str]:
    sql = _strip_sql_comments(sql)
    parts = re.split(r";\s*", sql)
    return [p.strip() for p in parts if p.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply PostgreSQL schema/seed via Aurora Data API")
    parser.add_argument("--seed", action="store_true", help="Also run db/seed_pg.sql")
    args = parser.parse_args()

    cluster = os.environ.get("DB_CLUSTER_ARN")
    secret = os.environ.get("DB_SECRET_ARN")
    database = os.environ.get("DB_NAME", "sdr")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))

    if not cluster or not secret:
        print("Set DB_CLUSTER_ARN and DB_SECRET_ARN (e.g. from terraform/database outputs).", file=sys.stderr)
        return 1

    import boto3

    client = boto3.client("rds-data", region_name=region)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run_file(rel_path: str) -> None:
        path = os.path.join(root, rel_path)
        with open(path, encoding="utf-8") as f:
            body = f.read()
        for stmt in _split_statements(body):
            client.execute_statement(
                resourceArn=cluster,
                secretArn=secret,
                database=database,
                sql=stmt,
                includeResultMetadata=False,
            )
            preview = stmt[:100] + ("..." if len(stmt) > 100 else "")
            print(f"OK: {preview}")

    run_file("db/schema_pg.sql")
    if args.seed:
        run_file("db/seed_pg.sql")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
