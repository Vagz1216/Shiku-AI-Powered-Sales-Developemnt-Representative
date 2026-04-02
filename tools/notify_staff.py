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
def notify_staff_about_meeting(
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
        details_dict = json.loads(meeting_details)
        meeting = MeetingDetails(**details_dict)
        
        # Create staff notification email
        staff_subject = f"Meeting Scheduled: {meeting.subject}"
        
        staff_body = f"""Hi there,

A meeting has been automatically scheduled with a client. Here are the details:

CLIENT: {client_email}
MEETING: {meeting.subject}
TIME: {meeting.start_time}
DURATION: {meeting.duration_minutes} minutes
AGENDA: {meeting.description}

CONVERSATION CONTEXT:
{meeting.conversation_summary}

The client has been sent a calendar invitation. Please review your calendar and prepare for the meeting.

If you need to reschedule or have any questions, please contact the client directly.

Best regards,
Team Coordination"""

        # Send notification to staff
        result = send_plain_email(
            email=staff_email,
            name="Team Member",
            subject=staff_subject,
            body=staff_body
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