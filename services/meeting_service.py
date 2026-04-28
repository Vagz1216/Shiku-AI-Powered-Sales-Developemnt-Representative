from typing import Dict, Any, Optional
import datetime
import json
from utils.db_connection import get_conn, sql_bool_true
from services import lead_service


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def schedule_meeting(lead_id: int, staff_id: int, start_time: str, meet_link: Optional[str] = None) -> Dict[str, Any]:
    """Insert meeting record transactionally, prevent duplicates (same lead + start_time).

    Also updates lead.status to MEETING_BOOKED and marks campaign_leads.meeting_booked if applicable.
    """
    if not lead_id or not staff_id or not start_time:
        return {"success": False, "data": None, "error": "lead_id, staff_id, start_time are required"}

    conn = get_conn()
    try:
        with conn:
            # idempotency check: same lead + start_time
            cur = conn.execute("SELECT id FROM meetings WHERE lead_id = ? AND start_time = ? LIMIT 1", (lead_id, start_time))
            existing = cur.fetchone()
            if existing:
                return {"success": True, "data": {"meeting_id": existing['id'], "idempotent": True}, "error": None}

            cur = conn.execute(
                "INSERT INTO meetings (lead_id, staff_id, meet_link, start_time, status, created_at) VALUES (?, ?, ?, ?, 'SCHEDULED', ?)",
                (lead_id, staff_id, meet_link, start_time, _now_iso()),
            )
            meeting_id = cur.lastrowid
            # Update lead status
            conn.execute("UPDATE leads SET status = 'MEETING_BOOKED' WHERE id = ?", (lead_id,))
            # Mark meeting_booked on any campaign_leads rows
            conn.execute(
                f"UPDATE campaign_leads SET meeting_booked = {sql_bool_true()} WHERE lead_id = ?",
                (lead_id,),
            )
            # log event (store JSON payload)
            conn.execute(
                "INSERT INTO events (type, payload) VALUES (?, ?)",
                ("meeting_scheduled", json.dumps({"meeting_id": meeting_id, "lead_id": lead_id})),
            )

        return {"success": True, "data": {"meeting_id": meeting_id}, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
