"""Email monitoring system - intent-based webhook email processing."""

from .intent_extractor import IntentExtractorAgent
from .email_response import EmailResponseAgent
from .response_evaluator import ResponseEvaluator
from .email_sender import EmailSenderAgent
from .monitor import EmailMonitorSystem, email_monitor
from .server import app
from schema import EmailIntent, EmailActionResult

__all__ = [
    "EmailMonitorSystem",
    "EmailIntent", 
    "EmailActionResult",
    "IntentExtractorAgent",
    "EmailResponseAgent",
    "ResponseEvaluator",
    "EmailSenderAgent",
    "email_monitor",
    "app"
]