"""Inspect where human-review drafts are saved.

Run with the same DATABASE_URL / DB_* environment as the app:
    uv run python scripts/inspect_drafts.py --organization-id 1 --limit 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.db_connection import dict_from_row, get_conn


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return [dict_from_row(row) for row in conn.execute(sql, params).fetchall()]


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n{title}")
    print("=" * len(title))
    if not rows:
        print("(none)")
        return
    columns = list(rows[0].keys())
    print("\t".join(columns))
    for row in rows:
        print("\t".join(str(row.get(column, "")) for column in columns))


def inspect_drafts(organization_id: int | None, limit: int) -> None:
    org_clause = "WHERE organization_id = ?" if organization_id else ""
    org_params: tuple[Any, ...] = (organization_id,) if organization_id else ()

    _print_table(
        "Email message counts by organization/status/approval/direction",
        _rows(
            f"""
            SELECT
                organization_id,
                direction,
                UPPER(COALESCE(status, '')) AS status,
                approved,
                COUNT(*) AS count
            FROM email_messages
            {org_clause}
            GROUP BY organization_id, direction, UPPER(COALESCE(status, '')), approved
            ORDER BY organization_id, direction, status, approved
            """,
            org_params,
        ),
    )

    where = ["e.direction = 'outbound'", "UPPER(COALESCE(e.status, '')) = 'DRAFT'", "e.approved = 0"]
    params: list[Any] = []
    if organization_id:
        where.append("e.organization_id = ?")
        params.append(organization_id)
    params.append(limit)

    _print_table(
        "Pending human-review drafts visible to /api/drafts",
        _rows(
            f"""
            SELECT
                e.id,
                e.organization_id,
                e.campaign_id,
                COALESCE(c.name, 'No campaign') AS campaign_name,
                e.lead_id,
                l.email AS lead_email,
                e.status,
                e.approved,
                e.direction,
                e.created_at
            FROM email_messages e
            JOIN leads l ON l.id = e.lead_id
            LEFT JOIN campaigns c ON c.id = e.campaign_id
            WHERE {" AND ".join(where)}
            ORDER BY e.id DESC
            LIMIT ?
            """,
            tuple(params),
        ),
    )

    orphan_params: list[Any] = []
    orphan_where = ["e.direction = 'outbound'", "UPPER(COALESCE(e.status, '')) = 'DRAFT'", "e.approved = 0"]
    if organization_id:
        orphan_where.append("e.organization_id = ?")
        orphan_params.append(organization_id)
    orphan_params.append(limit)
    _print_table(
        "Pending drafts hidden because their lead join is missing",
        _rows(
            f"""
            SELECT
                e.id,
                e.organization_id,
                e.campaign_id,
                e.lead_id,
                e.status,
                e.approved,
                e.direction,
                e.created_at
            FROM email_messages e
            LEFT JOIN leads l ON l.id = e.lead_id
            WHERE {" AND ".join(orphan_where)} AND l.id IS NULL
            ORDER BY e.id DESC
            LIMIT ?
            """,
            tuple(orphan_params),
        ),
    )

    recent_params: list[Any] = []
    recent_where = ["e.direction = 'outbound'"]
    if organization_id:
        recent_where.append("e.organization_id = ?")
        recent_params.append(organization_id)
    recent_params.append(limit)
    _print_table(
        "Latest outbound email_messages",
        _rows(
            f"""
            SELECT
                e.id,
                e.organization_id,
                e.campaign_id,
                COALESCE(c.name, 'No campaign') AS campaign_name,
                e.lead_id,
                l.email AS lead_email,
                e.status,
                e.approved,
                e.direction,
                e.created_at
            FROM email_messages e
            LEFT JOIN leads l ON l.id = e.lead_id
            LEFT JOIN campaigns c ON c.id = e.campaign_id
            WHERE {" AND ".join(recent_where)}
            ORDER BY e.id DESC
            LIMIT ?
            """,
            tuple(recent_params),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect saved outreach drafts without printing email bodies.")
    parser.add_argument("--organization-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    inspect_drafts(args.organization_id, max(1, args.limit))


if __name__ == "__main__":
    main()
