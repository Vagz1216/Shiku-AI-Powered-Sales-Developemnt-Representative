"""Email response generation agent."""

import logging
from typing import Dict, Any

from config.logging import setup_logging
from agents import Agent, ModelSettings, Runner, set_default_openai_key
from schema import EmailIntent, EmailResponse
from config import settings

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Set OpenAI API key for agents library
if settings.openai_api_key:
    set_default_openai_key(settings.openai_api_key)


class EmailResponseAgent:
    """Agent that crafts replies based on intent analysis."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailResponseAgent",
            model=settings.response_model,
            instructions="""
You are a professional business development assistant crafting strategic email responses.

Analyze the email intent and generate an appropriate response:
- MEETING_REQUEST: Express enthusiasm and suggest specific times
- QUESTION: Answer concisely and transition to suggesting a call  
- INTEREST: Build on their interest and push for meetings
- OPT_OUT: Respect their request gracefully and confirm removal
- NEUTRAL: Engage professionally and assess potential
- BOUNCE/SPAM: Set action to "skipped" with appropriate reason

For valid intents (confidence >= 0.3), generate professional responses (2-3 paragraphs max).
For low confidence or unwanted intents, set action to "skipped" with reason.

IMPORTANT: Always end emails with this professional signature:
Best regards,
Business Development Team
Euclid Squad3 Solutions
""",
            model_settings=ModelSettings(
                temperature=settings.response_temperature,
                max_tokens=settings.response_max_tokens
            ),
            output_type=EmailResponse
        )
    
    async def generate_response(self, email_data: Dict[str, Any], intent: EmailIntent, conversation_history: str = "") -> EmailResponse:
        """Generate appropriate response based on intent."""
        sender_email = email_data.get('from_', [''])[0]
        subject = email_data.get('subject', '')
        content = email_data.get('text', '') or email_data.get('preview', '')
        
        context = f"From: {sender_email}\nSubject: {subject}\nContent: {content}\nINTENT: {intent.intent} (confidence: {intent.confidence})\nHistory: {conversation_history or 'None'}"
        
        try:
            result = await Runner.run(self.agent, context)
            return result.final_output
        except Exception as e:
            logger.error(f"Failed to generate response: {e}")
            return EmailResponse(
                response_text="",
                action="error",
                reason=str(e)
            )