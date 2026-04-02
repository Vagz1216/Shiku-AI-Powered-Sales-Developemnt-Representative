"""Pydantic schemas for the Squad3 application."""

from .email import EmailIntent, EmailActionResult, WebhookEvent, ResponseEvaluation, MeetingResult, MeetingDetails, EmailResponse
from .tools import SendEmailResult, LeadOut, StaffOut
from .outreach import OutreachEmailDraft, OutreachSendResult, OutreachRunRecord, LeadInfo

__all__ = [
    "EmailIntent",
    "EmailActionResult", 
    "WebhookEvent",
    "ResponseEvaluation",
    "MeetingResult",
    "MeetingDetails",
    "EmailResponse",
    "SendEmailResult",
    "LeadOut",
    "StaffOut",
    "OutreachEmailDraft",
    "OutreachSendResult", 
    "OutreachRunRecord",
    "LeadInfo"
]