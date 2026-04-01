"""Email sender agent - intelligent agent with access to email and meeting tools."""

import logging
from typing import Dict, Any

from agents import Agent, ModelSettings, Runner
from tools import send_reply_email
from schema import EmailActionResult
from config import settings

logger = logging.getLogger(__name__)


class EmailSenderAgent:
    """Intelligent agent that can send emails, create meetings, and take other actions."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailSenderAgent",
            instructions="""
You are a professional email handling agent. Based on the approved response and email context, take appropriate actions.

Your available actions:
- Send email replies using send_reply_email tool
- (Future: Create calendar meetings, send notifications, etc.)

Always use the exact approved response text provided - do not modify it.
For email replies, use the send_reply_email tool with appropriate parameters.

If the email requires scheduling a meeting, mention this in your response for future tool integration.
""",
            tools=[send_reply_email],
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

Execute the appropriate action to send this approved response. Use send_reply_email tool to reply to this email.
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