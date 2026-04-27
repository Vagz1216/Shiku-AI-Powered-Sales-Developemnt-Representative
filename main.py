"""
Main FastAPI application with consolidated API endpoints.

Combines outreach and email monitoring functionality.
"""

import asyncio
import hashlib
import hmac
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time
import json

from config.logging import setup_logging
from config import settings
from schema import WebhookEvent
from email_monitor.monitor import email_monitor
from email_monitor.webhook_utils import should_process_webhook, DEFAULT_LOOP_PREVENTION
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
    
    async def broadcast(self, status: str, message: str):
        stale: list[asyncio.Queue] = []
        for queue in self.connections:
            try:
                queue.put_nowait({"status": status, "message": message})
            except asyncio.QueueFull:
                stale.append(queue)
        for q in stale:
            self.connections.remove(q)

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
    except Exception as e:
        logger.error(f"Failed to delete campaign {campaign_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/drafts")
async def list_drafts(user: dict = Depends(get_current_user)):
    """List all pending email drafts awaiting approval."""
    try:
        from utils.db_connection import get_conn
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT e.id, e.subject, e.body, l.name as lead_name, l.email as lead_email, c.name as campaign_name "
                "FROM email_messages e "
                "JOIN leads l ON e.lead_id = l.id "
                "JOIN campaigns c ON e.campaign_id = c.id "
                "WHERE e.status = 'DRAFT' AND e.approved = 0 AND e.direction = 'outbound'"
            )
            drafts = [dict(row) for row in cur.fetchall()]
        return {"drafts": drafts}
    except Exception as e:
        logger.error(f"Failed to list drafts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from pydantic import BaseModel
class DraftApprovalRequest(BaseModel):
    approved: bool

@app.post("/api/drafts/{draft_id}/approve")
async def approve_draft(draft_id: int, request: DraftApprovalRequest, user: dict = Depends(get_current_user)):
    """Approve or reject a pending email draft."""
    try:
        from utils.db_connection import get_conn
        from tools.send_email import send_plain_email
        
        with get_conn() as conn:
            # Get draft details
            cur = conn.execute(
                "SELECT e.id, e.subject, e.body, l.name as lead_name, l.email as lead_email "
                "FROM email_messages e "
                "JOIN leads l ON e.lead_id = l.id "
                "WHERE e.id = ? AND e.status = 'DRAFT' AND e.approved = 0",
                (draft_id,)
            )
            draft = cur.fetchone()
            
            if not draft:
                raise HTTPException(status_code=404, detail="Draft not found or already processed")
            
            draft = dict(draft)
            
            if request.approved:
                # Send the email
                send_res = await send_plain_email(
                    email=draft["lead_email"],
                    name=draft["lead_name"],
                    subject=draft["subject"],
                    body=draft["body"]
                )
                
                if send_res.ok:
                    # Update status
                    conn.execute(
                        "UPDATE email_messages SET approved = 1, status = 'SENT' WHERE id = ?",
                        (draft_id,)
                    )
                    return {"status": "success", "message": "Draft approved and sent"}
                else:
                    raise HTTPException(status_code=500, detail=f"Failed to send email: {send_res.error}")
            else:
                # Reject draft
                conn.execute(
                    "UPDATE email_messages SET approved = -1, status = 'REJECTED' WHERE id = ?",
                    (draft_id,)
                )
                return {"status": "success", "message": "Draft rejected"}
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process draft approval: {e}")
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
        
        logger.info(f"Received webhook: {event.event_id}")
        await webhook_broadcaster.broadcast("info", f"Received webhook: {event.event_type} - {event.event_id}")
        
        # Simplified processing decision (webhooks are received-only)
        should_process, reason = await should_process_webhook(
            event.event_id, 
            event.event_type, 
            event.message,
            DEFAULT_LOOP_PREVENTION
        )
        
        if not should_process:
            logger.info(f"Skipping webhook {event.event_id}: {reason}")
            await webhook_broadcaster.broadcast("warning", f"Skipping webhook {event.event_id}: {reason}")
            return {"status": "skipped", "reason": reason, "event_id": event.event_id}
        
        # Process received message
        logger.info(f"Processing received message: {event.event_id}")
        await webhook_broadcaster.broadcast("info", f"Starting pipeline for message: {event.event_id}")
        
        # We run this in the background or await it directly.
        # But we need to pass the broadcast callback.
        result = await email_monitor.process_incoming_email(event.message, callback=webhook_broadcaster.broadcast)
        
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
        await webhook_broadcaster.broadcast("error", f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email-monitor/health")
async def email_monitor_health() -> Dict[str, str]:
    """Email monitor health check."""
    return {"status": "healthy", "service": "email_monitor"}


def _is_our_message(message_data: Dict[str, Any]) -> bool:
    """Legacy function - replaced by enhanced webhook_utils.is_our_outgoing_message()"""
    labels = message_data.get('labels', [])
    return 'sent' in labels

