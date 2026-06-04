"""Campaign follow-up sequence management and due-draft generation."""

from __future__ import annotations

import datetime
import json
from typing import Any

from config import settings
from services import campaign_context_service
from utils.db_connection import get_conn, dict_from_row, sql_bool_false, sql_bool_true
from utils.quick_replies import quick_replies_for_followup

DEFAULT_SEQUENCE_STEPS = [
    {
        "step_number": 1,
        "delay_days": 3,
        "subject_template": "Re: {campaign_name}",
        "body_template": (
            "Hi {name},\n\n"
            "{context_hint}I wanted to follow up on my note about {value_proposition}. "
            "{company} may be dealing with similar priorities around {pain_points}.\n\n"
            "{cta}\n\n"
            "Best,\n{sender_name}"
        ),
    },
    {
        "step_number": 2,
        "delay_days": 5,
        "subject_template": "Worth revisiting?",
        "body_template": (
            "Hi {name},\n\n"
            "{context_hint}Checking once more in case this is useful. If improving {pain_points} is on the roadmap, "
            "I can share a brief view of how teams use {sender_company} for {value_proposition}.\n\n"
            "{cta}\n\n"
            "Best,\n{sender_name}"
        ),
    },
]


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _now_iso() -> str:
    return _now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_dt(value: Any) -> datetime.datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _render(template: str, context: dict[str, Any]) -> str:
    class SafeDict(dict):
        def __missing__(self, key):
            return ""

    return template.format_map(SafeDict({k: "" if v is None else v for k, v in context.items()})).strip()


def _context_hint(context: dict[str, Any]) -> str:
    if context.get("last_inbound_summary"):
        return "Based on your last note, I wanted to keep this focused on what you shared. "
    if context.get("last_outbound_summary"):
        return "I know timing may not have been right when I reached out earlier. "
    return ""


def ensure_default_steps(campaign_id: int) -> list[dict[str, Any]]:
    existing = list_sequence_steps(campaign_id)
    if existing:
        return existing
    replace_sequence_steps(campaign_id, DEFAULT_SEQUENCE_STEPS)
    return list_sequence_steps(campaign_id)


def ensure_default_steps_for_active_campaigns(organization_id: int | None = None) -> None:
    with get_conn() as conn:
        org_sql = "WHERE c.organization_id = ?" if organization_id is not None else ""
        rows = conn.execute(
            "SELECT c.id FROM campaigns c "
            "LEFT JOIN campaign_sequence_steps s ON s.campaign_id = c.id "
            f"{org_sql} "
            f"{'AND' if organization_id is not None else 'WHERE'} c.status = 'ACTIVE' GROUP BY c.id HAVING COUNT(s.id) = 0",
            (organization_id,) if organization_id is not None else (),
        ).fetchall()
    for row in rows:
        data = dict_from_row(row)
        if data:
            ensure_default_steps(int(data["id"]))


def list_sequence_steps(campaign_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, campaign_id, step_number, delay_days, subject_template, body_template, active, created_at "
            "FROM campaign_sequence_steps WHERE campaign_id = ? ORDER BY step_number ASC",
            (campaign_id,),
        ).fetchall()
    return [dict_from_row(row) for row in rows]


def replace_sequence_steps(campaign_id: int, steps: list[dict[str, Any]], organization_id: int | None = None) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in steps:
        step_number = int(raw.get("step_number") or 0)
        if step_number <= 0 or step_number in seen:
            raise ValueError("step_number values must be unique positive integers")
        delay_days = int(raw.get("delay_days") if raw.get("delay_days") is not None else 3)
        if delay_days < 1:
            raise ValueError("delay_days must be at least 1")
        cleaned.append(
            {
                "step_number": step_number,
                "delay_days": delay_days,
                "subject_template": str(raw.get("subject_template") or "").strip(),
                "body_template": str(raw.get("body_template") or "").strip(),
                "active": bool(raw.get("active", True)),
            }
        )
        seen.add(step_number)

    with get_conn() as conn:
        campaign = conn.execute(
            "SELECT id, organization_id FROM campaigns WHERE id = ? "
            + ("AND organization_id = ?" if organization_id is not None else ""),
            (campaign_id, organization_id) if organization_id is not None else (campaign_id,),
        ).fetchone()
        if not campaign:
            raise ValueError("campaign not found")
        with conn:
            conn.execute("DELETE FROM campaign_sequence_steps WHERE campaign_id = ?", (campaign_id,))
            for step in cleaned:
                conn.execute(
                    "INSERT INTO campaign_sequence_steps "
                    "(campaign_id, step_number, delay_days, subject_template, body_template, active) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        campaign_id,
                        step["step_number"],
                        step["delay_days"],
                        step["subject_template"],
                        step["body_template"],
                        step["active"],
                    ),
                )
            conn.execute(
                "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                (campaign["organization_id"], "campaign_sequence_updated", json.dumps({"campaign_id": campaign_id, "step_count": len(cleaned)}), None),
            )
    return list_sequence_steps(campaign_id)


