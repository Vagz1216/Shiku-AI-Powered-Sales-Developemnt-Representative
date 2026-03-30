"""Webhook server for AgentMail events with intent-based processing."""

import asyncio
import logging
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any

from config import settings
from .agent import email_monitor

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Email Monitor", description="AgentMail webhook handler with intent analysis")


class WebhookEvent(BaseModel):
    """AgentMail webhook event structure."""
    event_type: str = Field(..., description="Type of event, e.g. message.received")
    event_id: str = Field(..., description="Unique identifier for the event")
    message: Dict[str, Any] = Field(..., description="Message payload")


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


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "email_monitor"}


@app.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint."""
    return {
        "service": "Email Monitor",
        "version": "1.0.0",
        "webhook": "/webhook",
        "health": "/health"
    }


def _is_our_message(message_data: Dict[str, Any]) -> bool:
    """Check if this message was sent by us."""
    labels = message_data.get('labels', [])
    return 'sent' in labels