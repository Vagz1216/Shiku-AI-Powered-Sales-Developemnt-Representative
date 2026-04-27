"""Google Calendar meeting creation tool using proper Composio OpenAI Agents SDK pattern."""

import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from config.logging import setup_logging
from agents import function_tool
from config import settings
from schema import MeetingResult
from utils.model_fallback import run_agent_with_fallback

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

        os.environ["COMPOSIO_API_KEY"] = settings.composio_api_key
        if settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key

        # Initialize Composio with OpenAI Agents provider (proper pattern)
        composio = Composio(provider=OpenAIAgentsProvider())
        
        # Create session using consistent user ID for OAuth connections
        # Fallback to a default string if None to prevent API validation errors
        composio_user = settings.composio_user_id or "default_sdr_user"
        session = composio.create(user_id=composio_user)
        
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
        
        calendar_instructions = f"""
You are a Google Calendar assistant. Use the available Google Calendar tools to create meetings.

TODAY'S DATE: {datetime.now().strftime('%Y-%m-%d')}

When creating meetings:
- Set professional titles
- Include meeting descriptions with context
- Add Google Meet links when possible  
- Use exact attendee email addresses provided
- CRITICAL: You MUST explicitly enable email notifications/invitations for attendees so they receive the native Google Calendar invite (e.g. set sendUpdates='all').
- Return success confirmation with meeting details

For this request:
- Title: {subject}
- Attendees: {', '.join(attendees)}
- DateTime: {meeting_time}
- Duration: {duration_minutes} minutes
- Description: {description}
"""
        calendar_prompt = f"""Create a Google Calendar meeting with these exact details:
- Title: {subject}
- Attendees: {', '.join(attendees)}
- Date/Time: {meeting_time} 
- Duration: {duration_minutes} minutes
- Description: {description}
- Include Google Meet link
- CRITICAL: Ensure you explicitly send calendar invites to the attendees (sendUpdates='all')!

Create the meeting and return the meeting link and event ID.
"""
        try:
            result, provider = await run_agent_with_fallback(
                name="Google Calendar Agent",
                instructions=calendar_instructions,
                prompt=calendar_prompt,
                tools=tools,
            )
        except RuntimeError as e:
            logger.error(f"All providers failed for Google Calendar Agent: {e}")
            return MeetingResult(
                success=False,
                error=f"All AI providers failed for meeting creation. {str(e)[:200]}"
            )
        
        logger.info(f"Agent result: {result.final_output}")
        
        # Check if meeting was created successfully
        if "created" in str(result.final_output).lower() or "scheduled" in str(result.final_output).lower() or "success" in str(result.final_output).lower():
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
                    
            # Try to extract event ID (sometimes returned in the output as Event ID: xxx)
            import re
            event_match = re.search(r'(?i)event\s*id:\s*([a-zA-Z0-9_]+)', output_text)
            if event_match:
                event_id = event_match.group(1)
            
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

@function_tool
async def get_upcoming_free_slots(staff_email: str = None, days_ahead: int = 5, duration_minutes: int = 30, meeting_delay_days: int = 1) -> str:
    """Get a list of actual free time slots from the staff member's live Google Calendar.
    
    Args:
        staff_email: Staff member's email address.
        days_ahead: Number of days to look ahead (default: 5).
        duration_minutes: The required meeting duration in minutes (default: 30).
        meeting_delay_days: Number of days to wait before scheduling the meeting (default: 1).
        
    Returns:
        String containing a list of available time slots.
    """
    try:
        if settings.use_dummy_data and staff_email:
            # Use dummy data for capstone demo
            from utils.db_connection import get_conn
            import json
            conn = get_conn()
            cur = conn.execute("SELECT dummy_slots FROM staff WHERE email = ?", (staff_email,))
            row = cur.fetchone()
            if row and row['dummy_slots']:
                try:
                    slots = json.loads(row['dummy_slots'])
                    return f"Available slots (Dummy Data): {', '.join(slots)}"
                except Exception as e:
                    pass

        if not settings.composio_api_key or not settings.openai_api_key:
            return "Cannot check availability: API keys missing."

        try:
            from composio import Composio
            from composio_openai_agents import OpenAIAgentsProvider
        except ImportError:
            return "Composio packages not installed."

        os.environ["COMPOSIO_API_KEY"] = settings.composio_api_key
        if settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key

        composio = Composio(provider=OpenAIAgentsProvider())
        composio_user = settings.composio_user_id or "default_sdr_user"
        session = composio.create(user_id=composio_user)
        tools = session.tools()

        now = datetime.now()
        # Start looking for slots `meeting_delay_days` from now
        start_date = now + timedelta(days=meeting_delay_days)
        # Look within a window (e.g., 5 days from the start date)
        end_date = start_date + timedelta(days=days_ahead)

        avail_instructions = f"""
You are a Google Calendar assistant. Your task is to find available time slots on the user's primary calendar.
Current time: {now.strftime('%Y-%m-%d %H:%M')}
Search Window Start: {start_date.strftime('%Y-%m-%d 09:00')}
Search Window End: {end_date.strftime('%Y-%m-%d 17:00')}

1. Check the user's calendar events specifically between the Search Window Start and End.
2. Identify 3 to 5 completely free {duration_minutes}-minute slots during standard business hours (9 AM - 5 PM, Monday to Friday).
3. Prioritize slots on {start_date.strftime('%Y-%m-%d')}. If that day is full or it is a weekend, move to the next business day.
4. Return ONLY a bulleted list of the available slots in 'YYYY-MM-DD HH:MM' format.
"""
        try:
            result, provider = await run_agent_with_fallback(
                name="Google Calendar Availability Checker",
                instructions=avail_instructions,
                prompt=f"Find {duration_minutes}-minute free slots in the next {days_ahead} days.",
                tools=tools,
            )
            return str(result.final_output)
        except RuntimeError as e:
            logger.error(f"All providers failed for availability check: {e}")
            return f"Cannot check availability: all AI providers failed."

    except Exception as e:
        if "429" in str(e) or "insufficient_quota" in str(e):
            logger.error(f"OpenAI Quota Error in free slots check: {e}")
            return "Cannot check availability: OpenAI API Quota Exceeded."
        
        logger.error(f"Error getting calendar free slots: {e}")
        return f"Error getting availability: {str(e)}"
