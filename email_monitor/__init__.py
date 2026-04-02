"""Email monitoring system - intent-based webhook email processing."""

from .intent_extractor import IntentExtractorAgent
from .email_response import EmailResponseAgent
from .monitor import EmailMonitorSystem, email_monitor
from .server import app
from schema import EmailIntent, EmailActionResult

__all__ = [
    "EmailMonitorSystem",
    "EmailIntent", 
    "EmailActionResult",
    "IntentExtractorAgent",
    "EmailResponseAgent",
    "email_monitor",
    "app"
]