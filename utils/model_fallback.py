"""Utility for AI model provider fallback management."""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Type, Tuple
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from openai import AsyncAzureOpenAI, AsyncOpenAI
from agents import Agent, ModelSettings, Runner, set_default_openai_key
from agents.models.openai_provider import OpenAIProvider
from config import settings
from config.logging import get_request_id
from services import metering_service, usage_service

logger = logging.getLogger(__name__)

# Simple in-memory blacklist for providers
# Format: {provider_name: expiry_timestamp}
_BLACKLIST = {}
_BLACKLIST_DURATION = 300  # 5 minutes

_OPENROUTER_PROVIDERS = {"Meta", "OpenRouter-Llama", "DeepSeek", "Google", "Anthropic"}


def blacklist_provider(name: str):
    """Temporarily blacklist a provider. If it's an OpenRouter provider,
    blacklist all OpenRouter providers since they share the same credits."""
    expiry = time.time() + _BLACKLIST_DURATION
    if name in _OPENROUTER_PROVIDERS:
        for or_name in _OPENROUTER_PROVIDERS:
            _BLACKLIST[or_name] = expiry
        logger.warning(f"All OpenRouter providers blacklisted for {_BLACKLIST_DURATION}s (triggered by {name})")
    else:
        _BLACKLIST[name] = expiry
        logger.warning(f"Provider {name} blacklisted for {_BLACKLIST_DURATION}s")

def is_blacklisted(name: str) -> bool:
    """Check if a provider is currently blacklisted."""
    if name not in _BLACKLIST:
        return False
    if time.time() > _BLACKLIST[name]:
        del _BLACKLIST[name]
        return False
    return True

# Set OpenAI API key for agents library if not already in environment
if settings.openai_api_key:
    # Ensure it's in environment for underlying SDKs
    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.openai_base_url and not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = settings.openai_base_url
    # Set it for the agents library tracing and default operations
    set_default_openai_key(settings.openai_api_key)

class ModelProviderInfo(BaseModel):
    """Information about a model provider."""
    name: str
    model: str
    provider: Optional[Any] = None
    base_url: Optional[str] = None

def _build_example_json(model_cls: Type[BaseModel]) -> dict:
    """Build a placeholder example dict from a Pydantic model so the LLM
    sees field names + expected types, NOT the raw JSON-Schema definition."""
    schema = model_cls.model_json_schema()
    props = schema.get("properties", {})
    example = {}
    for field_name, field_info in props.items():
        ftype = field_info.get("type", "string")
        desc = field_info.get("description", "")
        if ftype == "boolean":
            example[field_name] = True
        elif ftype == "integer":
            example[field_name] = 0
        elif ftype == "number":
            example[field_name] = 0.0
        elif ftype == "array":
            example[field_name] = []
        elif ftype == "object":
            example[field_name] = {}
        else:
            example[field_name] = f"<{desc[:60]}>" if desc else "<string>"
    return example


def _suffix(index: int) -> str:
    """Return '' for the first key, '-2', '-3', etc. for subsequent keys."""
    return "" if index == 0 else f"-{index + 1}"


def _make_provider(api_key: str, base_url: str) -> OpenAIProvider:
    """Build an OpenAIProvider with max_retries=0 to prevent the SDK from
    burning 27-44 seconds retrying 429s that won't recover in-session."""
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=0,
    )
    return OpenAIProvider(openai_client=client, use_responses=False)


def _azure_responses_base_url(endpoint: str) -> str:
    """Return Azure OpenAI v1 base URL for Responses API calls."""
    base = endpoint.rstrip("/")
    if base.endswith("/openai/v1"):
        return f"{base}/"
    if base.endswith("/openai"):
        return f"{base}/v1/"
    return f"{base}/openai/v1/"


def _make_azure_provider() -> OpenAIProvider:
    """Build an Azure OpenAI provider using the configured deployment."""
    if not (
        settings.azure_openai_api_key
        and settings.azure_openai_endpoint
        and settings.azure_openai_deployment
    ):
        raise ValueError("Azure OpenAI requires key, endpoint, and deployment")

    if settings.azure_openai_wire_api == "responses":
        client = AsyncOpenAI(
            api_key=settings.azure_openai_api_key,
            base_url=_azure_responses_base_url(settings.azure_openai_endpoint),
            max_retries=0,
        )
        return OpenAIProvider(openai_client=client, use_responses=True)

    client = AsyncAzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        azure_deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
        max_retries=0,
    )
    return OpenAIProvider(
        openai_client=client,
        use_responses=False,
    )


