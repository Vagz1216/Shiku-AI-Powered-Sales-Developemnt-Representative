"""Email monitoring system - intent-based webhook email processing."""

from .agent import EmailMonitorSystem, EmailIntent, EmailActionResult, IntentExtractorAgent, EmailResponseAgent, email_monitor
from .server import app

__all__ = [
    "EmailMonitorSystem",
    "EmailIntent", 
    "EmailActionResult",
    "IntentExtractorAgent",
    "EmailResponseAgent",
    "email_monitor",
    "app"
]