"""Content generation tools with 3 different writing styles."""

import logging
from agents import Agent, ModelSettings, Runner, function_tool
from schema.outreach import OutreachEmailDraft

logger = logging.getLogger(__name__)

#TODO move model settings to config
# Professional Writer Agent
professional_agent = Agent(
    name="ProfessionalWriter",
    model="gpt-4o-mini",
    instructions="Write formal, business-focused emails. Use professional tone, clear value propositions, and specific benefits. for the given lead information and campaign value proposition.",
    model_settings=ModelSettings(
        temperature=0.3,
        max_tokens=1000
    ),
    output_type=OutreachEmailDraft
)

# Engaging Writer Agent  
engaging_agent = Agent(
    name="EngagingWriter", 
    model="gpt-4o-mini",
    instructions="Write warm, story-driven emails. Use conversational tone, scenarios, and emotional connection. for the given lead information and campaign value proposition.",
    model_settings=ModelSettings(
        temperature=0.7,
        max_tokens=1000
    ),
    output_type=OutreachEmailDraft
)

# Concise Writer Agent
concise_agent = Agent(
    name="ConciseWriter",
    model="gpt-4o-mini", 
    instructions="Write brief, direct emails. Get straight to the point with clear results and urgency. for the given lead information and campaign value proposition.",
    model_settings=ModelSettings(
        temperature=0.5,
        max_tokens=800
    ),
    output_type=OutreachEmailDraft
)


@function_tool
async def create_professional_email(name: str, value_proposition: str) -> OutreachEmailDraft:
    """Professional marketing content writer.
    
    Args:
        name: campaign's name
        value_proposition: Campaign value proposition
    
    Returns:
        Professional email draft
    """
    prompt = f"Write a professional outreach email to {name} about: {value_proposition}"
    
    try:
        result = await Runner.run(professional_agent, prompt)
        return result.final_output
    except Exception as e:
        logger.error(f"Professional email generation failed: {e}")
        return OutreachEmailDraft(
            subject=f"Partnership Opportunity with {name}",
            body=f"Dear Team,\n\nI'd like to discuss how our solution can help with {value_proposition}.\n\nBest regards,\nBusiness Development Team"
        )


@function_tool  
async def create_engaging_email(name: str, value_proposition: str) -> OutreachEmailDraft:
    """Engaging marketing content writer.
    
    Args:
        name: campaign's name
        value_proposition: Campaign value proposition
    
    Returns:
        Engaging email draft
    """
    prompt = f"Write an engaging, story-driven outreach email to {name} about: {value_proposition}"
    
    try:
        result = await Runner.run(engaging_agent, prompt)
        return result.final_output
    except Exception as e:
        logger.error(f"Engaging email generation failed: {e}")
        return OutreachEmailDraft(
            subject=f"Transform Your Business with {name} 🚀",
            body=f"Hi there!\n\nI wanted to share how we can help with {value_proposition}. Let's connect!\n\nBest,\nOur Team"
        )


@function_tool
async def create_concise_email(name: str, value_proposition: str) -> OutreachEmailDraft:
    """Concise marketing content writer.
    
    Args:
        name: campaign's name
        value_proposition: Campaign value proposition
    
    Returns:
        Concise email draft
    """
    prompt = f"Write a brief, direct outreach email to {name} about: {value_proposition}"
    
    try:
        result = await Runner.run(concise_agent, prompt)
        return result.final_output
    except Exception as e:
        logger.error(f"Concise email generation failed: {e}")
        return OutreachEmailDraft(
            subject=f"{value_proposition} - Quick Question",
            body=f"Hi,\n\nCan we help with {value_proposition}?\n\n5-minute call?\n\nBest"
        )