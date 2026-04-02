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
- meeting_request: Explicitly asking to schedule a meeting/call
- question: Has specific questions about services
- interest: Expressing interest but no specific questions
- opt_out: Requesting to be removed or unsubscribed
- neutral: General inquiry or acknowledgment
- bounce: Automated bounce/out-of-office message
- spam: Spam or irrelevant content

Provide confidence score 0.0-1.0 based on clarity of intent.
""",
            model_settings=ModelSettings(
                temperature=settings.intent_temperature,
                max_tokens=settings.intent_max_tokens
            ),
            output_type=EmailIntent
        )
    
    async def extract_intent(self, email_content: str, subject: str = "") -> EmailIntent:
        """Extract intent from email content."""
        context = f"Subject: {subject}\nContent: {email_content}"
        
        try:
            result = await Runner.run(self.agent, context)
            return result.final_output
        except Exception as e:
            logger.error(f"Failed to extract intent: {e}")
            return EmailIntent(intent="neutral", confidence=0.5)