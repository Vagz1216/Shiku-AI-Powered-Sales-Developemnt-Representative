"""Google Calendar meeting creation tool using proper Composio OpenAI Agents SDK pattern."""

import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from config.logging import setup_logging
from agents import function_tool, Agent, Runner
from config import settings
from schema import MeetingResult

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


@function_tool
async def create_google_meeting(
    attendees: list[str],
    subject: str,
    start_time: str,
    duration_minutes: int = 30,
    description: str = ""
) -> MeetingResult:
    """Create a Google Calendar meeting with attendees using proper Composio integration.
    
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
        
        if not settings.openai_api_key:
            logger.error("OpenAI API key not configured")
            return MeetingResult(
                success=False,
                error="OpenAI API key not configured. Please set OPENAI_API_KEY in .env file."
            )

        # Import Composio modules with proper OpenAI Agents SDK pattern
        try:
            from composio import Composio
            from composio_openai_agents import OpenAIAgentsProvider
        except ImportError as e:
            logger.error(f"Composio packages not installed: {e}")
            return MeetingResult(
                success=False,
                error="Composio packages not installed. Run: uv add composio-openai-agents"
            )

        # Set environment variables as required by the providers
        os.environ["COMPOSIO_API_KEY"] = settings.composio_api_key
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key

        # Initialize Composio with OpenAI Agents provider (proper pattern)
        composio = Composio(provider=OpenAIAgentsProvider())
        
        # Create session using consistent user ID for OAuth connections
        session = composio.create(user_id=settings.composio_user_id)
        
        # Get tools from session (this was the missing piece!)
        tools = session.tools()
        
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
        meeting_time = start_dt.strftime('%Y-%m-%d at %I:%M %p')
        
        # Create agent with tools from session (proper pattern)
        agent = Agent(
            name="Google Calendar Agent",
            instructions=f"""
You are a Google Calendar assistant. Use the available Google Calendar tools to create meetings.

TODAY'S DATE: {datetime.now().strftime('%Y-%m-%d')}

When creating meetings:
- Set professional titles
- Include meeting descriptions with context
- Add Google Meet links when possible  
- Use exact attendee email addresses provided
- Return success confirmation with meeting details

For this request:
- Title: {subject}
- Attendees: {', '.join(attendees)}
- DateTime: {meeting_time}
- Duration: {duration_minutes} minutes
- Description: {description}
""",
            tools=tools,  # Use tools from session
            model="gpt-4o-mini"  # Use consistent model
        )
        
        # Execute meeting creation using the agent (proper pattern)
        result = await Runner.run(
            starting_agent=agent,
            input=f"""Create a Google Calendar meeting with these exact details:
- Title: {subject}
- Attendees: {', '.join(attendees)}
- Date/Time: {meeting_time} 
- Duration: {duration_minutes} minutes
- Description: {description}
- Include Google Meet link

Create the meeting and return the meeting link and event ID.
"""
        )
        
        logger.info(f"Agent result: {result.final_output}")
        
        # Check if meeting was created successfully
        if "created" in str(result.final_output).lower() or "scheduled" in str(result.final_output).lower():
            # Extract meeting link if present in the output
            output_text = str(result.final_output)
            meeting_link = None
            event_id = None
            
            # Try to extract meeting link from the output
            if "meet.google.com" in output_text:
                import re
                meet_match = re.search(r'https://meet\.google\.com/[a-zA-Z0-9\-]+', output_text)
                if meet_match:
                    meeting_link = meet_match.group()
            elif "calendar.google.com" in output_text:
                import re
                cal_match = re.search(r'https://calendar\.google\.com/[^\s]+', output_text)
                if cal_match:
                    meeting_link = cal_match.group()
            
            return MeetingResult(
                success=True,
                meeting_link=meeting_link,
                event_id=event_id
            )
        else:
            # Check if it's an authentication issue
            if "connect" in str(result.final_output).lower() and "google" in str(result.final_output).lower():
                return MeetingResult(
                    success=False,
                    error=f"Google Calendar not connected. Please complete OAuth: {result.final_output}"
                )
            else:
                return MeetingResult(
                    success=False,
                    error=f"Meeting creation failed: {result.final_output}"
                )
        
    except Exception as e:
        logger.error(f"Error creating Google Calendar meeting: {e}")
        return MeetingResult(
            success=False,
            error=str(e)
        )