def _model_supports_temperature(model: str) -> bool:
    """Some reasoning/newer models reject temperature entirely."""
    model_lower = model.lower()
    unsupported_prefixes = ("gpt-5", "o1", "o3", "o4")
    return not model_lower.startswith(unsupported_prefixes)


def get_available_providers() -> List[ModelProviderInfo]:
    """Get list of available model providers based on configured API keys, skipping blacklisted ones.
    
    Supports multiple comma-separated API keys per provider (e.g. GROQ_API_KEY=key1,key2).
    Each key gets its own entry with a unique name (Groq, Groq-2, etc.) so each has
    an independent rate-limit budget.
    """
    providers = []

    all_configured = []
    if settings.azure_openai_api_key and settings.azure_openai_endpoint and settings.azure_openai_deployment:
        all_configured.append("AzureOpenAI")
    openai_provider_name = "OpenAICompatible" if settings.openai_base_url else "OpenAI"
    if settings.openai_api_key:
        all_configured.append(openai_provider_name)
    for i, _ in enumerate(settings.groq_api_keys):
        all_configured.append(f"Groq{_suffix(i)}")
    for i, _ in enumerate(settings.cerebras_api_keys):
        all_configured.append(f"Cerebras{_suffix(i)}")
    or_key = settings.openrouter_api_keys[0] if settings.openrouter_api_keys else None
    if or_key:
        all_configured.extend(["Meta", "OpenRouter-Llama", "DeepSeek", "Google", "Anthropic"])

    if all_configured and all(is_blacklisted(p) for p in all_configured):
        logger.warning("All providers blacklisted — clearing to attempt recovery.")
        _BLACKLIST.clear()

    # ── 1. AZURE OPENAI (primary when configured; enterprise quota and deployment control) ──
    if (
        settings.azure_openai_api_key
        and settings.azure_openai_endpoint
        and settings.azure_openai_deployment
        and not is_blacklisted("AzureOpenAI")
    ):
        providers.append(ModelProviderInfo(
            name="AzureOpenAI",
            model=settings.azure_openai_deployment,
            provider=_make_azure_provider(),
        ))

    # ── 2. OPENAI / OPENAI-COMPATIBLE (direct OpenAI or LiteLLM proxy) ──
    if settings.openai_api_key and not is_blacklisted(openai_provider_name):
        provider = _make_provider(settings.openai_api_key, settings.openai_base_url) if settings.openai_base_url else None
        providers.append(ModelProviderInfo(
            name=openai_provider_name,
            model=settings.outreach_model,
            provider=provider,
        ))

    # ── 3. GROQ (free, fast, 70B — good fallback but no json_schema) ──
    for i, key in enumerate(settings.groq_api_keys):
        name = f"Groq{_suffix(i)}"
        if not is_blacklisted(name):
            providers.append(ModelProviderInfo(
                name=name,
                model="llama-3.3-70b-versatile",
                provider=_make_provider(key, "https://api.groq.com/openai/v1"),
            ))

    # ── 4. CEREBRAS (free, ultra-fast, 8B — no tool calling) ──
    for i, key in enumerate(settings.cerebras_api_keys):
        name = f"Cerebras{_suffix(i)}"
        if not is_blacklisted(name):
            providers.append(ModelProviderInfo(
                name=name,
                model="llama3.1-8b",
                provider=_make_provider(key, "https://api.cerebras.ai/v1"),
            ))

    # ── 5. OPENROUTER MODELS (paid per token, shared credits) ──
    if or_key and not is_blacklisted("Meta"):
        providers.append(ModelProviderInfo(
            name="Meta",
            model="meta-llama/llama-4-maverick",
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
        ))
    if or_key and not is_blacklisted("OpenRouter-Llama"):
        providers.append(ModelProviderInfo(
            name="OpenRouter-Llama",
            model="meta-llama/llama-3.3-70b-instruct",
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
        ))
    if or_key and not is_blacklisted("DeepSeek"):
        providers.append(ModelProviderInfo(
            name="DeepSeek",
            model="deepseek/deepseek-v3.2",
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
        ))
    if or_key and not is_blacklisted("Google"):
        providers.append(ModelProviderInfo(
            name="Google",
            model="google/gemini-2.5-flash",
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
        ))
    if or_key and not is_blacklisted("Anthropic"):
        providers.append(ModelProviderInfo(
            name="Anthropic",
            model="anthropic/claude-sonnet-4.6",
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
        ))

    return providers

class ProviderExecutionError(Exception):
    """Raised when an execution fails for a retriable reason."""
    pass

