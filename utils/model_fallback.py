"""Utility for AI model provider fallback management."""

import logging
import os
from typing import Any, Dict, List, Optional, Type, Tuple
from pydantic import BaseModel

from agents import Agent, ModelSettings, Runner, set_default_openai_key, trace, gen_trace_id
from agents.models.openai_provider import OpenAIProvider
from config import settings

logger = logging.getLogger(__name__)

# Set OpenAI API key for agents library if not already in environment
if settings.openai_api_key:
    # Ensure it's in environment for underlying SDKs
    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    # Set it for the agents library tracing and default operations
    set_default_openai_key(settings.openai_api_key)

class ModelProviderInfo(BaseModel):
    """Information about a model provider."""
    name: str
    model: str
    provider: Optional[Any] = None

def get_available_providers() -> List[ModelProviderInfo]:
    """Get list of available model providers based on configured API keys."""
    providers = []
    
    # 1. OpenAI (Primary)
    if settings.openai_api_key:
        providers.append(ModelProviderInfo(
            name="OpenAI",
            model=settings.outreach_model,
            provider=None
        ))
        
    # 2. OpenRouter (Strong Open Source Fallback)
    if settings.openrouter_api_key:
        providers.append(ModelProviderInfo(
            name="OpenRouter",
            model="meta-llama/llama-3.3-70b-instruct",
            provider=OpenAIProvider(
                api_key=settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                use_responses=False
            )
        ))
        
    # 3. Cerebras (Fast Open Source Fallback)
    if settings.cerebras_api_key:
        providers.append(ModelProviderInfo(
            name="Cerebras",
            model="llama3.1-8b",
            provider=OpenAIProvider(
                api_key=settings.cerebras_api_key,
                base_url="https://api.cerebras.ai/v1",
                use_responses=False
            )
        ))
        
    # 4. Groq (Fast Open Source Fallback)
    if settings.groq_api_key:
        providers.append(ModelProviderInfo(
            name="Groq",
            model="llama-3.3-70b-versatile",
            provider=OpenAIProvider(
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
                use_responses=False
            )
        ))
        
    return providers

async def run_agent_with_fallback(
    name: str,
    instructions: str,
    prompt: str,
    output_type: Optional[Type[BaseModel]] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Any]] = None
) -> Tuple[Any, str]:
    """Run an agent with automatic provider fallback and detailed tracing.
    
    Returns:
        Tuple of (result_output, provider_name)
    """
    providers = get_available_providers()
    
    if not providers:
        raise RuntimeError(
            "Configuration Error: No API keys found for any supported AI provider. "
            "Please set at least one of OPENAI_API_KEY, OPENROUTER_API_KEY, "
            "CEREBRAS_API_KEY, or GROQ_API_KEY in your .env file."
        )

    errors = []
    # Use structured trace with gen_trace_id to match origin code style
    trace_id = gen_trace_id()
    
    with trace(
        workflow_name=f"{name}_with_fallback_pipeline",
        trace_id=trace_id,
        metadata={"prompt": prompt, "agent_name": name}
    ):
        for p_info in providers:
            try:
                # Nested trace for each provider attempt (though nested traces are discouraged, 
                # we can use trace metadata or individual spans if needed. 
                # For now, let's stick to the simplest valid call)
                logger.info(f"Attempting {name} with {p_info.name} model: {p_info.model}")
                
                # Setup model instance
                model_instance = p_info.provider.get_model(p_info.model) if p_info.provider else p_info.model
                
                # Create a fresh agent for this provider
                agent = Agent(
                    name=name,
                    instructions=instructions,
                    model=model_instance,
                    model_settings=ModelSettings(
                        temperature=temperature if temperature is not None else settings.outreach_temperature,
                        max_tokens=max_tokens if max_tokens is not None else settings.outreach_max_tokens,
                    ),
                    output_type=output_type,
                    tools=tools or []
                )
                
                result = await Runner.run(agent, prompt)
                
                # Check for hallucinated success in tool-heavy agents
                if name == "SeniorMarketingAgent":
                    # If the agent didn't actually call any tools (just replied with text)
                    # The Llama3.1-8b model on Cerebras is prone to doing this
                    if not hasattr(result, 'tool_calls') or not result.tool_calls:
                        logger.warning(f"Model {p_info.model} hallucinated success without executing the required tools.")
                        raise ValueError(f"Model {p_info.model} hallucinated success without executing tools.")
                
                return result.final_output, p_info.name
                
            except Exception as e:
                error_msg = f"{p_info.name} ({p_info.model}) failed: {str(e)}"
                logger.warning(error_msg)
                errors.append(error_msg)

    # If all providers fail, raise a detailed error
    all_errors = "\n".join([f"- {err}" for err in errors])
    raise RuntimeError(
        f"All AI providers failed for {name}.\n"
        f"Detailed Provider Log:\n{all_errors}"
    )
