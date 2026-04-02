"""Senior Marketing Agent that orchestrates database-driven outreach campaigns with tracing."""

import logging
import json
from typing import Dict, Any

from config.logging import setup_logging
from agents import Agent, ModelSettings, Runner, set_default_openai_key, trace
from config import settings

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
        
        self.agent = Agent(
            name="SeniorMarketingAgent",
            model=settings.outreach_model,
            instructions="""You are a Senior Marketing Agent that evaluates and executes outreach campaigns. Use the following tools to complete the campaign workflow:
- get_campaign_tool: Retrieve campaign details and objectives from the database
- get_lead_tool: Retrieve lead email and name
- create_professional_email: Generate a professional email draft
- create_engaging_email: Generate an engaging email draft
- create_concise_email: Generate a concise email draft
- send_agent_email: Send the selected email draft
""",
            model_settings=ModelSettings(
                temperature=0.4,
                max_tokens=1000
            ),
            tools=self.tools
        )
    
    async def execute_campaign(self, campaign_brief: str = "Execute database-driven outreach campaign") -> Dict[str, Any]:
        """Execute a complete database-driven outreach campaign with tracing."""
        logger.info("Starting automated database-driven outreach campaign")
        
        try:
            with trace("Outreach Campaign Execution"):
                runner = Runner()
                result = await runner.run(
                    self.agent,
                    "Execute automated outreach campaign"
                )
                
                if hasattr(result, 'value') and result.value:
                    logger.info("Database-driven outreach campaign completed successfully")
                    return {
                        "success": True,
                        "message": "Automated campaign executed with full database integration and tracing",
                        "agent_result": str(result.value) if hasattr(result, 'value') else "Campaign completed"
                    }
                else:
                    logger.info("Database-driven outreach campaign completed successfully (no result value)")
                    return {
                        "success": True,
                        "message": "Automated campaign executed with full database integration and tracing",
                        "agent_result": "Campaign completed successfully"
                    }
                    
        except Exception as e:
            logger.error(f"Campaign execution error: {e}")
            return {"success": False, "error": str(e)}

# Create global instance for API usage
senior_marketing_agent = SeniorMarketingAgent()