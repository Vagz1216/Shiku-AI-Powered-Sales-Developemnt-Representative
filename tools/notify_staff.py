"""Tool to notify staff members about scheduled meetings."""

import logging
import json        
from config.logging import setup_logging
from agents import function_tool
from tools.send_email import send_plain_email
from schema import SendEmailResult, MeetingDetails

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


@function_tool
async def notify_staff_about_meeting(
    staff_email: str,
    client_email: str, 
    meeting_details: str  # JSON string of MeetingDetails object
) -> SendEmailResult:
    """Send notification email to staff member about scheduled meeting.
    
    Args:
        staff_email: Staff member's email address
        client_email: Client's email address
        meeting_details: JSON string containing MeetingDetails with all meeting info and conversation summary
        
    Returns:
        SendEmailResult with success status
    """
    try:
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

        staff_subject = f"ACTION REQUIRED: Schedule Meeting - {subject}"
        
        staff_body = f"""Hi there,

A client has requested a meeting. Please CREATE a Google Calendar invite with the details below.

CLIENT EMAIL: {client_email}
MEETING TITLE: {subject}
PROPOSED TIME: {start_time}
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

        result = await send_plain_email(
            email=staff_email,
            name="Team Member",
            subject=staff_subject,
            body=staff_body,
            internal=True,
        )
        
        if result.ok:
            logger.info(f"Staff notification sent to {staff_email} for meeting with {client_email}")
        else:
            logger.error(f"Failed to send staff notification: {result.error}")
            
        return result
        
    except Exception as e:
        logger.error(f"Error sending staff notification: {e}")
        return SendEmailResult(
            ok=False,
            error=f"Failed to send staff notification: {str(e)}"
        )