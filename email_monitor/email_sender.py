"""Email sender agent - intelligent agent with access to email and meeting tools."""

import logging
from typing import Dict, Any

from config.logging import setup_logging
from agents import Agent, ModelSettings, Runner, set_default_openai_key
from tools import (
    send_reply_email, 
    create_google_meeting,
    get_staff_tool,
    notify_staff_about_meeting,
    generate_meeting_details
)
from schema import EmailActionResult
from config import settings

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Set OpenAI API key for agents library
if settings.openai_api_key:
    set_default_openai_key(settings.openai_api_key)

logger = logging.getLogger(__name__)


class EmailSenderAgent:
    """Intelligent agent that can send emails, create meetings, and take other actions."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailSenderAgent",
            model=settings.response_model,
            instructions="""
You are an email and meeting coordination agent. Execute actions based on the approved response.

Available tools:
- send_reply_email: Send email responses  
- generate_meeting_details: Create meeting information
- get_staff_tool: Get staff member details
- create_google_meeting: Create calendar events with attendees
- notify_staff_about_meeting: Email staff about meetings

WORKFLOW:
1. Always send the approved response to the client using send_reply_email
2. If response mentions meeting/call/appointment:
   a) Generate meeting details with generate_meeting_details
   b) Get staff details (name + email) with get_staff_tool  
   c) Create meeting with create_google_meeting (2 attendees: staff + client)
   d) Notify staff with notify_staff_about_meeting (pass MeetingDetails with conversation summary)

Execute tools in sequence for meeting scenarios.
""",
            tools=[
                send_reply_email, 
                generate_meeting_details,
                create_google_meeting,
                get_staff_tool,
                notify_staff_about_meeting
            ],
            model_settings=ModelSettings(
                temperature=0.3,  # Lower temperature for precise execution
                max_tokens=500
            )
        )
    
    async def execute_action(self, approved_response: str, email_data: Dict[str, Any]) -> EmailActionResult:
        """Execute the appropriate action (send email, create meeting, etc.) based on the approved response."""
        sender_email = email_data.get('from_', [''])[0]
        message_id = email_data.get('id')  # Original message ID for proper replies
        thread_id = email_data.get('thread_id')
        subject = email_data.get('subject', '')
        
        # Build context for the agent 
        intent_data = email_data.get('intent', {})
        conversation_history = email_data.get('conversation_history', '')
        email_content = email_data.get('text', '') or email_data.get('preview', '')
        
        context = f"""
APPROVED RESPONSE: {approved_response}

EMAIL DETAILS:
- To: {sender_email}
- Reply to Message ID: {message_id}
- Subject: {subject}  
- Thread: {thread_id}
- Intent: {intent_data.get('intent', 'unknown')} ({intent_data.get('confidence', 0.0)})
- Content: {email_content}
- History: {conversation_history or 'None'}

IMPORTANT: Use send_reply_email with message_id={message_id} for proper threading.
Execute appropriate tools based on response content.
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