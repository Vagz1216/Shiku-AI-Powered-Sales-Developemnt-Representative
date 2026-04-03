"""Senior Marketing Agent that orchestrates database-driven outreach campaigns with tracing."""

import logging
import json
from typing import Dict, Any, Optional

from config.logging import setup_logging
from agents import set_default_openai_key, trace, gen_trace_id
from config import settings
from utils.model_fallback import run_agent_with_fallback

# Import database-driven tools
from tools.campaign_tools import get_campaign_tool
from tools.lead_tools import get_lead_tool
from tools.send_email import send_agent_email
from tools.content_tools import (
    create_professional_email,
    create_engaging_email,
    create_concise_email
)


# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Set OpenAI API key for agents library
if settings.openai_api_key:
    set_default_openai_key(settings.openai_api_key)


# Senior Agent Instructions
SENIOR_AGENT_INSTRUCTIONS = """You are a Senior Marketing Agent that orchestrates outreach campaigns. Follow this EXACT workflow:

1. **Get Campaign**: Use get_campaign_tool to retrieve campaign details from database. If a specific campaign name is provided in the prompt, pass it to the tool.
2. **Get Lead**: Use get_lead_tool to retrieve target lead information 
3. **Generate Content**: Create 3 email variations using:
   - create_professional_email
   - create_engaging_email  
   - create_concise_email
4. **Evaluate & Select**: Compare the 3 drafts and choose the BEST one based on:
   - Relevance to campaign value proposition
   - Personalization for the lead
   - Professional quality and clarity
5. **Send ONE Email**: Use send_agent_email to send ONLY the selected best email

IMPORTANT: Send exactly ONE email per campaign. Do not send multiple emails.

For email generation, provide:
- name: The lead's company/contact name from get_lead_tool
- value_proposition: The campaign value proposition from get_campaign_tool

Complete the entire workflow and report success."""


class SeniorMarketingAgent:
    """Orchestrates complete database-driven outreach campaigns with AI content generation."""
    
    def __init__(self):
        # Collect all database-driven outreach tools
        self.tools = [
            get_campaign_tool,
            get_lead_tool,
            create_professional_email,
            create_engaging_email,
            create_concise_email,
            send_agent_email
        ]
    
    async def execute_campaign(self, campaign_name: Optional[str] = None) -> Dict[str, Any]:
        """Execute a complete database-driven outreach campaign with tracing and fallback."""
        logger.info(f"Starting automated database-driven outreach campaign. Target: {campaign_name or 'Random'}")
        
        prompt = "Execute automated outreach campaign"
        if campaign_name:
            prompt += f" for campaign: {campaign_name}"
        
        # Use structured trace with gen_trace_id to match monitor.py style
        trace_id = gen_trace_id()
        
        try:
            with trace(
                workflow_name="outreach_campaign_execution_pipeline",
                trace_id=trace_id,
                metadata={"campaign": campaign_name or "random_active"}
            ):
                result, provider = await run_agent_with_fallback(
                    name="SeniorMarketingAgent",
                    instructions=SENIOR_AGENT_INSTRUCTIONS,
                    prompt=prompt,
                    tools=self.tools,
                    temperature=0.4,
                    max_tokens=1000
                )
                
                logger.info(f"Database-driven outreach campaign completed successfully using {provider}")
                return {
                    "success": True,
                    "message": f"Automated campaign executed using {provider} with full database integration, tracing, and model fallback",
                    "agent_result": str(result)
                }
                    
        except Exception as e:
            logger.error(f"Campaign execution error: {e}")
            return {"success": False, "error": str(e)}

# Create global instance for API usage
senior_marketing_agent = SeniorMarketingAgent()