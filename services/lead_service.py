import json
import os
import re
from typing import Dict, Any, Optional, Iterable
import datetime
from utils.db_connection import (
    get_conn,
    dict_from_row,
    sql_order_by_datetime,
    sql_random_order,
    using_postgres,
)
from .data_provider import LeadProvider
from config.settings import settings

VALID_STATUSES = {'NEW','CONTACTED','WARM','QUALIFIED','MEETING_PROPOSED','MEETING_BOOKED','COLD','OPTED_OUT'}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _now_iso():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def _normalize_status(status: Optional[str]) -> str:
    value = (status or "NEW").upper()
    if value not in VALID_STATUSES:
        raise ValueError(f"invalid status: {value}")
    return value


def _normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError(f"invalid email: {email}")
    return value


def _bool_to_db(value: bool | int | None) -> int:
    return 1 if bool(value) else 0


def _assign_campaigns(conn, lead_id: int, campaign_ids: Iterable[int], *, organization_id: int, replace: bool = False) -> None:
    ids = sorted({int(cid) for cid in campaign_ids if cid is not None})
    if replace:
        conn.execute("DELETE FROM campaign_leads WHERE lead_id = ?", (lead_id,))
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id FROM campaigns WHERE organization_id = ? AND id IN ({placeholders})",
        (organization_id, *ids),
    ).fetchall()
    found = {dict_from_row(row)["id"] for row in rows}
    missing = [cid for cid in ids if cid not in found]
    if missing:
        raise ValueError(f"invalid campaign IDs: {missing}")
    for campaign_id in ids:
        existing = conn.execute(
            "SELECT campaign_id FROM campaign_leads WHERE campaign_id = ? AND lead_id = ?",
            (campaign_id, lead_id),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO campaign_leads "
            "(campaign_id, lead_id, emails_sent, responded, meeting_booked) "
            "VALUES (?, ?, 0, 0, 0)",
            (campaign_id, lead_id),
        )


def _lead_select_sql() -> str:
    return (
        "SELECT l.id, l.organization_id, l.name, l.email, l.company, l.industry, l.pain_points, "
        "l.status, l.email_opt_out, l.touch_count, l.last_contacted_at, "
        "l.last_inbound_at, l.created_at FROM leads l WHERE l.id = ?"
    )


def _fetch_lead_by_id(conn, lead_id: int, organization_id: int | None = None) -> Optional[dict]:
    sql = _lead_select_sql()
    params: tuple[Any, ...] = (lead_id,)
    if organization_id is not None:
        sql += " AND l.organization_id = ?"
        params = (lead_id, organization_id)
    row = conn.execute(sql, params).fetchone()
    return dict_from_row(row)


def _fetch_lead_id_by_email(conn, email: str, organization_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM leads WHERE email = ? AND organization_id = ?",
        (email, organization_id),
    ).fetchone()
    data = dict_from_row(row)
    if not data:
        raise ValueError(f"lead was not saved: {email}")
    return int(data["id"])


