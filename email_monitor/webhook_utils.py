"""Enhanced webhook handling with deduplication and loop prevention."""

import logging
from typing import Dict, Any, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
import asyncio

logger = logging.getLogger(__name__)

# In-memory cache for processed events (in production, use Redis or database)
_processed_events: Dict[str, datetime] = {}
_processing_lock = asyncio.Lock()

# Cleanup interval (remove events older than 1 hour)
CLEANUP_INTERVAL = timedelta(hours=1)
MAX_EVENT_AGE = timedelta(hours=1)

@dataclass
class WebhookLoopPrevention:
    """Simplified configuration for webhook loop prevention (received messages only)."""
    enable_event_deduplication: bool = True
    enable_system_email_check: bool = True  # Safety net for system emails
    max_processing_time: float = 60.0  # seconds
    
def cleanup_old_events():
    """Remove old processed events from memory."""
    cutoff_time = datetime.utcnow() - MAX_EVENT_AGE
    expired_events = [
        event_id for event_id, timestamp in _processed_events.items() 
        if timestamp < cutoff_time
    ]
    
    for event_id in expired_events:
        del _processed_events[event_id]
    
    if expired_events:
        logger.info(f"Cleaned up {len(expired_events)} expired webhook events")


async def is_duplicate_event(event_id: str, config: WebhookLoopPrevention) -> bool:
    """Check if this webhook event was already processed recently."""
    if not config.enable_event_deduplication:
        return False
        
    async with _processing_lock:
        # Clean up old events periodically
        cleanup_old_events()
        
        # Check if event was already processed
        if event_id in _processed_events:
            time_since = datetime.utcnow() - _processed_events[event_id]
            logger.warning(f"Duplicate event detected: {event_id} (last seen {time_since.total_seconds():.1f}s ago)")
            return True
        
        # Mark event as being processed
        _processed_events[event_id] = datetime.utcnow()
        return False


def is_system_email(message_data: Dict[str, Any], config: WebhookLoopPrevention) -> bool:
    """Check if message is from a system email (safety net for received webhooks)."""
    
    if not config.enable_system_email_check:
        return False
        
    # Extract sender email for system pattern checking
    from_field = message_data.get('from_', [])
    if isinstance(from_field, list) and from_field:
        sender_email = from_field[0]
        if isinstance(sender_email, str):
            # Check for system email patterns as safety net
            system_email_patterns = [
                '@agentmail.to',
                'agent_sales@',  # Our outbound agent email pattern  
                'noreply@',
                'no-reply@'
            ]
            
            sender_lower = sender_email.lower()
            for pattern in system_email_patterns:
                if pattern in sender_lower:
                    logger.debug(f"System email detected: '{sender_email}' - skipping as safety measure")
                    return True
    
    return False


def analyze_received_message(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze received message for debugging (simplified for received-only webhooks)."""
    
    analysis = {
        'labels': message_data.get('labels', []),
        'from_field': message_data.get('from_', []),
        'thread_id': message_data.get('thread_id'),
        'message_id': message_data.get('id', message_data.get('message_id')),
        'potential_issues': []
    }
    
    # Check for unexpected conditions in received messages
    labels = analysis['labels']
    
    if 'sent' in labels:
        analysis['potential_issues'].append("Received webhook contains 'sent' label - unexpected for incoming messages")
    
    if not labels:
        analysis['potential_issues'].append("Message has no labels - may indicate payload issue")
    
    # Check expected 'received' label
    if 'received' not in labels:
        analysis['potential_issues'].append("Missing 'received' label - unexpected for webhook trigger")
    
    # Check sender patterns  
    from_field = analysis['from_field']
    if isinstance(from_field, list) and from_field:
        sender = from_field[0] if isinstance(from_field[0], str) else str(from_field[0])
        if '@agentmail.to' in sender.lower():
            analysis['potential_issues'].append(f"Received message from system email: {sender}")
    
    return analysis


async def should_process_webhook(event_id: str, event_type: str, message_data: Dict[str, Any], 
                               config: WebhookLoopPrevention = None) -> tuple[bool, str]:
    """
    Simplified webhook processing decision for received-only messages.
    
    Returns:
        (should_process: bool, reason: str)
    """
    if config is None:
        config = WebhookLoopPrevention()
    
    # 1. Check for duplicate events (still useful for rapid duplicates)
    if await is_duplicate_event(event_id, config):
        return False, "duplicate_event"
    
    # 2. Safety check for system emails (shouldn't happen in received webhooks, but safety net)
    if is_system_email(message_data, config):
        return False, "system_email"
    
    # 3. Analysis for debugging (simplified for received messages)
    message_analysis = analyze_received_message(message_data)
    if message_analysis['potential_issues']:
        logger.warning(f"Received message issues for event {event_id}: {message_analysis['potential_issues']}")
        # Log warnings but still process - these are informational
    
    return True, "processing"


# Export simplified configuration for received-only webhooks
DEFAULT_LOOP_PREVENTION = WebhookLoopPrevention(
    enable_event_deduplication=True,
    enable_system_email_check=True,  # Safety net
    max_processing_time=60.0
)