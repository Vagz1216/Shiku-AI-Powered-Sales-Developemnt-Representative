"""Tools for agent operations and shared send helpers."""

from schema import SendEmailResult

from .send_email import send_agent_email, send_plain_email
from .email_reply import send_reply_email
from .google_calendar import create_google_meeting, get_upcoming_free_slots
from .notify_staff import notify_staff_about_meeting
from .generate_meeting_details import generate_meeting_details
from .staff_tools import get_staff_tool
from .lead_tools import get_lead_tool
from .campaign_tools import get_campaign_tool
from .content_tools import create_professional_email, create_engaging_email, create_concise_email

__all__ = [
    "send_agent_email", 
    "send_plain_email",
    "SendEmailResult", 
    "send_reply_email",
    "create_google_meeting",
    "notify_staff_about_meeting",
    "generate_meeting_details",
    "get_staff_tool",
    "get_lead_tool",
    "get_campaign_tool",
    "create_professional_email",
    "create_engaging_email", 
    "create_concise_email"
]