def generate_due_followup_drafts(campaign_id: int | None = None, limit: int = 50, organization_id: int | None = None) -> dict[str, Any]:
    """Create follow-up drafts for leads whose next active sequence step is due."""
    generated: list[dict[str, Any]] = []
    skipped = 0
    now = _now()
    if campaign_id is None:
        ensure_default_steps_for_active_campaigns(organization_id)
    with get_conn() as conn:
        params: list[Any] = []
        campaign_filter = ""
        if campaign_id is not None:
            campaign_filter = "AND c.id = ?"
            params.append(campaign_id)
            ensure_default_steps(campaign_id)
        if organization_id is not None:
            campaign_filter += " AND c.organization_id = ? AND l.organization_id = ?"
            params.extend([organization_id, organization_id])

        rows = conn.execute(
            "SELECT c.id AS campaign_id, c.organization_id, c.name AS campaign_name, c.value_proposition, c.cta, "
            "c.max_emails_per_lead, l.id AS lead_id, l.email, l.name, l.company, l.industry, "
            "l.pain_points, l.status, l.last_contacted_at, cl.emails_sent, cl.responded, cl.meeting_booked, "
            "s.id AS sequence_step_id, s.step_number, s.delay_days, s.subject_template, s.body_template, "
            "ctx.last_outbound_subject, ctx.last_outbound_summary, ctx.last_inbound_subject, "
            "ctx.last_inbound_summary, ctx.latest_intent "
            "FROM campaign_leads cl "
            "JOIN campaigns c ON c.id = cl.campaign_id "
            "JOIN leads l ON l.id = cl.lead_id "
            "JOIN campaign_sequence_steps s ON s.campaign_id = c.id AND s.step_number = cl.emails_sent "
            "LEFT JOIN campaign_lead_contexts ctx ON ctx.campaign_id = c.id AND ctx.lead_id = l.id "
            f"WHERE c.status = 'ACTIVE' AND s.active = {sql_bool_true()} AND l.email_opt_out = {sql_bool_false()} "
            f"AND l.status != 'OPTED_OUT' AND cl.responded = {sql_bool_false()} AND cl.meeting_booked = {sql_bool_false()} "
            "AND cl.emails_sent < c.max_emails_per_lead "
            f"{campaign_filter} "
            "ORDER BY l.last_contacted_at ASC LIMIT ?",
            tuple([*params, max(1, min(limit, 200))]),
        ).fetchall()

        with conn:
            for row in rows:
                item = dict_from_row(row) or {}
                last_contacted = _parse_dt(item.get("last_contacted_at"))
                if not last_contacted or now - last_contacted < datetime.timedelta(days=int(item["delay_days"])):
                    skipped += 1
                    continue
                duplicate = conn.execute(
                    "SELECT id FROM email_messages WHERE lead_id = ? AND campaign_id = ? AND sequence_step_id = ? "
                    "AND direction = 'outbound' AND UPPER(COALESCE(status, '')) IN ('DRAFT','SCHEDULED','SENT') LIMIT 1",
                    (item["lead_id"], item["campaign_id"], item["sequence_step_id"]),
                ).fetchone()
                if duplicate:
                    skipped += 1
                    continue

                context = {
                    **item,
                    "name": item.get("name") or "there",
                    "company": item.get("company") or "your team",
                    "pain_points": item.get("pain_points") or "your current priorities",
                    "sender_name": settings.outreach_sender_name,
                    "sender_company": settings.outreach_sender_company,
                    "conversation_context": campaign_context_service.format_context_for_followup(item),
                    "context_hint": _context_hint(item),
                }
                subject = _render(item.get("subject_template") or "Re: {campaign_name}", context)
                body = _render(item.get("body_template") or DEFAULT_SEQUENCE_STEPS[0]["body_template"], context)
                body = body + quick_replies_for_followup(
                    subject,
                    lead_email=item["email"],
                    campaign_id=item["campaign_id"],
                    organization_id=item["organization_id"],
                )
                cur = conn.execute(
                    "INSERT INTO email_messages "
                    "(organization_id, lead_id, campaign_id, sequence_step_id, direction, subject, body, status, processed, approved, created_at) "
                    "VALUES (?, ?, ?, ?, 'outbound', ?, ?, 'DRAFT', 1, 0, ?)",
                    (item["organization_id"], item["lead_id"], item["campaign_id"], item["sequence_step_id"], subject, body, _now_iso()),
                )
                campaign_context_service.record_outbound(
                    conn,
                    organization_id=item["organization_id"],
                    campaign_id=item["campaign_id"],
                    lead_id=item["lead_id"],
                    subject=subject,
                    body=body,
                )
                generated.append(
                    {
                        "draft_id": cur.lastrowid,
                        "lead_id": item["lead_id"],
                        "lead_email": item["email"],
                        "campaign_id": item["campaign_id"],
                        "sequence_step_id": item["sequence_step_id"],
                        "step_number": item["step_number"],
                    }
                )
            if generated:
                conn.execute(
                    "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                    (organization_id, "followup_drafts_generated", json.dumps({"count": len(generated)}), None),
                )

    return {
        "status": "success",
        "generated": len(generated),
        "skipped": skipped,
        "drafts": generated,
    }


