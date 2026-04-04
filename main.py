"""
Main FastAPI application with consolidated API endpoints.

Combines outreach and email monitoring functionality.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import gradio as gr
import time

from config.logging import setup_logging
from config import settings
from schema import WebhookEvent
from email_monitor.monitor import email_monitor
from email_monitor.webhook_utils import should_process_webhook, DEFAULT_LOOP_PREVENTION
from outreach.gradio_interface import create_outreach_interface

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# HTTP Access Logging Middleware
class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
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


# Health endpoints
@app.get("/health")
def health() -> Dict[str, str]:
    """Global health check."""
    return {"status": "ok", "service": "Andela AI Bootcamp Euclid Squad 3 API"}


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
@app.post("/outreach/campaign")  
async def execute_marketing_campaign(campaign_name: Optional[str] = None) -> dict:
    """Execute intelligent outreach campaign via Senior Marketing Agent (database-driven)."""
    try:
        from outreach.marketing_agent import senior_marketing_agent
        result = await senior_marketing_agent.execute_campaign(campaign_name=campaign_name)
        return result
    except Exception as e:
        logger.error(f"Marketing campaign failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Email monitoring endpoints  
@app.post("/webhook")
async def handle_webhook(request: Request) -> Dict[str, Any]:
    """Handle AgentMail webhook events (received messages only) with simplified loop prevention."""
    try:
        # Parse webhook payload
        payload = await request.json()
        event = WebhookEvent(**payload)
        
        logger.info(f"Received webhook: {event.event_id}")
        
        # Simplified processing decision (webhooks are received-only)
        should_process, reason = await should_process_webhook(
            event.event_id, 
            event.event_type, 
            event.message,
            DEFAULT_LOOP_PREVENTION
        )
        
        if not should_process:
            logger.info(f"Skipping webhook {event.event_id}: {reason}")
            return {"status": "skipped", "reason": reason, "event_id": event.event_id}
        
        # Process received message
        logger.info(f"Processing received message: {event.event_id}")
        result = await email_monitor.process_incoming_email(event.message)
        
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
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email-monitor/health")
async def email_monitor_health() -> Dict[str, str]:
    """Email monitor health check."""
    return {"status": "healthy", "service": "email_monitor"}


def _is_our_message(message_data: Dict[str, Any]) -> bool:
    """Legacy function - replaced by enhanced webhook_utils.is_our_outgoing_message()"""
    labels = message_data.get('labels', [])
    return 'sent' in labels


# Mount Gradio interface for outreach campaign management
outreach_interface = create_outreach_interface()
app = gr.mount_gradio_app(app, outreach_interface, path="/outreach")

