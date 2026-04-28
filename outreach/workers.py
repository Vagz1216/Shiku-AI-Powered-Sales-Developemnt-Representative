"""Specialized worker agents for the Orchestrator-Worker pattern."""

import logging
from typing import Dict, Any
from pydantic import BaseModel, Field

from schema.outreach import OutreachEmailDraft
from utils.model_fallback import run_agent_with_fallback
from config.settings import settings

logger = logging.getLogger(__name__)

class DraftsResponse(BaseModel):
    """Output from the Drafter Agent."""
    professional_draft: OutreachEmailDraft
    engaging_draft: OutreachEmailDraft
    concise_draft: OutreachEmailDraft

class ReviewResponse(BaseModel):
    """Output from the Reviewer Agent."""
    rationale: str = Field(description="Chain of thought explaining why this draft is best, considering lead industry and pain points")
    selected_draft_type: str = Field(description="The type of draft selected (professional, engaging, or concise)")
    subject: str = Field(description="The selected email subject")
    body: str = Field(description="The selected email body")


async def run_drafter_agent(campaign_info: Dict[str, Any], lead_info: Dict[str, Any]) -> DraftsResponse:
    """Worker Agent 1: Generates multiple variations of the email."""
    instructions = (
        "You are an expert SDR copywriter. Generate exactly 3 email drafts based on the provided lead and campaign context. "
        "Respect sequence stage: first-touch emails should introduce value; follow-up emails should acknowledge prior outreach and add fresh angle/value."
    )
    prompt = f"""
    Campaign Details:
    - Name: {campaign_info['name']}
    - Value Proposition: {campaign_info['value_proposition']}
    - CTA: {campaign_info.get('cta', '')}
    - Preferred Tone: {campaign_info.get('tone', settings.tone)}
    - Sender Name: {campaign_info.get('sender_name', settings.outreach_sender_name)}
    - Sender Company: {campaign_info.get('sender_company', settings.outreach_sender_company)}
    
    Lead Details:
    - Name: {lead_info['name']}
    - Company: {lead_info['company']}
    - Industry: {lead_info.get('industry', 'Unknown')}
    - Pain Points: {lead_info.get('pain_points', 'Unknown')}
    - Total Touch Count: {lead_info.get('touch_count', 0)}
    - Emails Sent In This Campaign: {lead_info.get('emails_sent', 0)}
    - Has Responded Before: {bool(lead_info.get('responded', 0))}
    
    Generate exactly 3 drafts:
    1. Professional: Formal business tone, focusing on ROI and specific business benefits.
    2. Engaging: Warm, story-driven, conversational, focusing on relatable business challenges.
    3. Concise: Brief, direct, maximum 4-5 sentences, focusing on quick wins.
    
    Follow-up sequencing rules:
    - If Emails Sent In This Campaign is 0: treat as first-touch outreach.
    - If Emails Sent In This Campaign is 1 or more: treat as follow-up and avoid repeating identical opener/CTA.
    - For follow-up, include one new angle (e.g., quantified benefit, relevant use case, or pain-point reframing).
    
    CRITICAL INSTRUCTION:
    - Do NOT use any bracketed placeholders like [Your Name], [Company], [Sender], etc.
    - Always sign using the provided sender identity.
    - Use the provided CTA naturally in the email body.
    """
    
    result, provider = await run_agent_with_fallback(
        name="DrafterAgent",
        instructions=instructions,
        prompt=prompt,
        output_type=DraftsResponse,
        temperature=0.7,
        max_tokens=2000
    )
    logger.info(f"DrafterAgent completed using {provider}")
    return result.final_output


async def run_reviewer_agent(campaign_info: Dict[str, Any], lead_info: Dict[str, Any], drafts: DraftsResponse) -> ReviewResponse:
    """Worker Agent 2: Reviews drafts and selects the best one."""
    instructions = "You are a Senior Marketing Reviewer. Evaluate the email drafts and select the best one. You MUST output your reasoning in the 'rationale' field first."
    prompt = f"""
    Campaign Value Proposition: {campaign_info['value_proposition']}
    Campaign CTA: {campaign_info.get('cta', '')}
    Preferred Tone: {campaign_info.get('tone', settings.tone)}
    Sender Name: {campaign_info.get('sender_name', settings.outreach_sender_name)}
    Sender Company: {campaign_info.get('sender_company', settings.outreach_sender_company)}
    Lead Name: {lead_info['name']}
    Lead Industry: {lead_info.get('industry', 'Unknown')}
    Lead Pain Points: {lead_info.get('pain_points', 'Unknown')}
    Emails Sent In Campaign So Far: {lead_info.get('emails_sent', 0)}
    
    Drafts to Evaluate:
    
    1. Professional
    Subject: {drafts.professional_draft.subject}
    Body: {drafts.professional_draft.body}
    
    2. Engaging
    Subject: {drafts.engaging_draft.subject}
    Body: {drafts.engaging_draft.body}
    
    3. Concise
    Subject: {drafts.concise_draft.subject}
    Body: {drafts.concise_draft.body}
    
    Select the BEST draft for this specific lead. Consider their industry and pain points. 
    Ensure the email directly addresses their pain points using the value proposition.
    Ensure the draft is appropriate for the outreach stage (first-touch vs follow-up).
    
    CRITICAL INSTRUCTION:
    - The final selected body MUST NOT contain any placeholders like [Your Name], [Company], etc.
    - If the chosen draft has placeholders, replace them with the provided sender identity before outputting.
    """
    
    result, provider = await run_agent_with_fallback(
        name="ReviewerAgent",
        instructions=instructions,
        prompt=prompt,
        output_type=ReviewResponse,
        temperature=0.3,
        max_tokens=1500
    )
    logger.info(f"ReviewerAgent completed using {provider}")
    return result.final_output
