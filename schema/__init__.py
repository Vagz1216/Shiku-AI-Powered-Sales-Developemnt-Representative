"""Pydantic schemas for the Squad3 application."""

from .email import EmailIntent, EmailActionResult, WebhookEvent
from .tools import SendEmailResult

__all__ = [
    "EmailIntent",
    "EmailActionResult", 
    "WebhookEvent",
    "SendEmailResult"
]