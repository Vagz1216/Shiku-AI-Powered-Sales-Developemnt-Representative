"""
Main FastAPI application with consolidated API endpoints.

Combines outreach and email monitoring functionality.
"""

import asyncio
import hashlib
import hmac
import logging
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
import time
import json

from config.logging import setup_logging
from config import settings
from schema import WebhookEvent
from email_monitor.monitor import email_monitor
from email_monitor.webhook_utils import should_process_webhook, DEFAULT_LOOP_PREVENTION
from email_monitor.data_utils import extract_sender_email, extract_sender_name, extract_subject
from schema.outreach import CampaignCreate, CampaignUpdate
from tools.campaign_tools import get_active_campaigns, get_all_campaigns, create_campaign, update_campaign, delete_campaign
from outreach.marketing_agent import OutreachOrchestrator
from utils.auth import get_current_user

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Configure separate tracing key if provided
if settings.openai_tracing_key:
    from agents import set_tracing_export_api_key
    set_tracing_export_api_key(settings.openai_tracing_key)
    logger.info("Tracing configured with separate OPENAI_TRACING_KEY")

# Initialize Orchestrator
outreach_orchestrator = OutreachOrchestrator()

# Webhook Log Broadcaster
class WebhookLogBroadcaster:
    def __init__(self):
        self.connections: list[asyncio.Queue] = []
    
    async def broadcast(self, status: str, message: str, event_id: str = ""):
        short_id = event_id[:8] if event_id else ""
        stale: list[asyncio.Queue] = []
        for queue in self.connections:
            try:
                queue.put_nowait({"status": status, "message": message, "event_id": short_id})
            except asyncio.QueueFull:
                stale.append(queue)
        for q in stale:
            self.connections.remove(q)

    def scoped(self, event_id: str):
        """Return a callback pre-bound to a specific event_id."""
        async def _cb(status: str, message: str):
            await self.broadcast(status, message, event_id)
        return _cb

webhook_broadcaster = WebhookLogBroadcaster()

# HTTP Access Logging Middleware
class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Add ngrok skip warning header for local development webhooks
        if request.headers.get("host", "").endswith("ngrok-free.dev") or request.headers.get("host", "").endswith("ngrok.io"):
            # We can't mutate request headers directly easily in starlette, 
            # but Ngrok intercepts it *before* it hits us anyway.
            # To fix the Ngrok warning for incoming webhooks, we need to tell the user to configure it in AgentMail,
            # OR we can try to send a custom response header, but ngrok blocks the *incoming* request.
            pass

        # Log the request
        logger.info(f"Request: {request.method} {request.url}")
        
        response = await call_next(request)
        
        # Calculate processing time
        process_time = time.time() - start_time
        
        # Log the response
        logger.info(
            f"Response: {request.method} {request.url.path} - "
            f"{response.status_code} - {process_time:.3f}s"
        )
        
        return response

app = FastAPI(
    title="Andela AI Bootcamp Euclid Squad 3 API", 
    description="Outreach and Email Monitoring System",
    version="1.0.0"
)

# Add access logging middleware
app.add_middleware(AccessLogMiddleware)

# Add CORS middleware for Next.js frontend (configurable via CORS_ORIGINS env)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health endpoints
@app.get("/health")
def health() -> Dict[str, str]:
    """Global health check."""
    return {"status": "ok", "service": "Andela AI Bootcamp Euclid Squad 3 API"}

@app.get("/health/db")
def health_db() -> Dict[str, str]:
    """Database health check."""
    try:
        from utils.db_connection import get_conn
        conn = get_conn()
        conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")

