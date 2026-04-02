"""
Main FastAPI application with consolidated API endpoints.

Combines outreach and email monitoring functionality.
"""

import asyncio
import logging
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import gradio as gr
import time

from config.logging import setup_logging
from config import settings
from schema import WebhookEvent
from email_monitor.monitor import email_monitor
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
    title="Squad3 API", 
    description="Outreach and Email Monitoring System",
    version="1.0.0"
)

# Add access logging middleware
app.add_middleware(AccessLogMiddleware)


# Health endpoints
@app.get("/health")
def health() -> Dict[str, str]:
    """Global health check."""
    return {"status": "ok", "service": "squad3_api"}


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint with API overview."""
    return {
        "service": "Squad3 API",
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
async def execute_marketing_campaign() -> dict:
    """Execute intelligent outreach campaign via Senior Marketing Agent (database-driven)."""
    try:
        from outreach.marketing_agent import senior_marketing_agent
        result = await senior_marketing_agent.execute_campaign()
        return result
    except Exception as e:
        logger.error(f"Marketing campaign failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Email monitoring endpoints  
@app.post("/webhook")
async def handle_webhook(request: Request) -> Dict[str, Any]:
    """Handle AgentMail webhook events with intent analysis."""
    try:
        # Parse webhook payload
        payload = await request.json()
        event = WebhookEvent(**payload)
        
        logger.info(f"Received {event.event_type} event: {event.event_id}")
        
        # Only process message.received events
        if event.event_type == "message.received":
            # Skip our own messages
            if _is_our_message(event.message):
                logger.info("Skipping our own message")
                return {"status": "skipped", "reason": "own_message"}
            
            # Process with intent-based system
            result = await email_monitor.process_incoming_email(event.message)
            
            return {
                "status": "processed", 
                "action": result.action_taken,
                "success": result.success,
                "message_id": result.message_id,
                "error": result.error
            }
        
        return {"status": "ignored", "reason": f"event_type_{event.event_type}"}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email-monitor/health")
async def email_monitor_health() -> Dict[str, str]:
    """Email monitor health check."""
    return {"status": "healthy", "service": "email_monitor"}


def _is_our_message(message_data: Dict[str, Any]) -> bool:
    """Check if this message was sent by us."""
    labels = message_data.get('labels', [])
    return 'sent' in labels


# Mount Gradio interface for outreach campaign management
outreach_interface = create_outreach_interface()
app = gr.mount_gradio_app(app, outreach_interface, path="/outreach")