def create_lead(data: Dict[str, Any], organization_id: int = 1) -> Dict[str, Any]:
    """Create one lead and optionally assign it to campaigns."""
    try:
        email = _normalize_email(data.get("email", ""))
        status = _normalize_status(data.get("status"))
        campaign_ids = data.get("campaign_ids") or []
        with get_conn() as conn:
            with conn:
                cur = conn.execute(
                    "INSERT INTO leads (organization_id, name, email, company, industry, pain_points, status, email_opt_out) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        organization_id,
                        data.get("name"),
                        email,
                        data.get("company"),
                        data.get("industry"),
                        data.get("pain_points"),
                        status,
                        _bool_to_db(data.get("email_opt_out")),
                    ),
                )
                lead_id = cur.lastrowid or _fetch_lead_id_by_email(conn, email, organization_id)
                _assign_campaigns(conn, lead_id, campaign_ids, organization_id=organization_id)
                conn.execute(
                    "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                    (organization_id, "lead_created", json.dumps({"lead_id": lead_id, "email": email}), None),
                )
            return {"success": True, "data": _fetch_lead_by_id(conn, lead_id, organization_id), "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def update_lead(lead_id: int, data: Dict[str, Any], organization_id: int = 1) -> Dict[str, Any]:
    """Update one lead. If campaign_ids is present, replace campaign assignments."""
    if not lead_id:
        return {"success": False, "data": None, "error": "lead_id required"}

    allowed_fields = {
        "name",
        "email",
        "company",
        "industry",
        "pain_points",
        "status",
        "email_opt_out",
    }
    updates = []
    params = []
    try:
        for field in allowed_fields:
            if field not in data:
                continue
            value = data[field]
            if field == "email":
                value = _normalize_email(value)
            elif field == "status":
                value = _normalize_status(value)
            elif field == "email_opt_out":
                value = _bool_to_db(value)
            updates.append(f"{field} = ?")
            params.append(value)

        with get_conn() as conn:
            existing = _fetch_lead_by_id(conn, lead_id, organization_id)
            if not existing:
                return {"success": False, "data": None, "error": "lead not found"}
            with conn:
                if updates:
                    params.extend([lead_id, organization_id])
                    conn.execute(
                        f"UPDATE leads SET {', '.join(updates)} WHERE id = ? AND organization_id = ?",
                        tuple(params),
                    )
                if "campaign_ids" in data:
                    _assign_campaigns(conn, lead_id, data.get("campaign_ids") or [], organization_id=organization_id, replace=True)
                conn.execute(
                    "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                    (organization_id, "lead_updated", json.dumps({"lead_id": lead_id}), None),
                )
            return {"success": True, "data": _fetch_lead_by_id(conn, lead_id, organization_id), "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def delete_lead(lead_id: int, organization_id: int = 1) -> Dict[str, Any]:
    if not lead_id:
        return {"success": False, "data": None, "error": "lead_id required"}
    try:
        with get_conn() as conn:
            existing = _fetch_lead_by_id(conn, lead_id, organization_id)
            if not existing:
                return {"success": False, "data": None, "error": "lead not found"}
            with conn:
                conn.execute("DELETE FROM leads WHERE id = ? AND organization_id = ?", (lead_id, organization_id))
                conn.execute(
                    "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                    (organization_id, "lead_deleted", json.dumps({"lead_id": lead_id, "email": existing["email"]}), None),
                )
        return {"success": True, "data": {"lead_id": lead_id}, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


def bulk_import_leads(
    leads: list[Dict[str, Any]],
    *,
    campaign_ids: Optional[list[int]] = None,
    upsert: bool = True,
    source: str | None = None,
    organization_id: int = 1,
) -> Dict[str, Any]:
    """Import multiple leads, optionally updating existing rows by email."""
    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    campaign_ids = campaign_ids or []

    try:
        with get_conn() as conn:
            with conn:
                for idx, raw in enumerate(leads):
                    try:
                        email = _normalize_email(str(raw.get("email", "")))
                        status = _normalize_status(raw.get("status"))
                        row_campaign_ids = raw.get("campaign_ids")
                        effective_campaign_ids = row_campaign_ids if row_campaign_ids is not None else campaign_ids
                        existing = conn.execute(
                            "SELECT id FROM leads WHERE email = ? AND organization_id = ?",
                            (email, organization_id),
                        ).fetchone()
                        if existing:
                            if not upsert:
                                skipped += 1
                                continue
                            lead_id = dict_from_row(existing)["id"]
                            conn.execute(
                                "UPDATE leads SET name = COALESCE(?, name), company = COALESCE(?, company), "
                                "industry = COALESCE(?, industry), pain_points = COALESCE(?, pain_points), "
                                "status = ?, email_opt_out = ? WHERE id = ? AND organization_id = ?",
                                (
                                    raw.get("name"),
                                    raw.get("company"),
                                    raw.get("industry"),
                                    raw.get("pain_points"),
                                    status,
                                    _bool_to_db(raw.get("email_opt_out")),
                                    lead_id,
                                    organization_id,
                                ),
                            )
                            updated += 1
                        else:
                            cur = conn.execute(
                                "INSERT INTO leads (organization_id, name, email, company, industry, pain_points, status, email_opt_out) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    organization_id,
                                    raw.get("name"),
                                    email,
                                    raw.get("company"),
                                    raw.get("industry"),
                                    raw.get("pain_points"),
                                    status,
                                    _bool_to_db(raw.get("email_opt_out")),
                                ),
                            )
                            lead_id = cur.lastrowid or _fetch_lead_id_by_email(conn, email, organization_id)
                            created += 1
                        _assign_campaigns(conn, lead_id, effective_campaign_ids, organization_id=organization_id)
                    except Exception as e:
                        skipped += 1
                        errors.append({"row": idx + 1, "error": str(e), "email": raw.get("email")})
                conn.execute(
                    "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                    (
                        organization_id,
                        "leads_imported",
                        json.dumps(
                            {
                                "created": created,
                                "updated": updated,
                                "skipped": skipped,
                                "source": source,
                            }
                        ),
                        None,
                    ),
                )
        return {
            "success": True,
            "data": {
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "errors": errors[:50],
            },
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}

class DBLeadProvider(LeadProvider):
    """Implementation of LeadProvider using SQLite/Aurora DB."""
    
    def get_leads(self, campaign_id: Optional[int] = None, max_leads: Optional[int] = None, order_by: str = 'newest_first', organization_id: Optional[int] = None) -> Dict[str, Any]:
        conn = get_conn()
        if using_postgres():
            select_sql = """
            SELECT l.id, l.name, l.email, l.company, l.industry, l.pain_points, l.status,
                   l.touch_count, l.created_at,
                   MAX(cl.emails_sent) AS emails_sent,
                   MAX(cl.responded) AS responded,
                   MAX(cl.meeting_booked) AS meeting_booked
            FROM leads l
            JOIN campaign_leads cl ON cl.lead_id = l.id
            JOIN campaigns c ON c.id = cl.campaign_id
            WHERE l.email_opt_out = 0
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
        if organization_id is not None:
            query += " AND l.organization_id = ? AND c.organization_id = ?"
            params.extend([organization_id, organization_id])

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
                row = conn.execute("SELECT organization_id FROM leads WHERE id = ?", (lead_id,)).fetchone()
                organization_id = dict_from_row(row).get("organization_id") if row else None
                conn.execute(
                    "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
                    (organization_id, "lead_status_updated", f'{{"lead_id": {lead_id}, "status": "{status}"}}', None),
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
    
    def get_leads(self, email_cap: int = 5, campaign_id: Optional[int] = None, max_leads: Optional[int] = None, order_by: str = 'newest_first', organization_id: Optional[int] = None) -> Dict[str, Any]:
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

def get_leads(campaign_id: Optional[int] = None, max_leads: Optional[int] = None, order_by: str = 'newest_first', organization_id: Optional[int] = None) -> Dict[str, Any]:
    return _provider.get_leads(campaign_id, max_leads, order_by, organization_id)

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
