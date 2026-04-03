"""Email monitoring system orchestrator."""

import logging
import re
from typing import Dict, Any, Optional, Tuple
from agentmail import AgentMail

from config.logging import setup_logging
from config import settings
from schema import EmailActionResult
from agents import trace, gen_trace_id
from .intent_extractor import IntentExtractorAgent
from .email_response import EmailResponseAgent
from .response_evaluator import ResponseEvaluator
from .email_sender import EmailSenderAgent

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


def validate_email_security(content: str, sender_email: str, subject: str) -> Tuple[bool, Optional[str]]:
    """Validate email for security issues before LLM processing.
    
    Args:
        content: Email content to validate
        sender_email: Sender's email address
        subject: Email subject line
        
    Returns:
        Tuple of (is_valid, rejection_reason)
    """
    # 1. Content length validation (prevent token exhaustion)
    if len(content) > 2000:
        return False, f"Email content too long ({len(content)} chars, max 2000)"
    
    # 2. Basic prompt injection patterns
    injection_patterns = [
        r'ignore\s+(previous|above|all)\s+instructions',
        r'forget\s+(everything|all|previous)',
        r'new\s+(instructions|task|role)',
        r'system\s*(prompt|message|instruction)',
        r'act\s+as\s+(?:a\s+)?(?!customer|client)',  # Allow "act as customer" but block others
        r'<\s*prompt\s*>',
        r'\[\s*system\s*\]',
        r'pretend\s+(?:you|to)\s+(?:are|be)',
        r'jailbreak|sudo|admin|root',
        r'override\s+(safety|security|settings)',
    ]
    
    combined_text = f"{subject} {content}".lower()
    for pattern in injection_patterns:
        if re.search(pattern, combined_text, re.IGNORECASE):
            return False, f"Potential prompt injection detected: {pattern}"
    
    # 3. Suspicious content patterns
    suspicious_patterns = [
        r'<script[^>]*>',  # Script tags
        r'javascript:',     # JavaScript URLs
        r'data:text/html',  # Data URLs
        r'eval\s*\(',       # Eval functions
        r'\$\([^)]*\)',     # jQuery-like selectors (potential XSS)
        r'document\.cookie', # Cookie access
        r'window\.location', # Location manipulation
        r'\bexec\b|\bsystem\b|\bshell\b', # System commands
    ]
    
    for pattern in suspicious_patterns:
        if re.search(pattern, combined_text, re.IGNORECASE):
            return False, f"Suspicious content pattern detected: {pattern}"
    
    # 4. Basic sender validation
    # Check for obviously fake/suspicious email patterns
    suspicious_domains = ['tempmail', 'guerrillamail', '10minutemail', 'mailinator']
    email_domain = sender_email.split('@')[-1].lower() if '@' in sender_email else ''
    
    if any(domain in email_domain for domain in suspicious_domains):
        return False, f"Suspicious sender domain: {email_domain}"
    
    # 5. Excessive special characters (potential encoding attacks)
    special_char_ratio = len(re.findall(r'[^\w\s.,!?@-]', content)) / max(len(content), 1)
    if special_char_ratio > 0.3:  # More than 30% special characters
        return False, f"Excessive special characters ({special_char_ratio:.1%})"
    
    # 6. Repeated patterns (potential spam/DoS)
    # Check for excessive repetition of words or characters
    words = content.lower().split()
    if len(words) > 10:  # Only check if enough words
        word_counts = {}
        for word in words:
            if len(word) > 3:  # Skip very short words
                word_counts[word] = word_counts.get(word, 0) + 1
        
        max_repetition = max(word_counts.values()) if word_counts else 0
        if max_repetition > len(words) * 0.5:  # Single word appears in >50% of content
            return False, "Excessive word repetition detected"
    
    return True, None


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
    
    async def fetch_conversation_history(self, thread_id: str, limit: int = 10) -> str:
        """Fetch thread messages using proper AgentMail API.
        
        Args:
            thread_id: Email thread identifier
            limit: Maximum number of messages to include (for context length control)
            
        Returns:
            Formatted conversation history string
        """
        if not thread_id:
            return "No thread ID available."
            
        try:
            # Get full thread with all messages using efficient API
            thread = self.agentmail_client.threads.get(thread_id=thread_id)
            
            if not thread.messages:
                return "No messages found in thread."
            
            # Sort by creation time and limit for context control
            messages = sorted(thread.messages, key=lambda x: getattr(x, 'created_at', 0))
            messages = messages[:limit]
            
            # Format conversation history
            history_parts = []
            for msg in messages:
                sender = msg.from_[0] if msg.from_ else "Unknown"
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else "Unknown time"
                # Use extracted_text for clean content without quoted history
                content = msg.extracted_text or msg.text or msg.preview or "[No content]"
                
                # Truncate very long messages for context efficiency
                if len(content) > 300:
                    content = content[:300] + "... [truncated]"
                
                history_parts.append(
                    f"[{timestamp}] {sender}:\n{content}\n"
                )
            
            return "\n---\n".join(history_parts)
            
        except Exception as e:
            logger.warning(f"Failed to fetch thread {thread_id}: {e}")
            return f"Unable to fetch conversation history: {str(e)}"
    
    async def process_incoming_email(self, email_data: Dict[str, Any]) -> EmailActionResult:
        """Complete email processing pipeline with retry logic and meeting scheduling."""
        # Create a single trace for the entire email processing pipeline
        trace_id = gen_trace_id()
        sender_email = email_data.get('from_', [''])[0]
        subject = email_data.get('subject', '')
        
        with trace(
            workflow_name="email_reply_processing_pipeline",
            trace_id=trace_id,
            metadata={"sender": sender_email, "subject": subject}
        ):
            try:
                content = email_data.get('text', '') or email_data.get('preview', '')
                thread_id = email_data.get('thread_id')
                
                logger.info(f"Processing email from {sender_email}: {subject}")
                
                # Security validation - check before any LLM processing
                is_valid, rejection_reason = validate_email_security(content, sender_email, subject)
                if not is_valid:
                    logger.warning(f"Email validation failed from {sender_email}: {rejection_reason}")
                    return EmailActionResult(
                        action_taken="rejected_security",
                        success=True,  # Successfully rejected for security
                        error=f"Email rejected for security: {rejection_reason}",
                        message_id=email_data.get('id', '')
                    )
                
                logger.info(f"Email security validation passed for {sender_email}")
                
                # Step 1: Extract intent
                intent = await self.intent_extractor.extract_intent(content, subject)
                logger.info(f"Intent: {intent.intent} (confidence: {intent.confidence})")
                
                # Step 2: Get conversation context
                conversation_history = await self.fetch_conversation_history(thread_id) if thread_id else ""
                
                # Step 3: Generate response with retry logic
                max_retries = 2
                retry_count = 0
                
                while retry_count <= max_retries:
                    # Generate response
                    response_result = await self.response_agent.generate_response(
                        email_data, intent, conversation_history
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
                    evaluation_context = {**email_data, "intent": intent.intent}
                    
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
                
                # Step 4: Send email with context for potential meeting creation
                email_context = {
                    **email_data,
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