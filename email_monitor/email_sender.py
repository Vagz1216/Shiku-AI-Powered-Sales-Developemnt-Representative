"""Email sender agent - intelligent agent with access to email and meeting tools."""

import logging
from typing import Dict, Any

from agents import Agent, ModelSettings, Runner
from tools import send_reply_email
from tools.google_calendar import create_google_meeting
from schema import EmailActionResult
from config import settings

logger = logging.getLogger(__name__)


class EmailSenderAgent:
    """Intelligent agent that can send emails, create meetings, and take other actions."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailSenderAgent",
            instructions="""
You are a professional email and meeting agent. Based on the approved response and email context, take appropriate actions.

Your available actions:
- Send email replies using send_reply_email tool  
- Create Google Calendar meetings using create_google_meeting tool

Guidelines:
1. Always send the approved response using send_reply_email tool
2. If the response mentions scheduling a meeting or call, also use create_google_meeting tool to create the calendar event
3. For meetings, include all attendees in a list format, suggest reasonable times (business hours, 30-60 minutes duration)
4. When creating meetings, always include the original sender's email in the attendees list

Examples:
- Simple reply: Just use send_reply_email
- Reply mentioning "let's schedule a call": Use both send_reply_email AND create_google_meeting
- Meeting request: Use both tools to reply and schedule

Always execute the appropriate combination of tools based on the approved response content.
""",
            tools=[send_reply_email, create_google_meeting],
            model_settings=ModelSettings(
                model=settings.response_model,
                temperature=0.3,  # Lower temperature for precise execution
                max_tokens=500
            )
        )
    
    async def execute_action(self, approved_response: str, email_data: Dict[str, Any]) -> EmailActionResult:
        """Execute the appropriate action (send email, create meeting, etc.) based on the approved response."""
        sender_email = email_data.get('from_', [''])[0]
        thread_id = email_data.get('thread_id')
        subject = email_data.get('subject', '')
        
        # Build context for the agent
        context = f"""
The following response has been approved and should be sent:

APPROVED RESPONSE:
{approved_response}

EMAIL CONTEXT:
- From: {sender_email}
- Subject: {subject}  
- Thread ID: {thread_id}

INSTRUCTIONS:
1. Always send the approved response using send_reply_email tool
2. If the response mentions scheduling a meeting/call, also use schedule_meeting tool
3. For meetings, suggest reasonable business hours (e.g., "2026-04-15 14:00" for 2 PM)
4. Use 30-60 minute durations for most meetings

Execute the appropriate combination of tools based on the approved response content.
"""
        
        try:
            result = await Runner.run(self.agent, context)
            
            logger.info(f"Email action executed for {sender_email}")
            return EmailActionResult(
                action_taken="sent",
                success=True,
                message_id=None,  # Will be populated by the tool
                thread_id=thread_id
            )
            
        except Exception as e:
            logger.error(f"Error executing email action: {e}")
            return EmailActionResult(
                action_taken="error",
                success=False,
                error=str(e)
            )