@app.get("/health/ai")
async def health_ai() -> Dict[str, Any]:
    """AI Provider health check."""
    try:
        from utils.model_fallback import get_available_providers
        providers = get_available_providers()
        if not providers:
            raise Exception("No AI providers configured")
        return {
            "status": "ok", 
            "providers_configured": len(providers),
            "primary_provider": providers[0].name
        }
    except Exception as e:
        logger.error(f"AI health check failed: {e}")
        raise HTTPException(status_code=503, detail="AI providers unavailable")


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint with API overview."""
    return {
        "service": "Andela AI Bootcamp Euclid Squad 3 API",
        "version": "1.0.0",
        "endpoints": {
            "marketing_campaign": "/outreach/campaign",
            "outreach_ui": "/outreach (Gradio Interface)", 
            "webhook": "/webhook",
            "health": "/health"
        },
        "note": "Visit /outreach for the interactive campaign management UI"
    }


# Outreach endpoints
@app.get("/api/campaigns")
async def list_campaigns(user: dict = Depends(get_current_user), active_only: bool = True):
    """List campaigns. If active_only is true, returns only ACTIVE campaigns."""
    try:
        if active_only:
            campaigns = get_active_campaigns()
        else:
            campaigns = get_all_campaigns()
        return {"campaigns": [c.dict() for c in campaigns]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list campaigns: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/campaigns")
async def create_new_campaign(campaign: CampaignCreate, user: dict = Depends(get_current_user)):
    """Create a new campaign."""
    try:
        new_campaign = create_campaign(campaign)
        if not new_campaign:
            raise HTTPException(status_code=500, detail="Failed to create campaign")
        return {"status": "success", "campaign": new_campaign.dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create campaign: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/campaigns/{campaign_id}")
async def update_existing_campaign(campaign_id: int, updates: CampaignUpdate, user: dict = Depends(get_current_user)):
    """Update an existing campaign."""
    try:
        updated_campaign = update_campaign(campaign_id, updates)
        if not updated_campaign:
            raise HTTPException(status_code=404, detail="Campaign not found or update failed")
        return {"status": "success", "campaign": updated_campaign.dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/campaigns/{campaign_id}")
async def delete_existing_campaign(campaign_id: int, user: dict = Depends(get_current_user)):
    """Delete an existing campaign."""
    try:
        success = delete_campaign(campaign_id)
        if not success:
            raise HTTPException(status_code=404, detail="Campaign not found or deletion failed")
        return {"status": "success", "message": f"Campaign {campaign_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class StaffUpsertRequest(BaseModel):
    name: str
    email: str
    timezone: Optional[str] = None
    availability: Optional[str] = None
    dummy_slots: Optional[str] = None


class CampaignStaffAssignmentRequest(BaseModel):
    staff_ids: List[int]


@app.get("/api/staff")
async def list_staff(user: dict = Depends(get_current_user)):
    """List all staff available for campaign assignment and meeting notifications."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT id, name, email, timezone, availability, dummy_slots, created_at "
                "FROM staff ORDER BY id ASC"
            )
            staff = [dict(row) for row in cur.fetchall()]
        return {"staff": staff}
    except Exception as e:
        logger.error(f"Failed to list staff: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/staff")
