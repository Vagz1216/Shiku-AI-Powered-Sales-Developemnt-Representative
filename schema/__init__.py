"""Pydantic schemas for the Squad3 application."""

from .email import EmailIntent, EmailActionResult, WebhookEvent, ResponseEvaluation, MeetingResult, MeetingDetails, EmailResponse
from .tools import SendEmailResult, LeadOut, StaffOut
from .outreach import OutreachEmailDraft, OutreachSendResult, OutreachRunRecord, LeadInfo
from .leads import LeadCreate, LeadUpdate, BulkLeadImportRequest, ApiLeadImportRequest
from .tenancy import MailboxCreate, OrganizationCreate, OrganizationUserUpsert

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
    "LeadInfo",
    "LeadCreate",
    "LeadUpdate",
    "BulkLeadImportRequest",
    "ApiLeadImportRequest",
    "MailboxCreate",
    "OrganizationCreate",
    "OrganizationUserUpsert",
]
