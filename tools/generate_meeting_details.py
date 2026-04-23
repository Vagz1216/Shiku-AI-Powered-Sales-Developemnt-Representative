"""Meeting details generation tool for creating structured meeting information."""

import logging
from datetime import datetime, timedelta

from config.logging import setup_logging
from agents import Agent, ModelSettings, Runner, function_tool, set_default_openai_key
from config import settings
from schema import MeetingDetails

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Set OpenAI API key for agents library
if settings.openai_api_key:
    set_default_openai_key(settings.openai_api_key)


@function_tool
async def generate_meeting_details(email_context: str, sender_email: str, staff_availability: str = "", staff_timezone: str = "UTC") -> MeetingDetails:
    """Generate structured meeting details from email context.
    
    Args:
        email_context: The email content and conversation history
        sender_email: Email address of the sender
        staff_availability: Staff member's availability in JSON string format
        staff_timezone: Staff member's timezone
        
    Returns:
        MeetingDetails with subject, start_time, duration_minutes, description
    """
    
    # Create agent for meeting details generation
    agent = Agent(
        name="MeetingDetailsGenerator",
        instructions=f"""
You are a meeting coordinator. Generate meeting details from email context.

TODAY'S DATE: {datetime.now().strftime('%Y-%m-%d')}
STAFF TIMEZONE: {staff_timezone}
STAFF AVAILABILITY: {staff_availability}

Generate professional meeting details:
- Subject: Professional meeting title with company name
- Start Time: Mathematically align the proposed meeting time with the provided STAFF AVAILABILITY and STAFF TIMEZONE. You must ONLY pick a time slot that strictly fits within the staff's specified weekly hours. Format: YYYY-MM-DD HH:MM
- Duration: 15 min (quick questions), 30 min (general), 60 min (demos/detailed). The duration must fit within the chosen availability block.
- Description: Brief context from email conversation
- Conversation Summary: Concise 2-3 sentence summary of email thread for staff context

Provide a chain of thought rationale explaining how you aligned the proposed time with the staff's exact availability JSON and timezone before returning the final meeting details.
""",
        model_settings=ModelSettings(
            model=settings.response_model,
            temperature=0.3,
            max_tokens=400
        ),
        output_type=MeetingDetails
    )
    
    # Extract company name from email
    company_name = sender_email.split('@')[1].split('.')[0].title() if '@' in sender_email else "Client"
    
    try:
        result = await Runner.run(agent, email_context)
        meeting_details = result.final_output
        logger.info(f"Generated meeting details for {sender_email}: {meeting_details.subject}")
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