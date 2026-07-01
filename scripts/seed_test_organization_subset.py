"""Copy a representative subset of default-org seed data into a tenant org.

This is intended for local tenant-isolation testing. It copies campaigns, leads,
staff, and their campaign assignments from the default organization into a target
organization without copying operational email history or secrets.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import tenant_service
from utils.db_connection import dict_from_row, get_conn


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict_from_row(row)
    if not data:
        raise ValueError("expected row but found none")
    return data


def _fetch_one(conn, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    return dict_from_row(conn.execute(sql, params).fetchone())


def _fetch_all(conn, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict_from_row(row) for row in conn.execute(sql, params).fetchall()]


def _half(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    return items[: max(1, len(items) // 2)]


def _target_org(conn, *, org_id: int | None, name: str, slug: str, create: bool) -> dict[str, Any]:
    if org_id:
        org = _fetch_one(conn, "SELECT * FROM organizations WHERE id = ?", (org_id,))
        if not org:
            raise ValueError(f"target organization id {org_id} not found")
        return org

    org = _fetch_one(
        conn,
        "SELECT * FROM organizations WHERE lower(name) = lower(?) OR lower(slug) = lower(?) ORDER BY id LIMIT 1",
        (name, slug),
    )
    if org:
        return org
    if not create:
        raise ValueError(f"target organization {name!r}/{slug!r} not found")

    cur = conn.execute(
        "INSERT INTO organizations (name, slug, timezone, status) VALUES (?, ?, 'Africa/Nairobi', 'ACTIVE')",
        (name, tenant_service.slugify(slug or name)),
    )
    return _row_to_dict(conn.execute("SELECT * FROM organizations WHERE id = ?", (cur.lastrowid,)).fetchone())


def _copy_campaign(conn, source: dict[str, Any], target_org_id: int, *, dry_run: bool) -> int | None:
    existing = _fetch_one(
        conn,
        "SELECT id FROM campaigns WHERE organization_id = ? AND name = ?",
        (target_org_id, source["name"]),
    )
    if existing:
        return int(existing["id"])
    if dry_run:
        return None
    cur = conn.execute(
        "INSERT INTO campaigns "
        "(organization_id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, "
        "lead_selection_order, auto_approve_drafts, auto_approve_monitor_replies, max_emails_per_lead, llm_routing_mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            target_org_id,
            source["name"],
            source.get("value_proposition"),
            source.get("cta"),
            source.get("status") or "ACTIVE",
            source.get("meeting_delay_days") or 1,
            source.get("max_leads_per_campaign"),
            source.get("lead_selection_order") or "newest_first",
            source.get("auto_approve_drafts") or 0,
            source.get("auto_approve_monitor_replies") or 0,
            source.get("max_emails_per_lead") or 5,
            source.get("llm_routing_mode"),
        ),
    )
    return int(cur.lastrowid)


def _copy_lead(conn, source: dict[str, Any], target_org_id: int, *, dry_run: bool) -> int | None:
    existing = _fetch_one(
        conn,
        "SELECT id FROM leads WHERE organization_id = ? AND lower(email) = lower(?)",
        (target_org_id, source["email"]),
    )
    if existing:
        return int(existing["id"])
    if dry_run:
        return None
    cur = conn.execute(
        "INSERT INTO leads "
        "(organization_id, email, name, company, industry, pain_points, status, email_opt_out, touch_count, "
        "last_contacted_at, last_inbound_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            target_org_id,
            source["email"],
            source.get("name"),
            source.get("company"),
            source.get("industry"),
            source.get("pain_points"),
            "NEW",
            source.get("email_opt_out") or 0,
            0,
            None,
            None,
        ),
    )
    return int(cur.lastrowid)


def _copy_staff(conn, source: dict[str, Any], target_org_id: int, *, dry_run: bool) -> int | None:
    existing = _fetch_one(
        conn,
        "SELECT id FROM staff WHERE organization_id = ? AND lower(email) = lower(?)",
        (target_org_id, source["email"]),
    )
    if existing:
        return int(existing["id"])
    if dry_run:
        return None
    cur = conn.execute(
        "INSERT INTO staff (organization_id, name, email, timezone, availability, dummy_slots) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            target_org_id,
            source["name"],
            source["email"],
            source.get("timezone"),
            source.get("availability"),
            source.get("dummy_slots"),
        ),
    )
    return int(cur.lastrowid)


def _copy_sequence_steps(
    conn,
    *,
    source_campaign_id: int,
    target_campaign_id: int | None,
    dry_run: bool,
) -> int:
    steps = _fetch_all(
        conn,
        "SELECT * FROM campaign_sequence_steps WHERE campaign_id = ? ORDER BY step_number",
        (source_campaign_id,),
    )
    copied = 0
    if dry_run or target_campaign_id is None:
        return len(steps)
    for step in steps:
        existing = _fetch_one(
            conn,
            "SELECT id FROM campaign_sequence_steps WHERE campaign_id = ? AND step_number = ?",
            (target_campaign_id, step["step_number"]),
        )
        if existing:
            continue
        conn.execute(
            "INSERT INTO campaign_sequence_steps "
            "(campaign_id, step_number, delay_days, subject_template, body_template, active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                target_campaign_id,
                step["step_number"],
                step.get("delay_days") or 3,
                step.get("subject_template"),
                step.get("body_template"),
                step.get("active") if step.get("active") is not None else 1,
            ),
        )
        copied += 1
    return copied


def seed_subset(
    *,
    source_org_id: int,
    target_org_id: int | None,
    target_name: str,
    target_slug: str,
    create_target: bool,
    dry_run: bool,
) -> dict[str, Any]:
    with get_conn() as conn:
        source_org = _fetch_one(conn, "SELECT * FROM organizations WHERE id = ?", (source_org_id,))
        if not source_org:
            raise ValueError(f"source organization id {source_org_id} not found")
        target_org = _target_org(
            conn,
            org_id=target_org_id,
            name=target_name,
            slug=target_slug,
            create=create_target,
        )
        resolved_target_org_id = int(target_org["id"])

        source_campaigns = _half(
            _fetch_all(conn, "SELECT * FROM campaigns WHERE organization_id = ? ORDER BY id", (source_org_id,))
        )
        source_leads = _half(
            _fetch_all(conn, "SELECT * FROM leads WHERE organization_id = ? ORDER BY id", (source_org_id,))
        )
        source_staff = _half(
            _fetch_all(conn, "SELECT * FROM staff WHERE organization_id = ? ORDER BY id", (source_org_id,))
        )

        campaign_id_map: dict[int, int] = {}
        lead_id_map: dict[int, int] = {}
        staff_id_map: dict[int, int] = {}

        for campaign in source_campaigns:
            copied_id = _copy_campaign(conn, campaign, resolved_target_org_id, dry_run=dry_run)
            if copied_id:
                campaign_id_map[int(campaign["id"])] = copied_id
                _copy_sequence_steps(
                    conn,
                    source_campaign_id=int(campaign["id"]),
                    target_campaign_id=copied_id,
                    dry_run=dry_run,
                )

        for lead in source_leads:
            copied_id = _copy_lead(conn, lead, resolved_target_org_id, dry_run=dry_run)
            if copied_id:
                lead_id_map[int(lead["id"])] = copied_id

        for staff in source_staff:
            copied_id = _copy_staff(conn, staff, resolved_target_org_id, dry_run=dry_run)
            if copied_id:
                staff_id_map[int(staff["id"])] = copied_id

        campaign_leads = _fetch_all(
            conn,
            "SELECT * FROM campaign_leads WHERE campaign_id IN ({}) AND lead_id IN ({})".format(
                ",".join("?" for _ in source_campaigns) or "NULL",
                ",".join("?" for _ in source_leads) or "NULL",
            ),
            tuple([item["id"] for item in source_campaigns] + [item["id"] for item in source_leads]),
        ) if source_campaigns and source_leads else []
        campaign_staff = _fetch_all(
            conn,
            "SELECT * FROM campaign_staff WHERE campaign_id IN ({}) AND staff_id IN ({})".format(
                ",".join("?" for _ in source_campaigns) or "NULL",
                ",".join("?" for _ in source_staff) or "NULL",
            ),
            tuple([item["id"] for item in source_campaigns] + [item["id"] for item in source_staff]),
        ) if source_campaigns and source_staff else []

        # The original demo seed links all seed leads to the first campaign. Some
        # local test DBs may have changed those joins during manual testing, so
        # preserve existing joins and fill gaps on the copied primary campaign.
        if source_campaigns and source_leads:
            primary_campaign_id = int(source_campaigns[0]["id"])
            existing_pairs = {
                (int(link["campaign_id"]), int(link["lead_id"]))
                for link in campaign_leads
            }
            for lead in source_leads:
                pair = (primary_campaign_id, int(lead["id"]))
                if pair not in existing_pairs:
                    campaign_leads.append(
                        {
                            "campaign_id": primary_campaign_id,
                            "lead_id": int(lead["id"]),
                            "emails_sent": 0,
                            "responded": 0,
                            "meeting_booked": 0,
                        }
                    )

        linked_leads = 0
        linked_staff = 0
        if not dry_run:
            for link in campaign_leads:
                next_campaign_id = campaign_id_map.get(int(link["campaign_id"]))
                next_lead_id = lead_id_map.get(int(link["lead_id"]))
                if not next_campaign_id or not next_lead_id:
                    continue
                exists = _fetch_one(
                    conn,
                    "SELECT 1 FROM campaign_leads WHERE campaign_id = ? AND lead_id = ?",
                    (next_campaign_id, next_lead_id),
                )
                if exists:
                    continue
                conn.execute(
                    "INSERT INTO campaign_leads (campaign_id, lead_id, emails_sent, responded, meeting_booked) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        next_campaign_id,
                        next_lead_id,
                        link.get("emails_sent") or 0,
                        link.get("responded") or 0,
                        link.get("meeting_booked") or 0,
                    ),
                )
                linked_leads += 1

            for link in campaign_staff:
                next_campaign_id = campaign_id_map.get(int(link["campaign_id"]))
                next_staff_id = staff_id_map.get(int(link["staff_id"]))
                if not next_campaign_id or not next_staff_id:
                    continue
                exists = _fetch_one(
                    conn,
                    "SELECT 1 FROM campaign_staff WHERE campaign_id = ? AND staff_id = ?",
                    (next_campaign_id, next_staff_id),
                )
                if exists:
                    continue
                conn.execute(
                    "INSERT INTO campaign_staff (campaign_id, staff_id) VALUES (?, ?)",
                    (next_campaign_id, next_staff_id),
                )
                linked_staff += 1

        return {
            "source_org": {"id": source_org["id"], "name": source_org["name"]},
            "target_org": {"id": target_org["id"], "name": target_org["name"], "slug": target_org["slug"]},
            "dry_run": dry_run,
            "selected": {
                "campaigns": len(source_campaigns),
                "leads": len(source_leads),
                "staff": len(source_staff),
                "campaign_leads": len(campaign_leads),
                "campaign_staff": len(campaign_staff),
            },
            "copied_or_existing": {
                "campaigns": len(campaign_id_map),
                "leads": len(lead_id_map),
                "staff": len(staff_id_map),
                "campaign_leads_created": linked_leads,
                "campaign_staff_created": linked_staff,
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-org-id", type=int, default=1)
    parser.add_argument("--target-org-id", type=int)
    parser.add_argument("--target-name", default="Test Organization")
    parser.add_argument("--target-slug", default="test-organization")
    parser.add_argument("--create-target", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = seed_subset(
        source_org_id=args.source_org_id,
        target_org_id=args.target_org_id,
        target_name=args.target_name,
        target_slug=args.target_slug,
        create_target=args.create_target,
        dry_run=args.dry_run,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
