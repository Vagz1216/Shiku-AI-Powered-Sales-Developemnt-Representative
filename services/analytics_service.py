"""Operational analytics for campaign, lead, and email performance."""

from __future__ import annotations

from typing import Any

from utils.db_connection import get_conn, dict_from_row, sql_bool_true


def _scalar(conn, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if not row:
        return 0
    data = dict_from_row(row) or {}
    return int(next(iter(data.values())) or 0)


def summary(organization_id: int | None = None) -> dict[str, Any]:
    with get_conn() as conn:
        true_literal = sql_bool_true()
        org_filter = "organization_id = ?"
        org_params: tuple[Any, ...] = (organization_id,) if organization_id is not None else ()
        org_where = f" WHERE {org_filter}" if organization_id is not None else ""
        org_and = f" AND {org_filter}" if organization_id is not None else ""
        totals = {
            "leads": _scalar(conn, f"SELECT COUNT(*) AS count FROM leads{org_where}", org_params),
            "active_campaigns": _scalar(
                conn,
                f"SELECT COUNT(*) AS count FROM campaigns WHERE status = 'ACTIVE'{org_and}",
                org_params,
            ),
            "pending_drafts": _scalar(
                conn,
                "SELECT COUNT(*) AS count FROM email_messages "
                f"WHERE direction = 'outbound' AND UPPER(status) = 'DRAFT' AND approved = 0{org_and}",
                org_params,
            ),
            "scheduled_emails": _scalar(
                conn,
                "SELECT COUNT(*) AS count FROM email_messages "
                f"WHERE direction = 'outbound' AND UPPER(status) = 'SCHEDULED' AND approved = 1{org_and}",
                org_params,
            ),
            "sent_emails": _scalar(
                conn,
                "SELECT COUNT(*) AS count FROM email_messages "
                f"WHERE direction = 'outbound' AND UPPER(status) = 'SENT'{org_and}",
                org_params,
            ),
            "inbound_replies": _scalar(
                conn,
                f"SELECT COUNT(*) AS count FROM email_messages WHERE direction = 'inbound'{org_and}",
                org_params,
            ),
            "meetings_booked": _scalar(
                conn,
                f"SELECT COUNT(*) AS count FROM leads WHERE status = 'MEETING_BOOKED'{org_and}",
                org_params,
            ),
            "opted_out": _scalar(
                conn,
                f"SELECT COUNT(*) AS count FROM leads WHERE (email_opt_out = {true_literal} OR status = 'OPTED_OUT'){org_and}",
                org_params,
            ),
        }
        sent = max(totals["sent_emails"], 1)
        rates = {
            "reply_rate": totals["inbound_replies"] / sent,
            "meeting_rate": totals["meetings_booked"] / sent,
            "opt_out_rate": totals["opted_out"] / max(totals["leads"], 1),
        }
        campaigns = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT c.id, c.name, c.status, "
                "COALESCE(cl_stats.assigned_leads, 0) AS assigned_leads, "
                "COALESCE(cl_stats.emails_sent, 0) AS emails_sent, "
                "COALESCE(cl_stats.responded, 0) AS responded, "
                "COALESCE(cl_stats.meetings_booked, 0) AS meetings_booked, "
                "COALESCE(msg_stats.pending_drafts, 0) AS pending_drafts, "
                "COALESCE(msg_stats.scheduled_emails, 0) AS scheduled_emails "
                "FROM campaigns c "
                "LEFT JOIN ("
                "  SELECT campaign_id, COUNT(DISTINCT lead_id) AS assigned_leads, "
                "  SUM(emails_sent) AS emails_sent, "
                f"  SUM(CASE WHEN responded = {true_literal} THEN 1 ELSE 0 END) AS responded, "
                f"  SUM(CASE WHEN meeting_booked = {true_literal} THEN 1 ELSE 0 END) AS meetings_booked "
                "  FROM campaign_leads GROUP BY campaign_id"
                ") cl_stats ON cl_stats.campaign_id = c.id "
                "LEFT JOIN ("
                "  SELECT campaign_id, "
                "  SUM(CASE WHEN UPPER(COALESCE(status, '')) = 'DRAFT' AND approved = 0 THEN 1 ELSE 0 END) AS pending_drafts, "
                "  SUM(CASE WHEN UPPER(COALESCE(status, '')) = 'SCHEDULED' AND approved = 1 THEN 1 ELSE 0 END) AS scheduled_emails "
                "  FROM email_messages WHERE direction = 'outbound' GROUP BY campaign_id"
                ") msg_stats ON msg_stats.campaign_id = c.id "
                + ("WHERE c.organization_id = ? " if organization_id is not None else "")
                + "ORDER BY c.id DESC",
                org_params,
            ).fetchall()
        ]
    return {"totals": totals, "rates": rates, "campaigns": campaigns}
