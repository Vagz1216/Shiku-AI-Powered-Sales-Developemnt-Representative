import os
from typing import Dict, Any, Optional
import datetime
from utils.db_connection import get_conn, dict_from_row, sql_order_by_datetime, sql_random_order, using_aurora
from .data_provider import LeadProvider
from config.settings import settings

VALID_STATUSES = {'NEW','CONTACTED','WARM','QUALIFIED','MEETING_PROPOSED','MEETING_BOOKED','COLD','OPTED_OUT'}

def _now_iso():
    return datetime.datetime.utcnow().isoformat() + 'Z'

class DBLeadProvider(LeadProvider):
    """Implementation of LeadProvider using SQLite/Aurora DB."""
    
    def get_leads(self, campaign_id: Optional[int] = None, max_leads: Optional[int] = None, order_by: str = 'newest_first') -> Dict[str, Any]:
        conn = get_conn()
        if using_aurora():
            select_sql = """
            SELECT l.id, l.name, l.email, l.company, l.industry, l.pain_points, l.status,
                   l.touch_count, l.created_at,
                   MAX(cl.emails_sent) AS emails_sent,
                   bool_or(cl.responded) AS responded,
                   bool_or(cl.meeting_booked) AS meeting_booked
            FROM leads l
            JOIN campaign_leads cl ON cl.lead_id = l.id
            JOIN campaigns c ON c.id = cl.campaign_id
            WHERE l.email_opt_out = FALSE
              AND c.status = 'ACTIVE'
              AND cl.emails_sent < c.max_emails_per_lead
            """
            group_sql = (
                "GROUP BY l.id, l.name, l.email, l.company, l.industry, l.pain_points, l.status, "
                "l.touch_count, l.created_at"
            )
        else:
            select_sql = """
            SELECT l.id, l.name, l.email, l.company, l.industry, l.pain_points, l.status,
                   l.touch_count, cl.emails_sent, cl.responded, cl.meeting_booked
            FROM leads l
            JOIN campaign_leads cl ON cl.lead_id = l.id
            JOIN campaigns c ON c.id = cl.campaign_id
            WHERE l.email_opt_out = 0
              AND c.status = 'ACTIVE'
              AND cl.emails_sent < c.max_emails_per_lead
            """
            group_sql = "GROUP BY l.id"
        query = select_sql
        params = []
        if campaign_id is not None:
            query += " AND c.id = ?"
            params.append(campaign_id)

        query += " " + group_sql
        
        if order_by == 'newest_first':
            query += " ORDER BY l.created_at DESC"
        elif order_by == 'oldest_first':
            query += " ORDER BY l.created_at ASC"
        elif order_by == 'random':
            query += f" ORDER BY {sql_random_order()}"
        elif order_by == 'highest_score':
            # "Score" proxy: prioritize least-touched leads first, then newest.
            query += " ORDER BY l.touch_count ASC, l.created_at DESC"
            
        if max_leads is not None:
            query += " LIMIT ?"
            params.append(max_leads)
            
        cur = conn.execute(query, tuple(params))
        rows = cur.fetchall()
        leads = [dict_from_row(r) for r in rows]
        filtered = []
        for l in leads:
            if not l or not isinstance(l, dict):
                continue
            filtered.append({
                "id": l.get("id"),
                "name": l.get("name"),
                "email": l.get("email"),
                "company": l.get("company"),
                "industry": l.get("industry"),
                "pain_points": l.get("pain_points"),
                "status": l.get("status"),
                "touch_count": l.get("touch_count", 0),
                "emails_sent": l.get("emails_sent", 0),
                "responded": l.get("responded", 0),
                "meeting_booked": l.get("meeting_booked", 0),
            })
        return {"success": True, "data": filtered, "error": None}

    def update_lead_touch(self, lead_id: int, campaign_id: int) -> Dict[str, Any]:
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

    def get_thread(self, lead_id: int) -> Dict[str, Any]:
        if not lead_id:
            return {"success": False, "data": None, "error": "lead_id required"}
        conn = get_conn()
        ob = sql_order_by_datetime("created_at")
        cur = conn.execute(
            f"SELECT * FROM email_messages WHERE lead_id = ? ORDER BY {ob} ASC",
            (lead_id,),
        )
        rows = cur.fetchall()
        messages = [dict_from_row(r) for r in rows]
        return {"success": True, "data": messages, "error": None}

    def update_lead_status(self, lead_id: int, status: str) -> Dict[str, Any]:
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
                    ("lead_status_updated", f'{{"lead_id": {lead_id}, "status": "{status}"}}', None),
                )
            return {"success": True, "data": {"lead_id": lead_id, "status": status}, "error": None}
        except Exception as e:
            return {"success": False, "data": None, "error": str(e)}

    def log_event(self, event_type: str, payload: Optional[str] = None, metadata: Optional[str] = None) -> Dict[str, Any]:
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

    def get_lead(self, lead_id: Optional[int] = None) -> Optional[dict]:
        conn = get_conn()
        if lead_id:
            cur = conn.execute("SELECT id, name, email, company, industry, pain_points FROM leads WHERE id = ?", (lead_id,))
        else:
            cur = conn.execute(
                f"SELECT id, name, email, company, industry, pain_points FROM leads ORDER BY {sql_random_order()} LIMIT 1"
            )
        row = cur.fetchone()
        return dict_from_row(row)


