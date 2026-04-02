"""Intent extraction agent for email content analysis."""

import json
import logging
from typing import Any

from agents import Agent, ModelSettings, Runner
from schema import EmailIntent
from config import settings

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
                model=settings.intent_model,
                temperature=settings.intent_temperature,
                max_tokens=settings.intent_max_tokens
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
            response_data = json.loads(result.final_output)
            return EmailIntent(**response_data)
        except Exception as e:
            logger.warning(f"Failed to parse intent response: {e}")
            return EmailIntent(intent="neutral", confidence=0.5)