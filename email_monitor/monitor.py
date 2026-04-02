"""Email monitoring system orchestrator."""

import logging
from typing import Dict, Any
from agentmail import AgentMail

from config import settings
from schema import EmailActionResult
from .intent_extractor import IntentExtractorAgent
from .email_response import EmailResponseAgent

logger = logging.getLogger(__name__)


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