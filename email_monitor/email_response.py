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
- MEETING_REQUEST: Express enthusiasm and confirm that you will send over a calendar invite shortly. State explicitly: "I will send over a calendar invite shortly. If the proposed time doesn't work, feel free to propose a new time via the calendar link."
- MEETING_CONFIRMATION: The lead is confirming a previously proposed meeting time. Write a brief, warm acknowledgment (1-2 paragraphs max). Thank them for confirming, mention that a calendar invite with meeting details will be sent shortly, and express that you look forward to the discussion.
- QUESTION: Answer the question directly and concisely. Transition to suggesting a call if appropriate, but DO NOT promise a calendar invite unless the primary intent is meeting_request.
- INTEREST: Build on their interest and suggest a discovery call.
- OPT_OUT: Respect their request gracefully and confirm removal from our list.
- NEUTRAL: Engage professionally, thank them for their time, and assess if further outreach is needed.
- BOUNCE/SPAM: Set action to "skipped" with appropriate reason.

For valid intents (confidence >= 0.3), generate professional responses (2-3 paragraphs max).
DO NOT cut off your sentences. Ensure the email is complete and ends with the required signature.
If you are interrupted or hit a token limit, ensure you at least finish the current sentence.

Provide a chain of thought rationale explaining your chosen response strategy before generating the final text.

IMPORTANT FORMATTING RULES:
- DO NOT include clickable links, buttons, or "click here" calls-to-action in the email body. Quick-reply links are added automatically by the system after your response.
- End the email body BEFORE the signature. Do not add any post-signature content.
- Always end emails with this professional signature:

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
        # Extract email information from clean metadata
        sender_email = email_data.get('sender_email', '')
        sender_name = email_data.get('sender_name', 'Unknown')
        subject = email_data.get('subject', '')
        content = email_data.get('content', '')
        
        context = f"From: {sender_name} ({sender_email})\\nSubject: {subject}\\nContent: {content}\\nINTENT: {intent.intent} (confidence: {intent.confidence})\\nHistory: {conversation_history or 'None'}"
        
        try:
            from utils.model_fallback import run_agent_with_fallback
            
            result, provider = await run_agent_with_fallback(
                name="EmailResponseAgent",
                instructions=self.agent.instructions,
                prompt=context,
                output_type=EmailResponse,
                temperature=settings.response_temperature,
                max_tokens=settings.response_max_tokens
            )
            return result.final_output
        except Exception as e:
            logger.error(f"Failed to generate response: {e}")
            return EmailResponse(
                rationale="Fallback rationale due to response generation error.",
                response_text="",
                action="error",
                reason=str(e)
            )