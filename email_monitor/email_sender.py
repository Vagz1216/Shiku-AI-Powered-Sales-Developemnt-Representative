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
You are an email and meeting coordination agent. Execute actions based on the approved response and classified intent.

Available tools:
- send_reply_email: Send email responses  
- generate_meeting_details: Create meeting information
- get_staff_tool: Get staff member details
- create_google_meeting: Create calendar events with attendees
- notify_staff_about_meeting: Email staff about meetings

CRITICAL WORKFLOW RULES:
1. ALWAYS send the approved response to the client using send_reply_email first
2. ONLY create meetings if the classified intent is "meeting_request" - DO NOT create meetings for other intents like "question", "interest", "neutral", etc.
3. For meeting_request intents ONLY:
   a) Get staff details (including name, email, availability, and timezone) with get_staff_tool  
   b) Generate meeting details with generate_meeting_details, passing the staff's availability and timezone
   c) Create meeting with create_google_meeting (2 attendees: staff + client)
   d) Notify staff with notify_staff_about_meeting (pass MeetingDetails with conversation summary)

INTENT-BASED ACTIONS:
- meeting_request: Send response + create meeting + notify staff
- question: Send response only (NO meeting creation)
- interest: Send response only (NO meeting creation)  
- neutral: Send response only (NO meeting creation)
- opt_out: Send response only (NO meeting creation)
- spam/bounce: Send response only (NO meeting creation)

Never create meetings unless the intent is explicitly "meeting_request".
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
        # Use clean metadata fields
        sender_email = email_data.get('sender_email', '')
        sender_name = email_data.get('sender_name', 'Unknown')
        message_id = email_data.get('message_id')  # Use extracted message_id
        thread_id = email_data.get('thread_id')
        subject = email_data.get('subject', '')
        
        # Debug logging for message_id propagation  
        logger.info(f"EmailSenderAgent - sender: {sender_name} ({sender_email}), message_id: {message_id}, thread_id: {thread_id}")
        
        # Build context for the agent 
        intent_data = email_data.get('intent', {})
        conversation_history = email_data.get('conversation_history', '')
        email_content = email_data.get('content', '')
        
        context = f"""RESPONSE: {approved_response}

EMAIL: From {sender_email} ({sender_name}) | Subject: {subject} | MSG_ID: {message_id} | Thread: {thread_id}
INTENT: {intent_data.get('intent', 'unknown')} (confidence: {intent_data.get('confidence', 0.0)})

CONTENT: {email_content}
HISTORY: {conversation_history if conversation_history else 'None'}

ACTIONS:
1. Send reply using message_id={message_id}
2. Meeting: {'YES - create meeting' if intent_data.get('intent') == 'meeting_request' else 'NO - response only'}
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