"""Content generation tools with different writing styles and channels."""

import logging
from agents import function_tool
from schema.outreach import OutreachEmailDraft
from utils.model_fallback import run_agent_with_fallback

logger = logging.getLogger(__name__)

# Professional Writer Instructions
PROFESSIONAL_INSTRUCTIONS = """Write a formal, business-focused outreach email. Use:
- Professional tone and clear value propositions
- Specific business benefits and ROI focus
- Formal greeting (Dear CEO, Manager, etc.) and professional closing (Best regards, Business Development Team)
- No placeholder text - use real business development language
- Focus on partnership opportunities and business value

Structure: Professional greeting + value proposition + specific benefits + clear CTA + professional signature"""

# Engaging Writer Instructions
ENGAGING_INSTRUCTIONS = """Write a warm, story-driven outreach email. Use:
- Conversational tone with genuine business scenarios
- Emotional connection and relatable business challenges
- Friendly greeting (Hi there,) and warm closing (Best, Growth Team)
- No placeholder text - use authentic business storytelling
- Focus on transformation and success stories

Structure: Friendly greeting + relatable scenario + transformation story + clear CTA + warm signature"""

# Concise Writer Instructions
CONCISE_INSTRUCTIONS = """Write a brief, direct outreach email. Use:
- Straight-to-point messaging with clear results
- Urgency and immediate value focus
- Simple greeting (Hi,) and brief closing (Thanks, Sales Team)
- No placeholder text - use direct business language
- Focus on quick wins and immediate action

Structure: Brief greeting + direct value statement + clear CTA + simple signature (max 4-5 sentences total)"""

# LinkedIn Instructions
LINKEDIN_INSTRUCTIONS = """Write a connection request note (max 300 characters). 
Be casual and authentic. No subject line.
Use the provided recent activity as a natural conversation opener if it exists. 
If no recent activity is provided, base your opener on their industry and role instead.
CRITICAL: Do NOT fabricate or invent milestones, funding rounds, or posts. Only reference what is explicitly provided in the prompt."""

# WhatsApp Instructions
WHATSAPP_INSTRUCTIONS = """Write a friendly, 2-sentence WhatsApp message. Reference the emails we previously sent. Ask a simple yes/no qualification question."""

@function_tool
async def create_professional_email(name: str, value_proposition: str) -> OutreachEmailDraft:
    """Generate a formal, professional outreach email for a target company.
    
    Args:
        name: The target company or contact name
        value_proposition: The specific value proposition for this outreach
        
    Returns:
        A formal email draft with subject and body
    """
    prompt = f"""Target: {name}
Value Proposition: {value_proposition}

Create a formal business email that establishes credibility and demonstrates clear business value. Use the target name appropriately in the greeting and reference the value proposition throughout. Sign as 'Business Development Team' or similar professional signature.

Do not use any placeholder text like [Your Name] or [Company]. Write complete, ready-to-send content."""
    
    try:
        result, provider = await run_agent_with_fallback(
            name="ProfessionalWriter",
            instructions=PROFESSIONAL_INSTRUCTIONS,
            prompt=prompt,
            output_type=OutreachEmailDraft,
            temperature=0.3,
            max_tokens=1000
        )
        logger.info(f"Professional email generated using {provider}")
        return result.final_output
    except Exception as e:
        logger.error(f"Professional email generation failed: {e}")
        return OutreachEmailDraft(
            subject=f"Partnership Opportunity - {value_proposition}",
            body=f"Dear {name} Team,\n\nWe help companies with {value_proposition.lower()}. Our solution delivers measurable ROI and operational efficiency.\n\nWould you be interested in a brief discussion about how we can help {name} achieve similar results?\n\nBest regards,\nBusiness Development Team"
        )


@function_tool
async def create_engaging_email(name: str, value_proposition: str) -> OutreachEmailDraft:
    """Generate a warm, story-driven outreach email for a target company.
    
    Args:
        name: The target company or contact name
        value_proposition: The specific value proposition for this outreach
        
    Returns:
        An engaging email draft with subject and body
    """
    prompt = f"""Target: {name}
Value Proposition: {value_proposition}

Create a warm, conversational email that tells a relevant business story or scenario. Use the target name naturally and weave the value proposition into a compelling narrative. Sign with a friendly but professional closing like 'Best, Sarah' or 'Cheers, The Growth Team'.

Do not use any placeholder text like [Your Name] or [Company]. Write complete, ready-to-send content with authentic storytelling."""
    
    try:
        result, provider = await run_agent_with_fallback(
            name="EngagingWriter",
            instructions=ENGAGING_INSTRUCTIONS,
            prompt=prompt,
            output_type=OutreachEmailDraft,
            temperature=0.7,
            max_tokens=1000
        )
        logger.info(f"Engaging email generated using {provider}")
        return result.final_output
    except Exception as e:
        logger.error(f"Engaging email generation failed: {e}")
        return OutreachEmailDraft(
            subject=f"How {name} Can Transform Operations 🚀",
            body=f"Hi there!\n\nI recently worked with a company similar to {name} that was struggling with {value_proposition.lower()}. Within 3 months, they saw incredible results.\n\nI'd love to share their story and see if we can help {name} achieve similar success!\n\nBest,\nSarah from Growth Team"
        )


