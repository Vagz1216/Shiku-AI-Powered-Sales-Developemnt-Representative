"""Utility for AI model provider fallback management."""

import logging
import os
from typing import Any, Dict, List, Optional, Type, Tuple
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agents import Agent, ModelSettings, Runner, set_default_openai_key
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
    base_url: Optional[str] = None

def get_available_providers() -> List[ModelProviderInfo]:
    """Get list of available model providers based on configured API keys."""
    providers = []
    
    # 1. OpenAI (Primary)
    if settings.openai_api_key:
        providers.append(ModelProviderInfo(
            name="OpenAI",
            model=settings.outreach_model
        ))
        
    # 2. OpenRouter (Strong Open Source Fallback)
    if settings.openrouter_api_key:
        providers.append(ModelProviderInfo(
            name="OpenRouter",
            model="meta-llama/llama-3.1-70b-instruct",
            provider=OpenAIProvider(
                api_key=settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                use_responses=False
            )
        ))
        
    # 3. Cerebras (Fast Inference)
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
        
    # 4. Groq (Fast Inference)
    if settings.groq_api_key:
        providers.append(ModelProviderInfo(
            name="Groq",
            model="llama-3.1-70b-versatile",
            provider=OpenAIProvider(
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
                use_responses=False
            )
        ))
        
    return providers

class ProviderExecutionError(Exception):
    """Raised when an execution fails for a retriable reason."""
    pass

class ProviderFatalError(Exception):
    """Raised when an execution fails for a non-retriable reason (e.g., Auth/Quota)."""
    pass

def is_fatal_error(e: Exception) -> bool:
    """Determine if an exception should skip retries and fail immediately to the next provider."""
    error_str = str(e).lower()
    
    # We do NOT want to retry on these errors, because retrying will just fail again and waste time.
    fatal_keywords = [
        "insufficient_quota", 
        "invalid_api_key", 
        "authentication_error", 
        "unauthorized",
        "billing_hard_limit",
        "context_length_exceeded"
    ]
    
    return any(keyword in error_str for keyword in fatal_keywords)


# Apply Tenacity retry decorator. It will only retry on ProviderExecutionError.
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(ProviderExecutionError),
    reraise=True
)
async def _execute_with_retry(agent: Agent, prompt: str) -> Any:
    """Executes the agent run, raising specific exceptions to control tenacity."""
    try:
        result = await Runner.run(agent, prompt)
        return result
    except Exception as e:
        if is_fatal_error(e):
            # Fatal error (like bad API key or out of credits). Do NOT retry.
            raise ProviderFatalError(str(e))
        else:
            # Likely a rate limit (429) or transient 502/503. Tenacity WILL retry this.
            raise ProviderExecutionError(str(e))


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
    
    for p_info in providers:
        try:
            logger.info(f"Attempting {name} with {p_info.name} model: {p_info.model}")
            
            # Create agent with appropriate provider configuration
            if p_info.provider:
                # Use custom provider (OpenRouter, Cerebras, Groq)
                agent = Agent(
                    name=name,
                    instructions=instructions,
                    model=p_info.model,
                    provider=p_info.provider,
                    model_settings=ModelSettings(
                        temperature=temperature if temperature is not None else settings.outreach_temperature,
                        max_tokens=max_tokens if max_tokens is not None else settings.outreach_max_tokens,
                    ),
                    output_type=output_type,
                    tools=tools or []
                )
            else:
                # Use default OpenAI provider
                agent = Agent(
                    name=name,
                    instructions=instructions,
                    model=p_info.model,
                    model_settings=ModelSettings(
                        temperature=temperature if temperature is not None else settings.outreach_temperature,
                        max_tokens=max_tokens if max_tokens is not None else settings.outreach_max_tokens,
                    ),
                    output_type=output_type,
                    tools=tools or []
                )
            
            # Execute with Tenacity retries (only for transient errors)
            result = await _execute_with_retry(agent, prompt)
            
            # Success - no need to validate tool calls as Runner.run handles execution
            logger.info(f"Agent {name} completed successfully with {p_info.name}")
            return result.final_output, p_info.name
        except ProviderFatalError as e:
            error_msg = f"{p_info.name} ({p_info.model}) failed FATALLY (skipping retries): {str(e)}"
            logger.warning(error_msg)
            errors.append(error_msg)
        except Exception as e:
            error_msg = f"{p_info.name} ({p_info.model}) failed after retries: {str(e)}"
            logger.warning(error_msg)
            errors.append(error_msg)

    # If all providers fail, raise a clear error
    all_errors = "\\n".join([f"  • {err}" for err in errors])
    raise RuntimeError(
        f"All AI providers failed for {name}.\\n"
        f"Provider attempts:\\n{all_errors}\\n\\n"
        f"Check your API keys and network connection."
    )
