"""Email monitoring agents using OpenAI Agents SDK."""

from typing import Dict, Any
import logging
from agentmail import AgentMail

from config import settings
from agents import Agent, ModelSettings, Runner, function_tool
from tools import send_reply_email
from schema import EmailIntent, EmailActionResult

logger = logging.getLogger(__name__)


class IntentExtractorAgent:
    """Agent that extracts intent from email content."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailIntentExtractor",
            instructions="""
Analyze email content and classify the sender's intent with confidence.

Classify into one of these intents:
- meeting_request: Explicitly asking to schedule a meeting/call
- question: Has specific questions about services
- interest: Expressing interest but no specific questions
- opt_out: Requesting to be removed or unsubscribed
- neutral: General inquiry or acknowledgment
- bounce: Automated bounce/out-of-office message
- spam: Spam or irrelevant content

Provide confidence score 0.0-1.0 based on clarity of intent.
Return only the structured response, no additional text.
""",
            model_settings=ModelSettings(
                model="gpt-4",
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=100
            )
        )
    
    async def extract_intent(self, email_content: str, subject: str = "") -> EmailIntent:
        """Extract intent from email content."""
        prompt = f"""
Subject: {subject}
Content: {email_content}

Respond with JSON only:
{{
  "intent": "meeting_request|question|opt_out|interest|neutral|bounce|spam",
  "confidence": 0.0-1.0
}}
"""
        
        result = await Runner.run(self.agent, prompt)
        
        # Parse the JSON response
        try:
            import json
            response_data = json.loads(result.final_output)
            return EmailIntent(**response_data)
        except Exception as e:
            logger.warning(f"Failed to parse intent response: {e}")
            return EmailIntent(intent="neutral", confidence=0.5)


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
                model="gpt-4",
                temperature=0.7,
                max_tokens=800
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
    
class EmailMonitorSystem:
    """Complete email monitoring system with intent analysis."""
    
    def __init__(self):
        self.intent_extractor = IntentExtractorAgent()
        self.response_agent = EmailResponseAgent()
        self._agentmail_client = None
    
    @property
    def agentmail_client(self):
        """Lazy-loaded AgentMail client."""
        if self._agentmail_client is None:
            self._agentmail_client = AgentMail(api_key=settings.agentmail_api_key)
        return self._agentmail_client
    
    async def fetch_conversation_history(self, thread_id: str, limit: int = 10) -> str:
        """Fetch previous messages from email thread for context.
        
        Args:
            thread_id: Email thread identifier
            limit: Maximum number of previous messages to fetch
            
        Returns:
            Formatted conversation history string
        """
        if not thread_id:
            return "No thread ID available."
            
        try:
            # Get thread messages from AgentMail
            response = self.agentmail_client.inboxes.threads.list_messages(
                inbox_id=settings.agentmail_inbox_id,
                thread_id=thread_id,
                limit=limit,
                order="asc"  # Oldest first for chronological order
            )
            
            if not response.messages:
                return "No previous messages in thread."
            
            # Format conversation history
            history_parts = []
            for msg in response.messages:
                sender = msg.from_[0] if msg.from_ else "Unknown"
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else "Unknown time"
                content = msg.text or msg.preview or "[No content]"
                
                # Truncate very long messages
                if len(content) > 500:
                    content = content[:500] + "... [truncated]"
                
                history_parts.append(
                    f"[{timestamp}] {sender}:\n{content}\n"
                )
            
            return "\n---\n".join(history_parts)
            
        except Exception as e:
            logger.warning(f"Failed to fetch conversation history for thread {thread_id}: {e}")
            return f"Unable to fetch conversation history: {str(e)}"
    
    async def process_incoming_email(self, email_data: Dict[str, Any]) -> EmailActionResult:
        """Process incoming email with intent analysis and appropriate response."""
        try:
            sender_email = email_data.get('from_', [''])[0]
            subject = email_data.get('subject', '')
            content = email_data.get('text', '') or email_data.get('preview', '')
            thread_id = email_data.get('thread_id')
            
            logger.info(f"Processing email from {sender_email}: {subject}")
            
            # Extract intent first
            intent = await self.intent_extractor.extract_intent(content, subject)
            logger.info(f"Extracted intent: {intent.intent} (confidence: {intent.confidence})")
            
            # Fetch conversation history from email thread
            conversation_history = await self.fetch_conversation_history(thread_id) if thread_id else "No thread ID - likely first message."
            logger.debug(f"Conversation history length: {len(conversation_history)} chars")
            
            # Generate response based on intent
            result = await self.response_agent.generate_response(
                email_data, intent, conversation_history
            )
            
            logger.info(f"Action taken: {result.action_taken} (success: {result.success})")
            return result
            
        except Exception as e:
            logger.error(f"Error processing email: {e}")
            return EmailActionResult(
                action_taken="error",
                success=False,
                error=str(e)
            )


# Global system instance
email_monitor = EmailMonitorSystem()