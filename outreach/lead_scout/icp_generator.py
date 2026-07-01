import json
from pydantic import BaseModel, Field
from typing import List, Optional
from utils.model_fallback import run_agent_with_fallback
import logging

logger = logging.getLogger(__name__)

class ICPParameters(BaseModel):
    job_titles: List[str] = Field(description="Target job titles (e.g., 'VP of Sales', 'CTO')")
    industries: List[str] = Field(description="Target industries")
    company_size_ranges: List[str] = Field(description="Apollo size ranges, e.g., '1,10', '11,50', '51,200', '201,500', '501,1000'")
    locations: List[str] = Field(description="Target locations (countries or major cities)")
    keywords: List[str] = Field(description="Keywords to look for in company description")
    seniority_levels: List[str] = Field(description="Seniority levels (e.g., 'director', 'vp', 'c_suite')")
    rationale: str = Field(description="Why this ICP was chosen based on the value proposition")

ICP_GENERATOR_PROMPT = """You are an expert SDR manager. Your job is to translate a campaign's value proposition into structured search parameters for a lead discovery database (like Apollo.io).

Campaign Name: {campaign_name}
Value Proposition: {value_proposition}
Call to Action (CTA): {cta}
Additional Context: {context}

Generate the Ideal Customer Profile (ICP) parameters to find the best leads for this campaign.
Ensure job titles are specific and relevant to who would buy this value proposition.
If location isn't specified, default to United States, United Kingdom, and Canada."""

async def generate_icp_from_campaign(campaign_name: str, value_proposition: str, cta: str, context: str = "") -> ICPParameters:
    """Generate structured ICP search parameters based on campaign context."""
    prompt = ICP_GENERATOR_PROMPT.format(
        campaign_name=campaign_name,
        value_proposition=value_proposition,
        cta=cta,
        context=context
    )
    
    try:
        result, provider = await run_agent_with_fallback(
            name="ICPGenerator",
            instructions="You generate structured search parameters based on campaign context. Output only JSON matching the schema.",
            prompt=prompt,
            output_type=ICPParameters,
            temperature=0.2,
            max_tokens=1000
        )
        logger.info(f"ICP Generated via {provider}")
        return result.final_output
    except Exception as e:
        logger.error(f"Failed to generate ICP: {e}")
        # Return a safe default fallback
        return ICPParameters(
            job_titles=["Founder", "CEO", "VP of Sales"],
            industries=["Software"],
            company_size_ranges=["1,10", "11,50"],
            locations=["United States"],
            keywords=[],
            seniority_levels=["c_suite", "vp"],
            rationale="Fallback ICP due to generation error."
        )