class ProviderFatalError(Exception):
    """Raised when an execution fails for a non-retriable reason (e.g., Auth/Quota)."""
    pass

_FATAL_BLACKLIST_KEYWORDS = [
    "insufficient_quota", 
    "invalid_api_key", 
    "authentication_error", 
    "unauthorized",
    "billing_hard_limit",
    "402",
    "insufficient credits",
    "wrong_api_format",
    "model_decommissioned",
    "quota exceeded",
    "exceeded your current quota",
    "credit limit",
    "tokens per day",
]

_FATAL_SKIP_KEYWORDS = [
    "does not support response format",
    "no endpoints found",
    "context_length_exceeded",
    "404",
    "rate_limit_exceeded",
    "429",
    "too many requests",
]


def is_fatal_error(e: Exception) -> bool:
    """Determine if an exception should skip retries and fail immediately to the next provider."""
    error_str = str(e).lower()
    return any(kw in error_str for kw in _FATAL_BLACKLIST_KEYWORDS) or \
           any(kw in error_str for kw in _FATAL_SKIP_KEYWORDS)


def should_blacklist(e: Exception) -> bool:
    """Return True if the error indicates the provider is broken for ALL agents (e.g. bad API key, quota)."""
    error_str = str(e).lower()
    return any(kw in error_str for kw in _FATAL_BLACKLIST_KEYWORDS)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=1, max=4),
    retry=retry_if_exception_type(ProviderExecutionError),
    reraise=True,
)
async def _execute_with_retry(agent: Agent, prompt: str) -> Any:
    """Execute agent run with minimal retries; fatal/rate-limit errors skip immediately."""
    try:
        result = await Runner.run(agent, prompt)
        return result
    except Exception as e:
        if is_fatal_error(e):
            raise ProviderFatalError(str(e))
        raise ProviderExecutionError(str(e))


