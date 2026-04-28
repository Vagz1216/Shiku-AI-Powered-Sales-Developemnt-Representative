"""Intent extraction agent for email content analysis."""

import logging
from typing import Any

from config.logging import setup_logging
from agents import Agent, ModelSettings, Runner, set_default_openai_key
from schema import EmailIntent
from config import settings

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Set OpenAI API key for agents library
if settings.openai_api_key:
    set_default_openai_key(settings.openai_api_key)


class IntentExtractorAgent:
    """Agent that extracts intent from email content."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailIntentExtractor",
            model=settings.intent_model,
            instructions="""
Analyze email content and classify the sender's intent with confidence.

Classify into one of these intents:
- meeting_request: Explicitly asking to schedule a meeting/call for the FIRST TIME (no prior meeting proposal in the conversation)
- meeting_confirmation: Confirming or accepting a previously proposed meeting time (e.g. "that time works", "see you then", "looking forward to the call")
- question: Has specific questions about services
- interest: Expressing interest but no specific questions
- opt_out: Requesting to be removed or unsubscribed
- neutral: General inquiry or acknowledgment
- bounce: Automated bounce/out-of-office message
- spam: Spam or irrelevant content

IMPORTANT distinction between meeting_request vs meeting_confirmation:
- meeting_request: The lead is asking to meet for the first time, or no specific time has been proposed yet
- meeting_confirmation: A meeting time was ALREADY proposed in earlier messages, and the lead is now confirming/accepting it

Provide a chain of thought rationale explaining your reasoning before giving the final intent and confidence score (0.0-1.0).
""",
            model_settings=ModelSettings(
                temperature=settings.intent_temperature,
                max_tokens=settings.intent_max_tokens
            ),
            output_type=EmailIntent
        )
    
    async def extract_intent(self, email_content: str, subject: str = "", sender_email: str = "") -> EmailIntent:
        """Extract intent from email content.
        
        First checks for quick-reply keyword markers (zero-cost fast path).
        Falls back to LLM classification if no keyword is found.
        """
        from utils.quick_replies import detect_quick_reply_keyword

        keyword_intent = detect_quick_reply_keyword(email_content)
        if not keyword_intent:
            keyword_intent = detect_quick_reply_keyword(subject)
        if keyword_intent:
            logger.info(f"Fast-path intent detected via quick-reply keyword: {keyword_intent}")
            return EmailIntent(
                rationale=f"Quick-reply keyword detected in email body/subject, mapping directly to '{keyword_intent}' without LLM call.",
                intent=keyword_intent,
                confidence=1.0
            )

        context = f"Subject: {subject}\nContent: {email_content}"
        
        try:
            from utils.model_fallback import run_agent_with_fallback
            
            result, provider = await run_agent_with_fallback(
                name="EmailIntentExtractor",
                instructions=self.agent.instructions,
                prompt=context,
                output_type=EmailIntent,
                temperature=settings.intent_temperature,
                max_tokens=settings.intent_max_tokens
            )
            return result.final_output
        except Exception as e:
            logger.error(f"Failed to extract intent: {e}")
            return EmailIntent(
                rationale="Fallback rationale due to intent extraction failure.",
                intent="neutral", 
                confidence=0.5
            )