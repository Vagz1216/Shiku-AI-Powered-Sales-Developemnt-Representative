"""Response evaluation agent for email safety validation."""

import json
import logging
from typing import Dict, Any

from agents import Agent, ModelSettings, Runner
from config import settings
from schema import ResponseEvaluation

logger = logging.getLogger(__name__)


class ResponseEvaluator:
    """Agent that evaluates email responses before sending."""
    
    def __init__(self):
        self.agent = Agent(
            name="EmailResponseEvaluator",
            instructions="""
You are an email response quality evaluator. Your job is simple: determine if an email response is safe and appropriate to send.

Evaluate the response for:
- Professional tone and language
- Appropriate content for business context  
- No inappropriate, offensive, or unprofessional content
- Clear and helpful response to the inquiry

Return a simple pass/fail decision with brief reasoning.

Always respond in this exact JSON format:
{
  "approved": true/false,
  "reason": "Brief explanation of decision"
}
""",
            model_settings=ModelSettings(
                model=settings.intent_model,  # Reuse same model as intent extraction
                temperature=0.2,  # Low temperature for consistent evaluation  
                max_tokens=200
            )
        )
    
    async def evaluate_response(self, response_text: str, email_context: Dict[str, Any]) -> ResponseEvaluation:
        """Evaluate an email response - simple pass/fail decision."""
        sender_email = email_context.get('from_', [''])[0]
        subject = email_context.get('subject', '')
        intent = email_context.get('intent', 'unknown')
        
        prompt = f"""
Evaluate this email response for safety and appropriateness:

CONTEXT:
- Recipient: {sender_email}
- Subject: {subject} 
- Intent: {intent}

PROPOSED RESPONSE:
{response_text}

Is this response professional and appropriate to send?
"""
        
        try:
            result = await Runner.run(self.agent, prompt)
            
            # Parse JSON output and validate with schema
            evaluation_data = json.loads(result.final_output)
            evaluation = ResponseEvaluation(**evaluation_data)
            
            logger.info(f"Response evaluation: {'APPROVED' if evaluation.approved else 'REJECTED'} - {evaluation.reason}")
            
            return evaluation
            
        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            # Default to rejection on evaluation failure for safety
            return ResponseEvaluation(
                approved=False,
                reason=f"Evaluation error: {str(e)}"
            )