@function_tool
async def create_concise_email(name: str, value_proposition: str) -> OutreachEmailDraft:
    """Generate a brief, direct outreach email for a target company.
    
    Args:
        name: The target company or contact name
        value_proposition: The specific value proposition for this outreach
        
    Returns:
        A concise email draft with subject and body
    """
    prompt = f"""Target: {name}
Value Proposition: {value_proposition}

Create a short, to-the-point email (maximum 4-5 sentences) that gets straight to business value. Use the target name efficiently and present the value proposition with urgency. Sign simply with 'Best' or 'Thanks' and a first name.

Do not use any placeholder text like [Your Name] or [Company]. Write complete, ready-to-send content that's direct and actionable."""
    
    try:
        result, provider = await run_agent_with_fallback(
            name="ConciseWriter",
            instructions=CONCISE_INSTRUCTIONS,
            prompt=prompt,
            output_type=OutreachEmailDraft,
            temperature=0.5,
            max_tokens=800
        )
        logger.info(f"Concise email generated using {provider}")
        return result.final_output
    except Exception as e:
        logger.error(f"Concise email generation failed: {e}")
        return OutreachEmailDraft(
            subject=f"{value_proposition} - Quick Question",
            body=f"Hi,\n\nCan we help {name} with {value_proposition.lower()}?\n\n5-minute call this week?\n\nBest,\nMike"
        )


async def create_linkedin_connection_note(campaign_name: str, value_proposition: str, lead_info: dict, context: str = "") -> OutreachEmailDraft:
    """Generate a short LinkedIn connection request note for a target company.
    
    Args:
        campaign_name: The name of the campaign
        value_proposition: The specific value proposition for this outreach
        lead_info: Dictionary containing lead details (name, company, recent_activity, etc)
        context: Optional extra instructions or context for this sequence step
        
    Returns:
        A LinkedIn message draft
    """
    lead_name = lead_info.get("name") or "there"
    company = lead_info.get("company") or "your company"
    recent_activity = lead_info.get("recent_activity")
    job_title = lead_info.get("job_title")
    industry = lead_info.get("industry")
    
    prompt = f"""Target: {lead_name} at {company}
Role/Industry: {job_title or 'Unknown Role'} in {industry or 'Unknown Industry'}
Value Proposition: {value_proposition}
Recent Activity: {recent_activity or 'None available'}

Create a connection request note (max 300 characters). 
{f"Context/Instructions for this specific sequence step: {context}" if context else ""}

Do not use any placeholder text like [Your Name] or [Company]. Write complete, ready-to-send content."""
    
    try:
        result, provider = await run_agent_with_fallback(
            name="LinkedInWriter",
            instructions=LINKEDIN_INSTRUCTIONS,
            prompt=prompt,
            output_type=OutreachEmailDraft,
            temperature=0.6,
            max_tokens=150
        )
        logger.info(f"LinkedIn note generated using {provider}")
        draft = result.final_output
        draft.channel = "linkedin"
        draft.subject = ""
        return draft
    except Exception as e:
        logger.error(f"LinkedIn note generation failed: {e}")
        return OutreachEmailDraft(
            subject="",
            body=f"Hi {name}, saw your recent updates and would love to connect. We help teams with {value_proposition.lower()}. Let's chat!",
            channel="linkedin"
        )


async def create_whatsapp_message(name: str, value_proposition: str, context: str = "") -> OutreachEmailDraft:
    """Generate a friendly WhatsApp message for a target company.
    
    Args:
        name: The target company or contact name
        value_proposition: The specific value proposition for this outreach
        context: Optional extra instructions or context for this sequence step
        
    Returns:
        A WhatsApp message draft
    """
    prompt = f"""Target: {name}
Value Proposition: {value_proposition}

Write a friendly, 2-sentence WhatsApp message. Reference the emails we previously sent. Ask a simple yes/no qualification question.
{f"Context/Instructions for this specific sequence step: {context}" if context else ""}

Do not use any placeholder text like [Your Name] or [Company]. Write complete, ready-to-send content."""
    
    try:
        result, provider = await run_agent_with_fallback(
            name="WhatsAppWriter",
            instructions=WHATSAPP_INSTRUCTIONS,
            prompt=prompt,
            output_type=OutreachEmailDraft,
            temperature=0.6,
            max_tokens=150
        )
        logger.info(f"WhatsApp message generated using {provider}")
        draft = result.final_output
        draft.channel = "whatsapp"
        draft.subject = ""
        return draft
    except Exception as e:
        logger.error(f"WhatsApp message generation failed: {e}")
        return OutreachEmailDraft(
            subject="",
            body=f"Hi {name}, just following up on my previous emails about {value_proposition.lower()}. Is this something you're currently exploring?",
            channel="whatsapp"
        )
