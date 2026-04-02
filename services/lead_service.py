from typing import List, Dict, Any, Optional
import datetime
from utils.db_connection import get_conn, dict_from_row


VALID_STATUSES = {'NEW','CONTACTED','WARM','QUALIFIED','MEETING_BOOKED','COLD','OPTED_OUT'}


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def get_leads(email_cap: int = 5) -> Dict[str, Any]:
    """Return leads eligible for outreach.

    Eligible criteria:
    - not opted out
    - campaign is ACTIVE
    - campaign_leads.emails_sent < email_cap
    """
    conn = get_conn()
    cur = conn.execute(
        """
        SELECT l.name, l.email FROM leads l
        JOIN campaign_leads cl ON cl.lead_id = l.id
        JOIN campaigns c ON c.id = cl.campaign_id
        WHERE l.email_opt_out = 0
          AND c.status = 'ACTIVE'
          AND cl.emails_sent < ?
        GROUP BY l.id
        """,
        (email_cap,)
    )
    rows = cur.fetchall()
    # Only expose name and email to callers
    leads = [dict_from_row(r) for r in rows]
    # Ensure keys are normalized to lowercase 'name' and 'email'
    filtered = []
    for l in leads:
        # dict_from_row may return None in some edge cases; guard against it
        if not l or not isinstance(l, dict):
            continue
        filtered.append({
            "name": l.get("name"),
            "email": l.get("email"),
        })
    return {"success": True, "data": filtered, "error": None}


def update_lead_touch(lead_id: int, campaign_id: int) -> Dict[str, Any]:
    """Increment touch_count, update last_contacted_at, increment campaign_leads.emails_sent.

    This is transactional and idempotent (increments only once per call).
    """
    if not lead_id or not campaign_id:
        return {"success": False, "data": None, "error": "lead_id and campaign_id are required"}

    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "UPDATE leads SET touch_count = touch_count + 1, last_contacted_at = ? WHERE id = ?",
                (_now_iso(), lead_id),
            )
            cur = conn.execute(
                "SELECT emails_sent FROM campaign_leads WHERE campaign_id = ? AND lead_id = ?",
                (campaign_id, lead_id),
            )
            row = cur.fetchone()
            if row is None:
                # create join row
                conn.execute(
                    "INSERT INTO campaign_leads (campaign_id, lead_id, emails_sent) VALUES (?, ?, 1)",
                    (campaign_id, lead_id),
                )
            else:
                conn.execute(
                    "UPDATE campaign_leads SET emails_sent = emails_sent + 1 WHERE campaign_id = ? AND lead_id = ?",
                    (campaign_id, lead_id),
                )
        return {"success": True, "data": {"lead_id": lead_id, "campaign_id": campaign_id}, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def get_thread(lead_id: int) -> Dict[str, Any]:
    if not lead_id:
        return {"success": False, "data": None, "error": "lead_id required"}
    conn = get_conn()
    cur = conn.execute(
        "SELECT * FROM email_messages WHERE lead_id = ? ORDER BY datetime(created_at) ASC",
        (lead_id,)
    )
    rows = cur.fetchall()
    messages = [dict_from_row(r) for r in rows]
    return {"success": True, "data": messages, "error": None}


def update_lead_status(lead_id: int, status: str) -> Dict[str, Any]:
    if not lead_id or not status:
        return {"success": False, "data": None, "error": "lead_id and status required"}
    status = status.upper()
    if status not in VALID_STATUSES:
        return {"success": False, "data": None, "error": f"invalid status: {status}"}
    conn = get_conn()
    try:
        with conn:
            conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
            conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                ("lead_status_updated", f"{{\"lead_id\": {lead_id}, \"status\": \"{status}\"}}", None),
            )
        return {"success": True, "data": {"lead_id": lead_id, "status": status}, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def log_event(event_type: str, payload: Optional[str] = None, metadata: Optional[str] = None) -> Dict[str, Any]:
    if not event_type:
        return {"success": False, "data": None, "error": "event type required"}
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                (event_type, payload, metadata),
            )
            event_id = cur.lastrowid
        return {"success": True, "data": {"event_id": event_id}, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def get_lead(lead_id: Optional[int] = None) -> Optional[dict]:
    """Return lead name and email by id, or a random lead if id is None."""
    conn = get_conn()
    if lead_id:
        cur = conn.execute("SELECT name, email FROM leads WHERE id = ?", (lead_id,))
    else:
        cur = conn.execute("SELECT name, email FROM leads ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    return dict_from_row(row)