async def run_agent_with_fallback(
    name: str,
    instructions: str,
    prompt: str,
    output_type: Optional[Type[BaseModel]] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Any]] = None,
    organization_id: Optional[int] = None,
) -> Tuple[Any, str]:
    """Run an agent with automatic provider fallback and detailed tracing.
    
    Returns:
        Tuple of (result_output, provider_name)
    """
    providers = get_available_providers()

    if tools:
        before = len(providers)
        providers = [p for p in providers if not p.name.startswith("Cerebras")]
        if before != len(providers):
            logger.info(f"Skipped {before - len(providers)} Cerebras provider(s) (no tool-call support) for {name}")

    if output_type is not None:
        before = len(providers)
        providers = [p for p in providers if not p.name.startswith("Groq")]
        if before != len(providers):
            logger.info(f"Skipped {before - len(providers)} Groq provider(s) (no json_schema support) for {name}")

    provider_names = [p.name for p in providers]
    logger.info(f"Starting {name} with providers: {provider_names}")
    
    if not providers:
        raise RuntimeError(
            "Configuration Error: No API keys found for any supported AI provider. "
            "Please set Azure OpenAI (AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_DEPLOYMENT) or at least one of OPENAI_API_KEY, OPENROUTER_API_KEY, "
            "CEREBRAS_API_KEY, or GROQ_API_KEY in your .env file."
        )

    errors = []
    
    for p_info in providers:
        attempt_started = time.perf_counter()
        try:
            logger.info(f"Attempting {name} with {p_info.name} model: {p_info.model}")

            model_settings = {
                "max_tokens": max_tokens if max_tokens is not None else settings.outreach_max_tokens,
            }
            if _model_supports_temperature(p_info.model):
                model_settings["temperature"] = (
                    temperature if temperature is not None else settings.outreach_temperature
                )
            else:
                logger.info(f"Skipping temperature for {p_info.name} model {p_info.model} (unsupported)")
            ms = ModelSettings(**model_settings)
            agent = Agent(
                name=name,
                instructions=instructions,
                model=p_info.provider.get_model(p_info.model) if p_info.provider else p_info.model,
                model_settings=ms,
                output_type=output_type,
                tools=tools or [],
            )
            
            result = await _execute_with_retry(agent, prompt)
            latency_ms = (time.perf_counter() - attempt_started) * 1000
            usage = usage_service.extract_usage(result)
            tool_call_count = usage_service.count_tool_calls(result)
            fallback_triggered = bool(errors) or p_info.name != provider_names[0]
            ai_action_id = metering_service.get_current_ai_action_id()
            user_id = metering_service.get_current_user_id()
            if organization_id and ai_action_id is None:
                action_type, credits_used = metering_service.action_defaults_for_agent(name)
                try:
                    action = metering_service.record_ai_usage_action(
                        organization_id=organization_id,
                        user_id=user_id,
                        request_id=get_request_id(),
                        action_type=action_type,
                        credits_used=credits_used,
                        source_object_type="agent",
                        source_object_id=name,
                        metadata={
                            "agent_name": name,
                            "provider": p_info.name,
                            "model": p_info.model,
                            "fallback_triggered": fallback_triggered,
                        },
                    )
                    ai_action_id = int(action["id"]) if action.get("id") else None
                except Exception as metering_error:
                    logger.warning(f"Failed to record AI usage action for {name}: {metering_error}")
            try:
                usage_record = usage_service.record_llm_usage(
                    organization_id=organization_id,
                    user_id=user_id,
                    ai_usage_action_id=ai_action_id,
                    request_id=get_request_id(),
                    agent_name=name,
                    provider=p_info.name,
                    model=p_info.model,
                    usage=usage,
                    latency_ms=latency_ms,
                    fallback_triggered=fallback_triggered,
                    attempt_count=len(errors) + 1,
                    tool_call_count=tool_call_count,
                )
            except Exception as usage_error:
                usage_record = {"estimated_cost_usd": None, "pricing_source": "record_failed"}
                logger.warning(f"Failed to record LLM usage for {name}: {usage_error}")
            logger.info(
                f"Agent {name} completed successfully with {p_info.name}",
                extra={
                    "kind": "agent_output",
                    "component": name,
                    "provider": p_info.name,
                    "model": p_info.model,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                    "latency_ms": round(latency_ms, 2),
                    "estimated_cost_usd": usage_record.get("estimated_cost_usd"),
                    "fallback_triggered": fallback_triggered,
                },
            )
            
            if tools and hasattr(result, 'new_items'):
                tool_calls = {}
                for item in result.new_items:
                    item_type = type(item).__name__
                    if item_type == "ToolCallItem":
                        cid = getattr(item.raw_item, "call_id", None) or getattr(item.raw_item, "id", None)
                        tool_name = getattr(item.raw_item, "name", None)
                        if not tool_name and hasattr(item.raw_item, "function"):
                            tool_name = item.raw_item.function.name
                        if cid and tool_name:
                            tool_calls[cid] = {"name": tool_name, "success": False}
                    elif item_type == "ToolCallOutputItem":
                        cid = getattr(item.raw_item, "call_id", None)
                        if not cid and isinstance(item.raw_item, dict):
                            cid = item.raw_item.get("call_id") or item.raw_item.get("tool_call_id")
                        if cid in tool_calls:
                            tool_calls[cid]["success"] = True
                            
                successful_tools = [d["name"] for d in tool_calls.values() if d["success"]]
                failed_tools = [d["name"] for d in tool_calls.values() if not d["success"]]
                
                if failed_tools:
                    logger.warning(
                        f"Agent {name} had {len(failed_tools)} failed tool calls: {failed_tools}",
                        extra={
                            "kind": "agent_tool_call",
                            "component": name,
                            "failed_tools": failed_tools,
                            "successful_tools": successful_tools,
                        },
                    )
                elif tool_calls:
                    logger.info(
                        f"Agent {name} successfully executed {len(successful_tools)} tool calls",
                        extra={
                            "kind": "agent_tool_call",
                            "component": name,
                            "successful_tools": successful_tools,
                        },
                    )

            return result, p_info.name
        except ProviderFatalError as e:
            if should_blacklist(e):
                error_msg = f"{p_info.name} ({p_info.model}) failed FATALLY (blacklisted): {str(e)}"
                blacklist_provider(p_info.name)
            else:
                error_msg = f"{p_info.name} ({p_info.model}) failed FATALLY (skipping retries): {str(e)}"
            logger.warning(
                error_msg,
                extra={
                    "kind": "provider_fallback",
                    "component": name,
                    "provider": p_info.name,
                    "model": p_info.model,
                    "error": str(e),
                },
            )
            errors.append(error_msg)
        except Exception as e:
            error_msg = f"{p_info.name} ({p_info.model}) failed after retries: {str(e)}"
            logger.warning(
                error_msg,
                extra={
                    "kind": "provider_fallback",
                    "component": name,
                    "provider": p_info.name,
                    "model": p_info.model,
                    "error": str(e),
                },
            )
            errors.append(error_msg)

    # If all providers fail, raise a clear error
    all_errors = "\\n".join([f"  • {err}" for err in errors])
    raise RuntimeError(
        f"All AI providers failed for {name}.\\n"
        f"Provider attempts:\\n{all_errors}\\n\\n"
        f"Check your API keys and network connection."
    )
