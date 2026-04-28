from typing import Dict, Any, List
import datetime
from utils.db_connection import get_conn, dict_from_row, sql_order_by_datetime, sql_bool_true, sql_bool_false
from services import lead_service


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def save_email(lead_id: int, campaign_id: int, subject: str, body: str) -> Dict[str, Any]:
    """Insert an outbound email record and update lead touch counts transactionally.

    Idempotency: prevent duplicate outbound emails with identical lead_id, campaign_id, subject, body.
    """
    if not lead_id or not campaign_id or subject is None or body is None:
        return {"success": False, "data": None, "error": "lead_id, campaign_id, subject, body are required"}

    conn = get_conn()
    try:
        with conn:
            # idempotency check
            cur = conn.execute(
                "SELECT id FROM email_messages WHERE lead_id = ? AND campaign_id = ? AND direction = 'outbound' AND subject = ? AND body = ? LIMIT 1",
                (lead_id, campaign_id, subject, body),
            )
            existing = cur.fetchone()
            if existing:
                return {"success": True, "data": {"email_id": existing['id'], "idempotent": True}, "error": None}

            proc = sql_bool_true()
            cur = conn.execute(
                f"INSERT INTO email_messages (lead_id, campaign_id, direction, subject, body, status, processed, created_at) VALUES (?, ?, 'outbound', ?, ?, ?, {proc}, ?)",
                (lead_id, campaign_id, subject, body, "sent", _now_iso()),
            )
            email_id = cur.lastrowid
            # update lead touch and campaign_leads
            # reuse lead_service which handles transactions internally; but we already are in a transaction
            # so directly perform the same updates here to keep atomicity.
            conn.execute(
                "UPDATE leads SET touch_count = touch_count + 1, last_contacted_at = ? WHERE id = ?",
                (_now_iso(), lead_id),
            )
            cur = conn.execute("SELECT emails_sent FROM campaign_leads WHERE campaign_id = ? AND lead_id = ?", (campaign_id, lead_id))
            row = cur.fetchone()
            if row is None:
                conn.execute("INSERT INTO campaign_leads (campaign_id, lead_id, emails_sent) VALUES (?, ?, 1)", (campaign_id, lead_id))
            else:
                conn.execute("UPDATE campaign_leads SET emails_sent = emails_sent + 1 WHERE campaign_id = ? AND lead_id = ?", (campaign_id, lead_id))

        return {"success": True, "data": {"email_id": email_id}, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def fetch_inbound_messages() -> Dict[str, Any]:
    conn = get_conn()
    try:
        ob = sql_order_by_datetime("created_at")
        pf = sql_bool_false()
        cur = conn.execute(
            f"SELECT * FROM email_messages WHERE direction = 'inbound' AND processed = {pf} ORDER BY {ob} ASC"
        )
        rows = cur.fetchall()
        messages = [dict_from_row(r) for r in rows]
        return {"success": True, "data": messages, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def mark_processed(message_id: int, intent: str) -> Dict[str, Any]:
    if not message_id or intent is None:
        return {"success": False, "data": None, "error": "message_id and intent required"}
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                f"UPDATE email_messages SET processed = {sql_bool_true()}, intent = ? WHERE id = ?",
                (intent, message_id),
            )
            # Optionally update last_inbound_at on the lead
            cur = conn.execute("SELECT lead_id FROM email_messages WHERE id = ?", (message_id,))
            row = cur.fetchone()
            if row:
                lead_id = row['lead_id']
                conn.execute("UPDATE leads SET last_inbound_at = ? WHERE id = ?", (_now_iso(), lead_id))
        return {"success": True, "data": {"message_id": message_id, "intent": intent}, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
