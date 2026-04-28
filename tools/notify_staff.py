"""Tool to notify staff members about scheduled meetings."""

import logging
import json        
from config.logging import setup_logging
from agents import function_tool
from tools.send_email import send_plain_email
from schema import SendEmailResult, MeetingDetails
from utils.db_connection import get_conn

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def _build_tentative_email(client_email: str, subject: str, start_time: str,
                           duration: int, description: str, summary: str) -> tuple[str, str]:
    """Build a heads-up notification for a proposed (unconfirmed) meeting."""
    staff_subject = f"HEADS UP: Meeting Proposed - {subject}"
    staff_body = f"""Hi there,

A lead has expressed interest in scheduling a meeting. We have proposed a time to them and are AWAITING THEIR CONFIRMATION. Please do NOT create a calendar event yet.

STATUS: PENDING CONFIRMATION

CLIENT EMAIL: {client_email}
MEETING TITLE: {subject}
PROPOSED TIME: {start_time}
DURATION: {duration} minutes
AGENDA: {description}

CONVERSATION CONTEXT:
{summary}

WHAT HAPPENS NEXT:
- If the client confirms the time, you will receive a follow-up "ACTION REQUIRED" email to create the calendar event.
- No action is needed from you right now.

Best regards,
SDR Automation System"""
    return staff_subject, staff_body


def _build_confirmed_email(client_email: str, subject: str, start_time: str,
                           duration: int, description: str, summary: str) -> tuple[str, str]:
    """Build an action-required notification for a confirmed meeting."""
    staff_subject = f"ACTION REQUIRED: Meeting Confirmed - {subject}"
    staff_body = f"""Hi there,

The client has CONFIRMED the proposed meeting time. Please CREATE a Google Calendar invite now.

STATUS: CONFIRMED

CLIENT EMAIL: {client_email}
MEETING TITLE: {subject}
CONFIRMED TIME: {start_time}
DURATION: {duration} minutes
AGENDA: {description}

CONVERSATION CONTEXT:
{summary}

ACTION NEEDED:
1. Create a Google Calendar event with the details above
2. Add {client_email} as an attendee (send invitation)
3. Include a Google Meet link for the call
4. If the proposed time doesn't work, reach out to the client to reschedule

Best regards,
SDR Automation System"""
    return staff_subject, staff_body


@function_tool
async def notify_staff_about_meeting(
    staff_email: str,
    client_email: str, 
    meeting_details: str,
    confirmed: bool = False,
    campaign_id: int | None = None,
) -> SendEmailResult:
    """Send notification email to staff member about a meeting.
    
    Args:
        staff_email: Staff member's email address
        client_email: Client's email address
        meeting_details: JSON string containing MeetingDetails with all meeting info and conversation summary
        confirmed: If True, send an ACTION REQUIRED email (client confirmed). If False (default), send a HEADS UP email (awaiting confirmation).
        campaign_id: Optional campaign ID. If provided, staff_email must be assigned to this campaign.
        
    Returns:
        SendEmailResult with success status
    """
    try:
        if campaign_id is not None:
            conn = get_conn()
            assignment = conn.execute(
                "SELECT 1 FROM campaign_staff cs "
                "JOIN staff s ON s.id = cs.staff_id "
                "WHERE cs.campaign_id = ? AND LOWER(s.email) = LOWER(?) LIMIT 1",
                (campaign_id, staff_email),
            ).fetchone()
            if not assignment:
                error = (
                    f"Staff routing blocked: {staff_email} is not assigned to campaign {campaign_id}. "
                    "Update Campaign Staff assignments first."
                )
                logger.error(error)
                return SendEmailResult(ok=False, error=error)

        try:
            details_dict = json.loads(meeting_details)
            meeting = MeetingDetails(**details_dict)
            
            subject = meeting.subject
            start_time = meeting.start_time
            duration = meeting.duration_minutes
            description = meeting.description
            summary = meeting.conversation_summary
        except Exception as parse_error:
            logger.warning(f"Failed to parse MeetingDetails JSON exactly, falling back to raw text: {parse_error}")
            subject = "New Meeting Scheduled"
            start_time = "Unknown"
            duration = 30
            description = "See conversation context"
            summary = meeting_details

        if confirmed:
            staff_subject, staff_body = _build_confirmed_email(
                client_email, subject, start_time, duration, description, summary
            )
        else:
            staff_subject, staff_body = _build_tentative_email(
                client_email, subject, start_time, duration, description, summary
            )

        result = await send_plain_email(
            email=staff_email,
            name="Team Member",
            subject=staff_subject,
            body=staff_body,
            internal=True,
        )
        
        status_label = "confirmed" if confirmed else "tentative"
        if result.ok:
            logger.info(f"Staff {status_label} notification sent to {staff_email} for meeting with {client_email}")
        else:
            logger.error(f"Failed to send staff {status_label} notification: {result.error}")
            
        return result
        
    except Exception as e:
        logger.error(f"Error sending staff notification: {e}")
        return SendEmailResult(
            ok=False,
            error=f"Failed to send staff notification: {str(e)}"
        )