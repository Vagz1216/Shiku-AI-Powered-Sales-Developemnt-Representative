"""Google Calendar meeting creation tool using Composio."""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from agents import function_tool
from config import settings
from schema import MeetingResult

logger = logging.getLogger(__name__)


@function_tool
def create_google_meeting(
    attendees: list[str],
    subject: str,
    start_time: str,
    duration_minutes: int = 30,
    description: str = ""
) -> MeetingResult:
    """Create a Google Calendar meeting with attendees.
    
    Args:
        attendees: List of email addresses to invite to the meeting
        subject: Meeting subject/title
        start_time: Meeting start time (e.g., "2026-04-02 14:00")
        duration_minutes: Meeting duration in minutes (default: 30)
        description: Optional meeting description
    
    Returns:
        MeetingResult with success status and meeting details
    """
    try:
        # Validate attendees list
        if not attendees or not isinstance(attendees, list):
            return MeetingResult(
                success=False,
                error="At least one attendee email is required"
            )
        
        if len(attendees) == 0:
            return MeetingResult(
                success=False,
                error="At least one attendee email is required"
            )
        
        # Check if Composio is configured
        if not settings.composio_api_key:
            logger.error("Composio API key not configured")
            return MeetingResult(
                success=False,
                error="Composio API key not configured. Please set COMPOSIO_API_KEY in .env file."
            )

        # Import Composio modules
        try:
            from composio import Composio
        except ImportError as e:
            logger.error(f"Composio packages not installed: {e}")
            return MeetingResult(
                success=False,
                error="Composio packages not installed. Run: pip install composio-openai-agents"
            )

        # Initialize Composio with OpenAI provider
        composio = Composio(api_key=settings.composio_api_key)
        
        # Create a session for the email agent
        session = composio.create(user_id="email-agent-user")
        
        # Parse and validate datetime
        try:
            start_dt = datetime.fromisoformat(start_time.replace('T', ' '))
        except ValueError:
            # Try parsing different formats
            try:
                start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            except ValueError:
                return MeetingResult(
                    success=False,
                    error="Invalid datetime format. Use 'YYYY-MM-DD HH:MM' or ISO format."
                )
        
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        # Execute the calendar event creation using Composio session
        result = session.execute(
            tool_slug="GOOGLECALENDAR_CREATE_EVENT",
            arguments={
                "title": subject,
                "description": description,
                "start_time": start_dt.isoformat() + "Z",
                "end_time": end_dt.isoformat() + "Z", 
                "attendees": attendees,
                "create_meet_link": True
            }
        )
        
        if result.data and not result.error:
            event_result = result.data
            return MeetingResult(
                success=True,
                meeting_link=event_result.get("hangoutLink") or event_result.get("htmlLink"),
                event_id=event_result.get("id")
            )
        else:
            error_msg = result.error or "Unknown error creating calendar event"
            logger.error(f"Calendar event creation failed: {error_msg}")
            return MeetingResult(
                success=False,
                error=f"Failed to create calendar event: {error_msg}"
            )
        
    except Exception as e:
        logger.error(f"Error creating Google Calendar meeting: {e}")
        return MeetingResult(
            success=False,
            error=str(e)
        )