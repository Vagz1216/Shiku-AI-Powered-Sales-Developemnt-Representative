"""Meeting details generation tool for creating structured meeting information."""

import logging
from datetime import datetime, timedelta

from config.logging import setup_logging
from agents import function_tool, set_default_openai_key
from config import settings
from schema import MeetingDetails

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Set OpenAI API key for agents library
if settings.openai_api_key:
    set_default_openai_key(settings.openai_api_key)


@function_tool
async def generate_meeting_details(email_context: str, sender_email: str, staff_email: str = "", staff_availability: str = "", staff_timezone: str = "UTC", meeting_delay_days: int = 1) -> MeetingDetails:
    """Generate structured meeting details from email context.
    
    Args:
        email_context: The email content and conversation history
        sender_email: Email address of the sender
        staff_email: Email address of the staff member
        staff_availability: Staff member's availability in JSON string format
        staff_timezone: Staff member's timezone
        meeting_delay_days: Number of days to delay before scheduling
        
    Returns:
        MeetingDetails with subject, start_time, duration_minutes, description
    """
    
    now = datetime.now()
    start_date = now + timedelta(days=meeting_delay_days)
    # Skip weekends
    while start_date.weekday() >= 5:
        start_date += timedelta(days=1)

    instructions = f"""
You are a meeting coordinator. Propose a meeting time based on the staff member's availability.

TODAY'S DATE: {now.strftime('%Y-%m-%d')}
EARLIEST MEETING DATE: {start_date.strftime('%Y-%m-%d')} ({start_date.strftime('%A')})
STAFF EMAIL: {staff_email}
STAFF TIMEZONE: {staff_timezone}
STAFF AVAILABILITY: {staff_availability}

Rules:
- Subject: Professional meeting title including the client's company name
- Start Time: Pick a slot on or after {start_date.strftime('%Y-%m-%d')} that fits within the STAFF AVAILABILITY hours. Skip weekends. Format: YYYY-MM-DD HH:MM
- Duration: 30 min (general) or 60 min (demos/detailed discussion)
- Description: Brief context from the email conversation
- Conversation Summary: 2-3 sentence summary of the email thread for the staff member
- Rationale: Explain why you picked this slot

Do NOT call any external tools. Just reason from the availability data provided.
"""
    
    company_name = sender_email.split('@')[1].split('.')[0].title() if '@' in sender_email else "Client"
    
    try:
        from utils.model_fallback import run_agent_with_fallback
        
        result, provider = await run_agent_with_fallback(
            name="MeetingDetailsGenerator",
            instructions=instructions,
            prompt=email_context,
            output_type=MeetingDetails,
            temperature=0.3,
            max_tokens=600,
        )
        
        meeting_details = result.final_output
        logger.info(f"Generated meeting details for {sender_email} via {provider}: {meeting_details.subject}")
        return meeting_details
    except Exception as e:
        logger.error(f"Error generating meeting details: {e}")
        company_name = sender_email.split('@')[1].split('.')[0].title() if '@' in sender_email else "Client"
        next_business_day = datetime.now() + timedelta(days=1)
        while next_business_day.weekday() >= 5:
            next_business_day += timedelta(days=1)
        return MeetingDetails(
            rationale="Fallback rationale due to meeting generation error.",
            subject=f"Business Discussion - {company_name}",
            start_time=next_business_day.replace(hour=14, minute=0).strftime('%Y-%m-%d %H:%M'),
            duration_minutes=30,
            description=f"Meeting to discuss business needs and explore potential collaboration opportunities with {company_name}.",
            conversation_summary=f"Client {sender_email} expressed interest in our services and requested a meeting to discuss how we can help their company."
        )