async def create_staff_member(request: StaffUpsertRequest, user: dict = Depends(get_current_user)):
    """Create a staff member."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO staff (name, email, timezone, availability, dummy_slots) VALUES (?, ?, ?, ?, ?)",
                (
                    request.name.strip(),
                    request.email.strip().lower(),
                    request.timezone,
                    request.availability,
                    request.dummy_slots,
                ),
            )
            staff_id = cur.lastrowid
        return {"status": "success", "staff_id": staff_id}
    except Exception as e:
        logger.error(f"Failed to create staff member: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/staff/{staff_id}")
async def update_staff_member(staff_id: int, request: StaffUpsertRequest, user: dict = Depends(get_current_user)):
    """Update a staff member."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM staff WHERE id = ?", (staff_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Staff member not found")
            conn.execute(
                "UPDATE staff SET name = ?, email = ?, timezone = ?, availability = ?, dummy_slots = ? WHERE id = ?",
                (
                    request.name.strip(),
                    request.email.strip().lower(),
                    request.timezone,
                    request.availability,
                    request.dummy_slots,
                    staff_id,
                ),
            )
        return {"status": "success", "staff_id": staff_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update staff member {staff_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/staff/{staff_id}")
async def delete_staff_member(staff_id: int, user: dict = Depends(get_current_user)):
    """Delete a staff member."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM staff WHERE id = ?", (staff_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Staff member not found")
            conn.execute("DELETE FROM staff WHERE id = ?", (staff_id,))
        return {"status": "success", "staff_id": staff_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete staff member {staff_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/campaigns/{campaign_id}/staff")
async def get_campaign_staff(campaign_id: int, user: dict = Depends(get_current_user)):
    """Get all staff with assignment state for a campaign."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            c = conn.execute("SELECT id, name FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Campaign not found")

            cur = conn.execute(
                "SELECT s.id, s.name, s.email, s.timezone, "
                "CASE WHEN cs.campaign_id IS NULL THEN 0 ELSE 1 END AS assigned "
                "FROM staff s "
                "LEFT JOIN campaign_staff cs ON cs.staff_id = s.id AND cs.campaign_id = ? "
                "ORDER BY s.id ASC",
                (campaign_id,),
            )
            staff = [dict(row) for row in cur.fetchall()]
        return {"campaign_id": campaign_id, "staff": staff}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch campaign staff for {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/campaigns/{campaign_id}/staff")
async def replace_campaign_staff(
    campaign_id: int,
    request: CampaignStaffAssignmentRequest,
    user: dict = Depends(get_current_user),
):
    """Replace campaign staff assignments with the provided staff IDs."""
    try:
        from utils.db_connection import get_conn
        staff_ids = sorted(set(request.staff_ids))
        with get_conn() as conn:
            c = conn.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Campaign not found")

            if staff_ids:
                placeholders = ",".join("?" for _ in staff_ids)
                rows = conn.execute(
                    f"SELECT id FROM staff WHERE id IN ({placeholders})",
                    tuple(staff_ids),
                ).fetchall()
                found = {r["id"] for r in rows}
                missing = [sid for sid in staff_ids if sid not in found]
                if missing:
                    raise HTTPException(status_code=400, detail=f"Invalid staff IDs: {missing}")

            with conn:
                conn.execute("DELETE FROM campaign_staff WHERE campaign_id = ?", (campaign_id,))
                for staff_id in staff_ids:
                    conn.execute(
                        "INSERT INTO campaign_staff (campaign_id, staff_id) VALUES (?, ?)",
                        (campaign_id, staff_id),
                    )
        return {"status": "success", "campaign_id": campaign_id, "assigned_count": len(staff_ids)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update campaign staff for {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/leads")
async def list_leads(user: dict = Depends(get_current_user)):
    """List leads with outreach status, campaign context, and last outbound activity."""
    try:
        from utils.db_connection import get_conn, sql_group_concat_distinct, sql_order_by_datetime

        odt = sql_order_by_datetime("em.created_at")
        gcat = sql_group_concat_distinct("c.name")
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT "
                "l.id, l.name, l.email, l.company, l.industry, l.status, l.touch_count, l.email_opt_out, "
                "l.last_contacted_at, l.last_inbound_at, l.created_at, "
                "COALESCE(SUM(cl.emails_sent), 0) AS emails_sent, "
                "COALESCE(MAX(CAST(cl.responded AS INTEGER)), 0) AS responded, "
                "COALESCE(MAX(CAST(cl.meeting_booked AS INTEGER)), 0) AS meeting_booked, "
                f"{gcat} AS campaigns, "
                "(SELECT em.status FROM email_messages em "
                " WHERE em.lead_id = l.id AND em.direction = 'outbound' "
                f" ORDER BY {odt} DESC LIMIT 1) AS last_outbound_status, "
                "(SELECT em.subject FROM email_messages em "
                " WHERE em.lead_id = l.id AND em.direction = 'outbound' "
                f" ORDER BY {odt} DESC LIMIT 1) AS last_outbound_subject, "
                "(SELECT em.created_at FROM email_messages em "
                " WHERE em.lead_id = l.id AND em.direction = 'outbound' "
                f" ORDER BY {odt} DESC LIMIT 1) AS last_outbound_at "
                "FROM leads l "
                "LEFT JOIN campaign_leads cl ON cl.lead_id = l.id "
                "LEFT JOIN campaigns c ON c.id = cl.campaign_id "
                "GROUP BY l.id "
                "ORDER BY l.id ASC"
            )
            leads = [dict(row) for row in cur.fetchall()]
        return {"leads": leads}
    except Exception as e:
        logger.error(f"Failed to list leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/campaigns/{campaign_id}/leads")
async def get_campaign_leads(campaign_id: int, user: dict = Depends(get_current_user)):
    """Get all leads with assignment info for a campaign."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            # Ensure campaign exists
            c = conn.execute("SELECT id, name FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Campaign not found")

            cur = conn.execute(
                "SELECT l.id, l.name, l.email, l.company, l.status, l.touch_count, "
                "CASE WHEN cl.campaign_id IS NULL THEN 0 ELSE 1 END AS assigned, "
                "COALESCE(cl.emails_sent, 0) AS emails_sent, "
                "COALESCE(CAST(cl.responded AS INTEGER), 0) AS responded, "
                "COALESCE(CAST(cl.meeting_booked AS INTEGER), 0) AS meeting_booked "
                "FROM leads l "
                "LEFT JOIN campaign_leads cl ON cl.lead_id = l.id AND cl.campaign_id = ? "
                "ORDER BY l.id ASC",
                (campaign_id,),
            )
            leads = [dict(row) for row in cur.fetchall()]
        return {"campaign_id": campaign_id, "leads": leads}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch campaign leads for {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class CampaignLeadAssignmentRequest(BaseModel):
    lead_ids: List[int]


@app.put("/api/campaigns/{campaign_id}/leads")
async def replace_campaign_leads(
    campaign_id: int,
    request: CampaignLeadAssignmentRequest,
    user: dict = Depends(get_current_user),
):
    """Replace campaign lead assignments with the provided lead IDs."""
    try:
        from utils.db_connection import get_conn
        lead_ids = sorted(set(request.lead_ids))
        with get_conn() as conn:
            c = conn.execute("SELECT id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Campaign not found")

            # Validate provided lead IDs exist
            if lead_ids:
                placeholders = ",".join("?" for _ in lead_ids)
                rows = conn.execute(
                    f"SELECT id FROM leads WHERE id IN ({placeholders})",
                    tuple(lead_ids),
                ).fetchall()
                found = {r["id"] for r in rows}
                missing = [lid for lid in lead_ids if lid not in found]
                if missing:
                    raise HTTPException(status_code=400, detail=f"Invalid lead IDs: {missing}")

            with conn:
                conn.execute("DELETE FROM campaign_leads WHERE campaign_id = ?", (campaign_id,))
                for lead_id in lead_ids:
                    conn.execute(
                        "INSERT INTO campaign_leads (campaign_id, lead_id, emails_sent, responded, meeting_booked) "
                        "VALUES (?, ?, 0, 0, 0)",
                        (campaign_id, lead_id),
                    )
        return {"status": "success", "campaign_id": campaign_id, "assigned_count": len(lead_ids)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update campaign leads for {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/drafts")
async def list_drafts(
    user: dict = Depends(get_current_user),
    q: Optional[str] = None,
    campaign_name: Optional[str] = None,
    lead_email: Optional[str] = None,
):
    """List all pending email drafts awaiting approval."""
    try:
        from utils.db_connection import get_conn, sql_order_by_datetime

        order_created = sql_order_by_datetime("e.created_at")
        where_clauses = ["e.status = 'DRAFT'", "e.approved = 0", "e.direction = 'outbound'"]
        params: list[Any] = []

        if q:
            where_clauses.append("(e.subject LIKE ? OR e.body LIKE ? OR l.name LIKE ? OR l.email LIKE ? OR c.name LIKE ?)")
            q_like = f"%{q}%"
            params.extend([q_like, q_like, q_like, q_like, q_like])
        if campaign_name:
            where_clauses.append("c.name = ?")
            params.append(campaign_name)
        if lead_email:
            where_clauses.append("l.email = ?")
            params.append(lead_email)

        where_sql = " AND ".join(where_clauses)
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT e.id, e.subject, e.body, e.created_at, l.name as lead_name, l.email as lead_email, c.name as campaign_name "
                "FROM email_messages e "
                "JOIN leads l ON e.lead_id = l.id "
                "JOIN campaigns c ON e.campaign_id = c.id "
                f"WHERE {where_sql} "
                f"ORDER BY {order_created} DESC",
                tuple(params),
            )
            drafts = [dict(row) for row in cur.fetchall()]
        return {"drafts": drafts}
    except Exception as e:
        logger.error(f"Failed to list drafts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class DraftApprovalRequest(BaseModel):
    approved: bool


async def _process_single_draft_approval(
    conn,
    draft_id: int,
    approved: bool,
) -> Dict[str, Any]:
    """Approve/reject one draft and return structured status."""
    from tools.send_email import send_plain_email

    cur = conn.execute(
        "SELECT e.id, e.subject, e.body, e.campaign_id, l.name as lead_name, l.email as lead_email "
        "FROM email_messages e "
        "JOIN leads l ON e.lead_id = l.id "
        "WHERE e.id = ? AND e.status = 'DRAFT' AND e.approved = 0",
        (draft_id,),
    )
    draft = cur.fetchone()
    if not draft:
        return {"draft_id": draft_id, "status": "not_found"}

    draft = dict(draft)
    if approved:
        from utils.quick_replies import (
            quick_replies_for_outreach,
            quick_replies_html_for_outreach,
            plain_text_to_basic_html,
        )
        body_with_qr = draft["body"] + quick_replies_for_outreach(
            draft["subject"],
            lead_email=draft["lead_email"],
            campaign_id=draft["campaign_id"],
        )
        html_body = plain_text_to_basic_html(draft["body"]) + quick_replies_html_for_outreach(
            draft["subject"],
            lead_email=draft["lead_email"],
            campaign_id=draft["campaign_id"],
        )
        send_res = await send_plain_email(
            email=draft["lead_email"],
            name=draft["lead_name"],
            subject=draft["subject"],
            body=body_with_qr,
            html_body=html_body,
        )
        if send_res.ok:
            conn.execute(
                "UPDATE email_messages SET approved = 1, status = 'SENT' WHERE id = ?",
                (draft_id,)
            )
            return {"draft_id": draft_id, "status": "approved_sent"}
        return {"draft_id": draft_id, "status": "send_failed", "error": send_res.error}

    conn.execute(
        "UPDATE email_messages SET approved = -1, status = 'REJECTED' WHERE id = ?",
        (draft_id,)
    )
    return {"draft_id": draft_id, "status": "rejected"}


@app.post("/api/drafts/{draft_id}/approve")
async def approve_draft(draft_id: int, request: DraftApprovalRequest, user: dict = Depends(get_current_user)):
    """Approve or reject a pending email draft."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            result = await _process_single_draft_approval(conn, draft_id, request.approved)
            if result["status"] == "not_found":
                raise HTTPException(status_code=404, detail="Draft not found or already processed")
            if result["status"] == "send_failed":
                raise HTTPException(status_code=500, detail=f"Failed to send email: {result.get('error')}")
            return {"status": "success", "message": "Draft approved and sent" if request.approved else "Draft rejected"}
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process draft approval: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BatchDraftApprovalRequest(BaseModel):
    draft_ids: List[int]
    approved: bool


@app.post("/api/drafts/batch-approve")
async def batch_approve_drafts(request: BatchDraftApprovalRequest, user: dict = Depends(get_current_user)):
    """Approve or reject many drafts in one call."""
    try:
        from utils.db_connection import get_conn
        draft_ids = sorted(set(request.draft_ids))
        if not draft_ids:
            raise HTTPException(status_code=400, detail="draft_ids cannot be empty")

        results: list[Dict[str, Any]] = []
        with get_conn() as conn:
            for draft_id in draft_ids:
                results.append(await _process_single_draft_approval(conn, draft_id, request.approved))

        summary = {
            "requested": len(draft_ids),
            "approved_sent": sum(1 for r in results if r["status"] == "approved_sent"),
            "rejected": sum(1 for r in results if r["status"] == "rejected"),
            "not_found": sum(1 for r in results if r["status"] == "not_found"),
            "send_failed": sum(1 for r in results if r["status"] == "send_failed"),
        }
        return {"status": "success", "summary": summary, "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed batch draft approval: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _stop_future_attempts_for_draft(conn, lead_id: int, campaign_id: int):
    """Mark campaign lead as fully attempted so outreach won't generate another draft."""
    conn.execute(
        "UPDATE campaign_leads "
        "SET emails_sent = COALESCE((SELECT max_emails_per_lead FROM campaigns WHERE id = ?), emails_sent) "
        "WHERE campaign_id = ? AND lead_id = ?",
        (campaign_id, campaign_id, lead_id),
    )


def _process_single_draft_delete(conn, draft_id: int, stop_future_attempts: bool) -> Dict[str, Any]:
    """Delete one pending draft and optionally stop future attempts for that lead/campaign."""
    cur = conn.execute(
        "SELECT id, lead_id, campaign_id FROM email_messages "
        "WHERE id = ? AND status = 'DRAFT' AND approved = 0 AND direction = 'outbound'",
        (draft_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"draft_id": draft_id, "status": "not_found"}

    lead_id = row["lead_id"]
    campaign_id = row["campaign_id"]

    conn.execute("DELETE FROM email_messages WHERE id = ?", (draft_id,))
    if stop_future_attempts and lead_id and campaign_id:
        _stop_future_attempts_for_draft(conn, lead_id, campaign_id)
    return {"draft_id": draft_id, "status": "deleted", "stop_future_attempts": stop_future_attempts}


@app.delete("/api/drafts/{draft_id}")
async def delete_draft(
    draft_id: int,
    stop_future_attempts: bool = True,
    user: dict = Depends(get_current_user),
):
    """Delete one pending draft and optionally stop future attempts for that lead in the campaign."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            result = _process_single_draft_delete(conn, draft_id, stop_future_attempts)
            if result["status"] == "not_found":
                raise HTTPException(status_code=404, detail="Draft not found or already processed")
            return {"status": "success", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete draft {draft_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BatchDraftDeleteRequest(BaseModel):
    draft_ids: List[int]
    stop_future_attempts: bool = True


@app.post("/api/drafts/batch-delete")
async def batch_delete_drafts(request: BatchDraftDeleteRequest, user: dict = Depends(get_current_user)):
    """Delete many pending drafts and optionally stop future attempts."""
    try:
        from utils.db_connection import get_conn
        draft_ids = sorted(set(request.draft_ids))
        if not draft_ids:
            raise HTTPException(status_code=400, detail="draft_ids cannot be empty")

        results: list[Dict[str, Any]] = []
        with get_conn() as conn:
            for draft_id in draft_ids:
                results.append(_process_single_draft_delete(conn, draft_id, request.stop_future_attempts))

        summary = {
            "requested": len(draft_ids),
            "deleted": sum(1 for r in results if r["status"] == "deleted"),
            "not_found": sum(1 for r in results if r["status"] == "not_found"),
        }
        return {"status": "success", "summary": summary, "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed batch draft delete: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/outreach/stream")
async def stream_outreach(campaign_name: Optional[str] = None, user: dict = Depends(get_current_user)):
    """Execute campaign and stream progress via SSE."""
    async def event_generator():
        try:
            # Helper to yield SSE events
            async def sse_callback(status: str, message: str):
                data = json.dumps({"status": status, "message": message})
                # Note: We need to use a non-blocking yield here, but since this is 
                # called from within the orchestrator, we'll use a queue or 
                # just yield directly if possible.
                # For this implementation, we'll use a simple queue to bridge 
                # the orchestrator and the generator.
                await queue.put(f"data: {data}\n\n")

            queue = asyncio.Queue()
            
            # Start orchestrator in a background task
            task = asyncio.create_task(
                outreach_orchestrator.execute_campaign(
                    campaign_name=campaign_name, 
                    callback=sse_callback
                )
            )

            # Yield events from the queue until the task is done
            while not task.done() or not queue.empty():
                try:
                    # Wait for an event with a timeout to check task status
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield event
                except asyncio.TimeoutError:
                    continue
            
            # Final check for exceptions
            if task.exception():
                raise task.exception()
                
        except Exception as e:
            logger.error(f"Streaming outreach failed: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/outreach/campaign")  
async def execute_marketing_campaign(background_tasks: BackgroundTasks, campaign_name: Optional[str] = None) -> dict:
    """Execute intelligent outreach campaign via Orchestrator (database-driven)."""
    try:
        background_tasks.add_task(outreach_orchestrator.execute_campaign, campaign_name)
        return {
            "status": "accepted", 
            "message": f"Campaign execution started in background for {campaign_name or 'random active campaign'}"
        }
    except Exception as e:
        logger.error(f"Marketing campaign failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/webhooks/stream")
async def stream_webhooks(user: dict = Depends(get_current_user)):
    """Stream incoming webhook processing logs via SSE."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    webhook_broadcaster.connections.append(queue)
    
    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in webhook_broadcaster.connections:
                webhook_broadcaster.connections.remove(queue)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Email monitoring endpoints
@app.post("/webhook")
async def handle_webhook(request: Request) -> Dict[str, Any]:
    """Handle AgentMail webhook events (received messages only) with simplified loop prevention."""
    try:
        # Validate webhook secret when configured
        if settings.webhook_secret:
            sig = request.headers.get("x-webhook-signature", "")
            raw_body = await request.body()
            expected = hmac.HMAC(
                settings.webhook_secret.encode(), raw_body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(sig, expected):
                logger.warning("Webhook signature mismatch - rejecting request")
                raise HTTPException(status_code=403, detail="Invalid webhook signature")
            payload = json.loads(raw_body)
        else:
            payload = await request.json()
        event = WebhookEvent(**payload)
        
        sender_email = extract_sender_email(event.message)
        sender_name = extract_sender_name(event.message)
        subject = extract_subject(event.message)
        logger.info(f"Received webhook: {event.event_id}")
        
        cb = webhook_broadcaster.scoped(event.event_id)
        await cb(
            "info",
            f"Received webhook: {event.event_type} - {event.event_id} | From: {sender_name} <{sender_email}> | Subject: {subject}"
        )
        
        # Simplified processing decision (webhooks are received-only)
        should_process, reason = await should_process_webhook(
            event.event_id, 
            event.event_type, 
            event.message,
            DEFAULT_LOOP_PREVENTION
        )
        
        if not should_process:
            logger.info(f"Skipping webhook {event.event_id}: {reason}")
            await cb("warning", f"Skipping webhook {event.event_id}: {reason}")
            return {"status": "skipped", "reason": reason, "event_id": event.event_id}
        
        # Process received message
        logger.info(f"Processing received message: {event.event_id}")
        await cb("info", f"Starting pipeline for message: {event.event_id}")
        
        result = await email_monitor.process_incoming_email(event.message, callback=cb)
        
        return {
            "status": "processed", 
            "event_id": event.event_id,
            "action": result.action_taken,
            "success": result.success,
            "message_id": result.message_id,
            "error": result.error
        }
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        await webhook_broadcaster.broadcast("error", f"Webhook error: {str(e)}", event_id=getattr(event, 'event_id', '') if 'event' in dir() else "")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email-monitor/health")
async def email_monitor_health() -> Dict[str, str]:
    """Email monitor health check."""
    return {"status": "healthy", "service": "email_monitor"}


def _is_our_message(message_data: Dict[str, Any]) -> bool:
    """Legacy function - replaced by enhanced webhook_utils.is_our_outgoing_message()"""
    labels = message_data.get('labels', [])
    return 'sent' in labels