class CRMLeadProvider(LeadProvider):
    """Skeleton implementation for fetching leads from an external CRM like HubSpot."""
    
    def get_leads(self, email_cap: int = 5, campaign_id: Optional[int] = None, max_leads: Optional[int] = None, order_by: str = 'newest_first') -> Dict[str, Any]:
        # TODO: Implement API call to CRM (e.g. requests.get('https://api.hubapi.com/...'))
        return {"success": True, "data": [], "error": "CRM provider not fully implemented yet"}

    def update_lead_touch(self, lead_id: int, campaign_id: int) -> Dict[str, Any]:
        return {"success": True, "data": {"lead_id": lead_id, "campaign_id": campaign_id}, "error": None}

    def get_thread(self, lead_id: int) -> Dict[str, Any]:
        return {"success": True, "data": [], "error": None}

    def update_lead_status(self, lead_id: int, status: str) -> Dict[str, Any]:
        return {"success": True, "data": {"lead_id": lead_id, "status": status}, "error": None}

    def log_event(self, event_type: str, payload: Optional[str] = None, metadata: Optional[str] = None) -> Dict[str, Any]:
        return {"success": True, "data": {"event_id": 0}, "error": None}

    def get_lead(self, lead_id: Optional[int] = None) -> Optional[dict]:
        return {
            "id": lead_id or 999,
            "name": "CRM Dummy Lead", 
            "email": "dummy@crm.com",
            "company": "CRM Corp",
            "industry": "Software",
            "pain_points": "Legacy CRM migration"
        }


# Factory function to provide the right implementation based on environment
def get_lead_provider() -> LeadProvider:
    # Use environment variable to determine data source, defaulting to DB
    data_source = os.environ.get("DATA_SOURCE", "DB").upper()
    
    if data_source == "CRM":
        return CRMLeadProvider()
    else:
        return DBLeadProvider()

# Backwards compatibility layer to avoid breaking existing imports right away
_provider = get_lead_provider()

def get_leads(campaign_id: Optional[int] = None, max_leads: Optional[int] = None, order_by: str = 'newest_first') -> Dict[str, Any]:
    return _provider.get_leads(campaign_id, max_leads, order_by)

def update_lead_touch(lead_id: int, campaign_id: int) -> Dict[str, Any]:
    return _provider.update_lead_touch(lead_id, campaign_id)

def get_thread(lead_id: int) -> Dict[str, Any]:
    return _provider.get_thread(lead_id)

def update_lead_status(lead_id: int, status: str) -> Dict[str, Any]:
    return _provider.update_lead_status(lead_id, status)

def log_event(event_type: str, payload: Optional[str] = None, metadata: Optional[str] = None) -> Dict[str, Any]:
    return _provider.log_event(event_type, payload, metadata)

def get_lead(lead_id: Optional[int] = None) -> Optional[dict]:
    return _provider.get_lead(lead_id)
