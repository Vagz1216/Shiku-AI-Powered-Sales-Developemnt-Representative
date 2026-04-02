"""Email response generation agent."""

import logging
from typing import Dict, Any

from agents import Agent, ModelSettings, Runner
from tools import send_reply_email
from schema import EmailIntent, EmailActionResult
from config import settings

logger = logging.getLogger(__name__)


class EmailResponseAgent:
    """Agent that crafts replies based on intent analysis."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailResponseAgent",
            instructions="""
You are a professional business development assistant responding to client inquiries.

Your PRIMARY goal is to schedule meetings/calls with potential clients.

Response guidelines by intent:
- meeting_request: Confirm availability and provide scheduling options
- question: Answer briefly, then suggest meeting for detailed discussion
- interest: Build value and urgency, push for meeting
- opt_out: Respect request, confirm removal
- neutral: Engage professionally, steer toward meeting if appropriate
- bounce/spam: No response needed

Use email conversation history as context for personalized responses.
Keep responses concise (2-3 paragraphs max).
Always use send_reply_email function to send your response.
""",
            tools=[send_reply_email],
            model_settings=ModelSettings(
                model=settings.response_model,
                temperature=settings.response_temperature,
                max_tokens=settings.response_max_tokens
            )
        )
    
    async def generate_response(self, email_data: Dict[str, Any], intent: EmailIntent, conversation_history: str = "") -> EmailActionResult:
        """Generate and send appropriate response based on intent."""
        sender_email = email_data.get('from_', [''])[0]
        subject = email_data.get('subject', '')
        content = email_data.get('text', '') or email_data.get('preview', '')
        thread_id = email_data.get('thread_id')
        
        # Skip responses for certain intents
        if intent.intent in ['bounce', 'spam'] or intent.confidence < 0.3:
            return EmailActionResult(
                action_taken="skipped",
                success=True,
                error=f"Intent: {intent.intent} (confidence: {intent.confidence})"
            )
        
        # Build context for response
        context = f"""
Incoming email analysis:
- From: {sender_email}
- Subject: {subject}
- Intent: {intent.intent} (confidence: {intent.confidence})
- Content: {content}

Conversation history:
{conversation_history or "No previous conversation."}

Generate appropriate response and send using send_reply_email function.
"""
        
        try:
            result = await Runner.run(self.agent, context)
            
            return EmailActionResult(
                action_taken="replied",
                success=True,
                message_id=None,  # Would be populated by send_reply_email tool
                thread_id=thread_id
            )
            
        except Exception as e:
            logger.error(f"Failed to generate response: {e}")
            return EmailActionResult(
                action_taken="error",
                success=False,
                error=str(e)
            )