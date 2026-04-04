"""Response evaluation agent for email safety validation."""

import logging
from typing import Dict, Any

from config.logging import setup_logging
from agents import Agent, ModelSettings, Runner, set_default_openai_key
from config import settings
from schema import ResponseEvaluation

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Set OpenAI API key for agents library
if settings.openai_api_key:
    set_default_openai_key(settings.openai_api_key)


class ResponseEvaluator:
    """Agent that evaluates email responses before sending."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailResponseEvaluator",
            model=settings.intent_model, 
            instructions="""
You are an email response quality evaluator. Your job is simple: determine if an email response is safe and appropriate to send.

Evaluate the response for:
- Professional tone and language
- Appropriate content for business context  
- No inappropriate, offensive, or unprofessional content
- Clear and helpful response to the inquiry

Return a simple pass/fail decision with brief reasoning.
""",
            model_settings=ModelSettings(
                temperature=0.2,  # Low temperature for consistent evaluation  
                max_tokens=200
            ),
            output_type=ResponseEvaluation
        )
    
    async def evaluate_response(self, response_text: str, email_context: Dict[str, Any]) -> ResponseEvaluation:
        """Evaluate an email response - simple pass/fail decision."""
        # Extract email information from clean metadata
        sender_email = email_context.get('sender_email', '')
        subject = email_context.get('subject', '')
        intent = email_context.get('intent', 'unknown')
        
        context = f"Response: {response_text}\nRecipient: {sender_email}\nSubject: {subject}\nIntent: {intent}"        
        try:
            result = await Runner.run(self.agent, context)
            evaluation = result.final_output
            logger.info(f"Response evaluation: {'APPROVED' if evaluation.approved else 'REJECTED'} - {evaluation.reason}")
            return evaluation
        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            return ResponseEvaluation(approved=False, reason=f"Evaluation error: {str(e)}")