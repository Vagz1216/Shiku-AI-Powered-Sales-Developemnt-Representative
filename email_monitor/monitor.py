"""Email monitoring system orchestrator."""

import logging
import re
from typing import Dict, Any
from agentmail import AgentMail

from config.logging import setup_logging
from config import settings
from schema import EmailActionResult
from agents import trace, gen_trace_id
from .intent_extractor import IntentExtractorAgent
from .email_response import EmailResponseAgent
from .response_evaluator import ResponseEvaluator
from .email_sender import EmailSenderAgent
from .security import validate_email_security
from .data_utils import get_email_metadata

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


class EmailMonitorSystem:
    """Complete email monitoring system with intent analysis."""
    
    def __init__(self):
        self.intent_extractor = IntentExtractorAgent()
        self.response_agent = EmailResponseAgent()
        self.response_evaluator = ResponseEvaluator()
        self.email_sender = EmailSenderAgent()
        self._agentmail_client = None
    
    @property
    def agentmail_client(self):
        """Lazy-loaded AgentMail client."""
        if self._agentmail_client is None:
            self._agentmail_client = AgentMail(api_key=settings.agentmail_api_key)
        return self._agentmail_client
    
    async def fetch_conversation_history(self, thread_id: str, current_message_id: str = None, limit: int = 20) -> str:
        """Fetch thread messages using proper AgentMail API with improved message handling.
        
        Args:
            thread_id: Email thread identifier
            current_message_id: ID of current message to exclude from history
            limit: Maximum number of messages to include (increased from 10 to 20)
            
        Returns:
            Formatted conversation history string (excluding current message)
        """
        if not thread_id:
            return "No thread ID available."
            
        try:
            # Get full thread with all messages using efficient API
            thread = self.agentmail_client.threads.get(thread_id=thread_id)
            
            if not hasattr(thread, 'messages') or not thread.messages:
                return "No messages found in thread."
            
            # Sort by creation time and limit for context control
            messages = sorted(thread.messages, key=lambda x: getattr(x, 'created_at', 0))
            
            # Exclude the current message from history to avoid duplication
            if current_message_id:
                messages = [msg for msg in messages if getattr(msg, 'message_id', None) != current_message_id]
            
            messages = messages[:limit]
            
            # Format conversation history with improved message handling
            history_parts = []
            for msg in messages:
                # Handle sender extraction - use full name, not just first letter
                sender_raw = msg.from_[0] if msg.from_ else "Unknown"
                if isinstance(sender_raw, str) and '<' in sender_raw:
                    # Extract full name from "Name <email>" format
                    name_match = re.search(r'^([^<]+)\s*<', sender_raw)
                    if name_match:
                        sender = name_match.group(1).strip()
                        # Clean up quotes and artifacts
                        sender = re.sub(r'["\'\\\/]', '', sender)
                    else:
                        sender = sender_raw.split('@')[0] if '@' in sender_raw else "Unknown"
                else:
                    sender = str(sender_raw) if sender_raw else "Unknown"
                
                # Format timestamp  
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else "Unknown time"
                
                # Use extracted_text for clean content without quoted history, fallback to text/preview
                content = msg.extracted_text or msg.text or msg.preview or "[No content]"
                
                # Increase content limit and provide smarter truncation
                if len(content) > 1000:  # Increased from 300 to 1000
                    # Try to truncate at sentence boundary
                    truncated = content[:1000]
                    last_sentence = max(
                        truncated.rfind('.'),
                        truncated.rfind('!'), 
                        truncated.rfind('?')
                    )
                    if last_sentence > 1000: 
                        content = content[:last_sentence + 1] + " [truncated]"
                    else:
                        content = content[:1000] + "... [truncated]"
                
                history_parts.append(
                    f"[{timestamp}] {sender}:\n{content}\n"
                )
            
            return "\n---\n".join(history_parts)
            
        except Exception as e:
            logger.warning(f"Failed to fetch thread {thread_id}: {e}")
            return f"Unable to fetch conversation history: {str(e)}"    


    async def process_incoming_email(self, email_data: Dict[str, Any]) -> EmailActionResult:
        """Complete email processing pipeline with retry logic and meeting scheduling."""
        # Extract all email metadata in one efficient call
        metadata = get_email_metadata(email_data)
        
        # Create a single trace for the entire email processing pipeline  
        trace_id = gen_trace_id()
        
        with trace(
            workflow_name="Email Processing Pipeline",
            trace_id=trace_id,
            metadata={"sender": metadata['sender_email'], "subject": metadata['subject']}
        ):
            try:
                logger.info(f"Processing email from {metadata['sender_email']}: {metadata['subject']} (msg_id: {metadata['message_id']})")
                
                # Security validation - check before any LLM processing
                is_valid, rejection_reason = validate_email_security(
                    metadata['content'], metadata['sender_email'], metadata['subject']
                )
                if not is_valid:
                    logger.warning(f"Email validation failed from {metadata['sender_email']}: {rejection_reason}")
                    return EmailActionResult(
                        action_taken="rejected_security",
                        success=True,  # Successfully rejected for security
                        error=f"Email rejected for security: {rejection_reason}",
                        message_id=metadata['message_id']
                    )
                
                logger.info(f"Email security validation passed for {metadata['sender_email']}")
                
                # Llama Guard Validation - Check for prompt injection or malicious content
                from utils.llama_guard import check_email_safety
                safety_check = await check_email_safety(metadata['content'], metadata['subject'])
                if not safety_check.is_safe:
                    logger.warning(f"Llama Guard rejected email from {metadata['sender_email']}: {safety_check.violation_reason}")
                    return EmailActionResult(
                        action_taken="rejected_safety",
                        success=True,
                        error=f"Email rejected by Llama Guard: {safety_check.violation_reason}",
                        message_id=metadata['message_id']
                    )
                
                logger.info(f"Llama Guard safety check passed for {metadata['sender_email']}")
                
                # Step 1: Extract intent
                intent = await self.intent_extractor.extract_intent(metadata['content'], metadata['subject'])
                logger.info(f"Intent: {intent.intent} (confidence: {intent.confidence})")
                
                # Step 2: Get conversation context (excluding current message to avoid duplication)
                conversation_history = await self.fetch_conversation_history(
                    metadata['thread_id'], metadata['message_id']
                ) if metadata['thread_id'] else ""
                
                # Step 3: Generate response with retry logic
                max_retries = 2
                retry_count = 0
                
                while retry_count <= max_retries:
                    # Generate response with clean extracted data instead of raw webhook payload
                    response_result = await self.response_agent.generate_response(
                        metadata, intent, conversation_history
                    )
                    
                    # Handle skipped responses
                    if response_result.action == "skipped":
                        return EmailActionResult(
                            action_taken="skipped",
                            success=True,
                            error=response_result.reason
                        )
                    
                    if response_result.action != "generated":
                        return EmailActionResult(
                            action_taken="error",
                            success=False,
                            error=response_result.reason or "Failed to generate response"
                        )
                    
                    # Step 4: Evaluate response
                    response_text = response_result.response_text
                    evaluation_context = {**metadata, "intent": intent.intent}
                    
                    evaluation = await self.response_evaluator.evaluate_response(
                        response_text, evaluation_context
                    )
                    
                    # If approved, proceed to sending
                    if evaluation.approved:
                        logger.info(f"Response approved on attempt {retry_count + 1}")
                        break
                    
                    # If not approved and we have retries left
                    retry_count += 1
                    if retry_count <= max_retries:
                        logger.warning(f"Response rejected (attempt {retry_count}): {evaluation.reason}. Retrying...")
                        # Add feedback to context for next attempt
                        conversation_history += f"\n\nPrevious response was rejected: {evaluation.reason}. Please improve the response."
                    else:
                        logger.error(f"Response rejected after {max_retries + 1} attempts: {evaluation.reason}")
                        return EmailActionResult(
                            action_taken="rejected",
                            success=False,
                            error=f"Evaluator rejected after {max_retries + 1} attempts: {evaluation.reason}"
                        )
                
                # Step 4: Send email with clean extracted context for potential meeting creation
                email_context = {
                    **metadata,  # Use clean extracted data instead of raw webhook payload
                    "intent": intent.model_dump(),
                    "conversation_history": conversation_history
                }
                
                result = await self.email_sender.execute_action(response_text, email_context)
                
                logger.info(f"Email processing completed: {result.action_taken}")
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