def list_upcoming_followups(campaign_id: int | None = None, limit: int = 100, organization_id: int | None = None) -> dict[str, Any]:
    """List leads whose next follow-up sequence step is pending or due."""
    if campaign_id is None:
        ensure_default_steps_for_active_campaigns(organization_id)
    else:
        ensure_default_steps(campaign_id)

    now = _now()
    upcoming: list[dict[str, Any]] = []
    with get_conn() as conn:
        params: list[Any] = []
        campaign_filter = ""
        if campaign_id is not None:
            campaign_filter = "AND c.id = ?"
            params.append(campaign_id)
        if organization_id is not None:
            campaign_filter += " AND c.organization_id = ? AND l.organization_id = ?"
            params.extend([organization_id, organization_id])

        rows = conn.execute(
            "SELECT c.id AS campaign_id, c.name AS campaign_name, l.id AS lead_id, l.email, l.name, "
            "l.company, l.status, l.last_contacted_at, cl.emails_sent, cl.responded, cl.meeting_booked, "
            "s.id AS sequence_step_id, s.step_number, s.delay_days "
            "FROM campaign_leads cl "
            "JOIN campaigns c ON c.id = cl.campaign_id "
            "JOIN leads l ON l.id = cl.lead_id "
            "JOIN campaign_sequence_steps s ON s.campaign_id = c.id AND s.step_number = cl.emails_sent "
            f"WHERE c.status = 'ACTIVE' AND s.active = {sql_bool_true()} AND l.email_opt_out = {sql_bool_false()} "
            f"AND l.status != 'OPTED_OUT' AND cl.responded = {sql_bool_false()} AND cl.meeting_booked = {sql_bool_false()} "
            "AND cl.emails_sent < c.max_emails_per_lead "
            f"{campaign_filter} "
            "ORDER BY l.last_contacted_at ASC LIMIT ?",
            tuple([*params, max(1, min(limit, 500))]),
        ).fetchall()

        for row in rows:
            item = dict_from_row(row) or {}
            duplicate = conn.execute(
                "SELECT id, status FROM email_messages WHERE lead_id = ? AND campaign_id = ? AND sequence_step_id = ? "
                "AND direction = 'outbound' AND UPPER(COALESCE(status, '')) IN ('DRAFT','SCHEDULED','SENT') LIMIT 1",
                (item["lead_id"], item["campaign_id"], item["sequence_step_id"]),
            ).fetchone()
            last_contacted = _parse_dt(item.get("last_contacted_at"))
            due_at_dt = (
                last_contacted + datetime.timedelta(days=int(item["delay_days"]))
                if last_contacted
                else None
            )
            due_at = due_at_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z") if due_at_dt else None
            item["due_at"] = due_at
            item["is_due"] = bool(due_at_dt and due_at_dt <= now and not duplicate)
            item["blocked_reason"] = (
                "existing_draft_or_sent"
                if duplicate
                else "missing_last_contacted"
                if not last_contacted
                else None
            )
            if duplicate:
                duplicate_data = dict_from_row(duplicate) or {}
                item["existing_message_id"] = duplicate_data.get("id")
                item["existing_message_status"] = duplicate_data.get("status")
            upcoming.append(item)

    return {
        "status": "success",
        "count": len(upcoming),
        "due_count": sum(1 for item in upcoming if item.get("is_due")),
        "followups": upcoming,
    }
