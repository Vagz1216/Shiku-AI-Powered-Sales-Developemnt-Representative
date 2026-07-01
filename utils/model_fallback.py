"""Utility for AI model provider fallback management."""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, Tuple
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from langfuse.openai import AsyncAzureOpenAI, AsyncOpenAI
from langfuse import get_client, observe
from openai._base_client import AsyncHttpxClientWrapper
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

_OPENROUTER_PROVIDERS = {"Meta", "OpenRouter-Llama", "DeepSeek", "Google", "OpenRouter-Auto"}


def _patch_openai_async_httpx_del() -> None:
    """Guard OpenAI's async HTTP wrapper destructor against partial init.

    Some OpenAI/Langfuse/Agents paths can leave a temporary AsyncHttpxClientWrapper
    object partially initialized while the actual request succeeds. Its __del__
    then reads `is_closed`, which can raise AttributeError for missing `_state`
    and prints noisy "Exception ignored in..." messages to stderr. Keep the
    original behavior for normal instances and suppress only that broken cleanup
    path.
    """
    if getattr(AsyncHttpxClientWrapper, "_sdr_safe_del_patched", False):
        return
    original_del = AsyncHttpxClientWrapper.__del__

    def safe_del(self) -> None:
        try:
            original_del(self)
        except AttributeError as exc:
            if "_state" not in str(exc):
                raise

    AsyncHttpxClientWrapper.__del__ = safe_del
    AsyncHttpxClientWrapper._sdr_safe_del_patched = True


_patch_openai_async_httpx_del()


def _update_langfuse_span(**kwargs) -> None:
    """Attach useful metadata to the current Langfuse observation when enabled."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return
    try:
        get_client().update_current_span(**kwargs)
    except Exception as exc:
        logger.debug("Failed to update Langfuse span metadata: %s", exc)


def _trace_metadata_value(value: Any) -> Any:
    """Keep trace metadata compatible with strict exporters."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return "" if value is None else str(value)
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_trace_metadata_value(item) for item in value)
    return str(value)


def _trace_metadata(values: dict[str, Any]) -> dict[str, str]:
    return {key: _trace_metadata_value(value) for key, value in values.items()}


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
    transport: str = "openai_agents_default"
    api_compatibility: str = "openai"
    billing_source: str = "platform"
    provider_credential_id: Optional[int] = None


@dataclass(frozen=True)
class AgentFallbackProfile:
    """Routing preferences for an agent class.

    quality_order preserves the current enterprise hierarchy by default.
    balanced_order is the recommended production middle ground.
    cost_order is opt-in through LLM_ROUTING_MODE=cost_optimized and moves
    cheaper providers earlier where the task can tolerate it.
    """

    quality_order: tuple[str, ...]
    balanced_order: tuple[str, ...]
    cost_order: tuple[str, ...]
    rationale: str
    task_class: str
    cost_sensitivity: str
    capability_requirement: str
    default_temperature: Optional[float] = None
    default_max_tokens: Optional[int] = None


_PLATFORM_PROVIDER_ORDER = (
    "AzureOpenAI",
    "AzureDeepSeek",
    "OpenAI",
    "OpenAICompatible",
    "Groq",
    "Cerebras",
    "Gemini",
    "Meta",
    "OpenRouter-Llama",
    "DeepSeek",
    "Google",
    "OpenRouter-Auto",
)

_QUALITY_REPLY_ORDER = (
    "AzureOpenAI",
    "AzureDeepSeek",
    "OpenAI",
    "OpenAICompatible",
    "Gemini",
    "Cerebras",
    "Meta",
    "OpenRouter-Llama",
    "DeepSeek",
    "Google",
    "OpenRouter-Auto",
)

_CHEAP_STRUCTURED_ORDER = (
    "Cerebras",
    "Gemini",
    "AzureOpenAI",
    "OpenAI",
    "OpenAICompatible",
    "Meta",
    "OpenRouter-Llama",
    "DeepSeek",
    "Google",
    "OpenRouter-Auto",
)

_BALANCED_STRUCTURED_ORDER = (
    "Gemini",
    "Cerebras",
    "AzureOpenAI",
    "OpenAI",
    "OpenAICompatible",
    "Meta",
    "OpenRouter-Llama",
    "DeepSeek",
    "Google",
    "OpenRouter-Auto",
)

_BALANCED_WRITING_ORDER = (
    "AzureDeepSeek",
    "Gemini",
    "AzureOpenAI",
    "OpenAI",
    "OpenAICompatible",
    "Cerebras",
    "OpenRouter-Auto",
    "Meta",
    "OpenRouter-Llama",
    "DeepSeek",
    "Google",
)

_AGENT_FALLBACK_PROFILES: dict[str, AgentFallbackProfile] = {
    "DrafterAgent": AgentFallbackProfile(
        quality_order=_QUALITY_REPLY_ORDER,
        balanced_order=_BALANCED_WRITING_ORDER,
        cost_order=("Gemini", "Cerebras", "AzureOpenAI", "OpenAI", "OpenAICompatible", "OpenRouter-Auto", "Meta", "OpenRouter-Llama", "DeepSeek", "Google"),
        rationale="Outbound copy is user-facing and benefits from stronger generation quality; cost mode tries cheaper structured-capable generators first.",
        task_class="outbound_generation",
        cost_sensitivity="medium",
        capability_requirement="structured JSON output, strong writing quality",
        default_temperature=0.7,
        default_max_tokens=2000,
    ),
    "ReviewerAgent": AgentFallbackProfile(
        quality_order=_QUALITY_REPLY_ORDER,
        balanced_order=_BALANCED_STRUCTURED_ORDER,
        cost_order=_CHEAP_STRUCTURED_ORDER,
        rationale="Review is a deterministic quality gate; cost mode prioritizes Cerebras before Gemini after Gemini showed weaker strict-JSON reliability on review output.",
        task_class="outbound_quality_gate",
        cost_sensitivity="high",
        capability_requirement="structured JSON output, conservative evaluation",
        default_temperature=0.2,
        default_max_tokens=800,
    ),
    "EmailIntentExtractor": AgentFallbackProfile(
        quality_order=_PLATFORM_PROVIDER_ORDER,
        balanced_order=_BALANCED_STRUCTURED_ORDER,
        cost_order=_CHEAP_STRUCTURED_ORDER,
        rationale="Intent classification is short, structured, and often zero-cost via quick-reply fast path; cost mode prioritizes cheap structured models.",
        task_class="classification",
        cost_sensitivity="high",
        capability_requirement="structured JSON output, low temperature",
        default_temperature=0.1,
        default_max_tokens=100,
    ),
    "LlamaGuardAgent": AgentFallbackProfile(
        quality_order=_QUALITY_REPLY_ORDER,
        balanced_order=("AzureOpenAI", "OpenAI", "OpenAICompatible", "Gemini", "Cerebras", "OpenRouter-Auto", "Meta", "OpenRouter-Llama", "DeepSeek", "Google"),
        cost_order=("AzureOpenAI", "OpenAI", "OpenAICompatible", "Gemini", "Cerebras", "OpenRouter-Auto", "Meta", "OpenRouter-Llama", "DeepSeek", "Google"),
        rationale="Safety checks fail closed, so reliability outranks marginal cost savings even in cost mode.",
        task_class="safety_gate",
        cost_sensitivity="low",
        capability_requirement="structured JSON output, conservative safety classification",
        default_temperature=0.1,
        default_max_tokens=300,
    ),
    "EmailResponseAgent": AgentFallbackProfile(
        quality_order=_QUALITY_REPLY_ORDER,
        balanced_order=_BALANCED_WRITING_ORDER,
        cost_order=("Gemini", "Cerebras", "AzureOpenAI", "OpenAI", "OpenAICompatible", "OpenRouter-Auto", "Meta", "OpenRouter-Llama", "DeepSeek", "Google"),
        rationale="Inbound replies are user-facing and context-sensitive; cost mode still uses capable structured models before free routers.",
        task_class="inbound_reply_generation",
        cost_sensitivity="medium",
        capability_requirement="structured JSON output, strong contextual writing",
        default_temperature=0.7,
        default_max_tokens=1000,
    ),
    "EmailResponseEvaluator": AgentFallbackProfile(
        quality_order=_QUALITY_REPLY_ORDER,
        balanced_order=_BALANCED_STRUCTURED_ORDER,
        cost_order=_CHEAP_STRUCTURED_ORDER,
        rationale="Reply evaluation is a short structured quality gate; cost mode prioritizes Cerebras before Gemini for stricter JSON reliability.",
        task_class="inbound_quality_gate",
        cost_sensitivity="high",
        capability_requirement="structured JSON output, conservative approval decision",
        default_temperature=0.2,
        default_max_tokens=300,
    ),
    "EmailSenderAgent": AgentFallbackProfile(
        quality_order=("AzureOpenAI", "AzureDeepSeek", "OpenAI", "OpenAICompatible", "Gemini", "Meta", "OpenRouter-Llama", "DeepSeek", "Google", "OpenRouter-Auto"),
        balanced_order=("AzureOpenAI", "AzureDeepSeek", "OpenAI", "OpenAICompatible", "Gemini", "OpenRouter-Auto", "Meta", "OpenRouter-Llama", "DeepSeek", "Google"),
        cost_order=("AzureOpenAI", "AzureDeepSeek", "OpenAI", "OpenAICompatible", "Gemini", "OpenRouter-Auto", "Meta", "OpenRouter-Llama", "DeepSeek", "Google"),
        rationale="The sender agent can call tools with external side effects, so proven tool-call support is prioritized over lowest token cost.",
        task_class="tool_orchestration",
        cost_sensitivity="low",
        capability_requirement="tool calling, instruction following",
        default_temperature=0.3,
        default_max_tokens=1024,
    ),
}


async def _close_provider_clients(providers: list[ModelProviderInfo]) -> None:
    """Close async SDK clients owned by provider wrappers.

    Providers are constructed per fallback run. If a run succeeds with the first
    provider, every later provider's async HTTP client would otherwise be left to
    Python garbage collection, which can emit noisy OpenAI/httpx __del__ errors.
    """
    closed: set[int] = set()
    for provider_info in providers:
        provider = provider_info.provider
        if provider is None:
            continue
        provider_id = id(provider)
        if provider_id in closed:
            continue
        closed.add(provider_id)
        close = getattr(provider, "aclose", None)
        try:
            if close is not None:
                await close()
            raw_client = getattr(provider, "_client", None)
            raw_close = getattr(raw_client, "close", None)
            if raw_close is not None:
                await raw_close()
        except Exception as exc:
            logger.debug("Could not close provider %s client: %s", provider_info.name, exc)


def _skipped_providers(
    before: list[ModelProviderInfo],
    after: list[ModelProviderInfo],
) -> list[ModelProviderInfo]:
    retained_ids = {id(provider) for provider in after}
    return [provider for provider in before if id(provider) not in retained_ids]


def _provider_family_name(name: str) -> str:
    if name.startswith("Org"):
        name = name.removeprefix("Org")
    if name.startswith("Groq"):
        return "Groq"
    if name.startswith("Cerebras"):
        return "Cerebras"
    if name == "OpenRouter":
        return "OpenRouter-Auto"
    return name


def get_agent_fallback_profile(name: str) -> AgentFallbackProfile:
    return _AGENT_FALLBACK_PROFILES.get(
        name,
        AgentFallbackProfile(
            quality_order=_PLATFORM_PROVIDER_ORDER,
            balanced_order=_PLATFORM_PROVIDER_ORDER,
            cost_order=_PLATFORM_PROVIDER_ORDER,
            rationale="Default platform provider hierarchy for uncategorized agents.",
            task_class="general",
            cost_sensitivity="medium",
            capability_requirement="general LLM capability",
        ),
    )


def _ordered_providers_for_agent(
    providers: list[ModelProviderInfo],
    profile: AgentFallbackProfile,
    routing_mode: str | None = None,
) -> list[ModelProviderInfo]:
    routing_mode = routing_mode or _active_llm_routing_mode()
    if routing_mode == "cost_optimized":
        configured_order = profile.cost_order
    elif routing_mode == "balanced":
        configured_order = profile.balanced_order
    else:
        configured_order = profile.quality_order
    order_index = {name: index for index, name in enumerate(configured_order)}

    def sort_key(item: tuple[int, ModelProviderInfo]) -> tuple[int, int]:
        original_index, provider = item
        family = _provider_family_name(provider.name)
        return (order_index.get(provider.name, order_index.get(family, len(order_index))), original_index)

    return [provider for _, provider in sorted(enumerate(providers), key=sort_key)]


def _active_llm_routing_mode() -> str:
    try:
        from services import platform_settings_service

        return platform_settings_service.get_llm_routing_mode()
    except Exception:
        return settings.llm_routing_mode


def _effective_llm_routing_policy(organization_id: int | None = None) -> dict[str, Any]:
    try:
        from services import platform_settings_service

        return platform_settings_service.get_effective_llm_routing_policy(organization_id)
    except Exception:
        mode = _active_llm_routing_mode()
        return {
            "requested_mode": mode,
            "default_mode": mode,
            "resolved_mode": mode,
            "allowed_modes": ["cost_optimized", "balanced", "quality_first"],
            "plan_id": None,
            "plan_name": None,
            "plan_slug": None,
            "plan_currency_code": None,
            "plan_market_code": None,
            "plan_allow_byok": None,
            "plan_byok_provider_mode": None,
            "subscription_status": None,
            "downgraded": False,
        }

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


def _make_provider(api_key: str, base_url: str | None = None) -> OpenAIProvider:
    """Build an OpenAIProvider with max_retries=0 to prevent the SDK from
    burning 27-44 seconds retrying 429s that won't recover in-session."""
    kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)
    return OpenAIProvider(openai_client=client, use_responses=False)


def _azure_responses_base_url(endpoint: str) -> str:
    """Return Azure OpenAI v1 base URL for Responses API calls."""
    base = endpoint.rstrip("/")
    if base.endswith("/openai/v1"):
        return f"{base}/"
    if base.endswith("/openai"):
        return f"{base}/v1/"
    return f"{base}/openai/v1/"


def _make_azure_provider(
    api_key: str | None = None,
    endpoint: str | None = None,
    deployment: str | None = None,
    api_version: str | None = None,
    wire_api: str | None = None,
) -> OpenAIProvider:
    """Build an Azure OpenAI provider using the configured deployment."""
    resolved_api_key = api_key or settings.azure_openai_api_key
    resolved_endpoint = endpoint or settings.azure_openai_endpoint
    resolved_deployment = deployment or settings.azure_openai_deployment
    resolved_api_version = api_version or settings.azure_openai_api_version
    resolved_wire_api = wire_api or settings.azure_openai_wire_api
    if not (
        resolved_api_key
        and resolved_endpoint
        and resolved_deployment
    ):
        raise ValueError("Azure OpenAI requires key, endpoint, and deployment")

    if resolved_wire_api == "responses":
        client = AsyncOpenAI(
            api_key=resolved_api_key,
            base_url=_azure_responses_base_url(resolved_endpoint),
            max_retries=0,
        )
        return OpenAIProvider(openai_client=client, use_responses=True)

    client = AsyncAzureOpenAI(
        api_key=resolved_api_key,
        azure_endpoint=resolved_endpoint,
        azure_deployment=resolved_deployment,
        api_version=resolved_api_version,
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


def _organization_provider_infos(organization_id: int | None) -> tuple[list[ModelProviderInfo], dict[str, Any]]:
    try:
        from services import llm_credential_service

        credentials, policy = llm_credential_service.list_active_provider_credentials(organization_id)
    except Exception as exc:
        logger.warning("Could not load organization LLM credentials: %s", exc)
        return [], {"enabled": False, "provider_mode": settings.organization_llm_provider_mode}

    providers: list[ModelProviderInfo] = []
    for credential in credentials:
        api_key = credential.get("api_key")
        provider = credential.get("provider")
        model = credential.get("default_model")
        credential_id = int(credential["id"])
        if not api_key or not model:
            continue
        if provider == "azure_openai":
            name = "OrgAzureOpenAI"
            if is_blacklisted(name):
                continue
            providers.append(ModelProviderInfo(
                name=name,
                model=model,
                provider=_make_azure_provider(
                    api_key=api_key,
                    endpoint=credential.get("azure_endpoint"),
                    deployment=credential.get("azure_deployment") or model,
                    api_version=credential.get("azure_api_version"),
                ),
                base_url=credential.get("azure_endpoint"),
                transport="azure_openai",
                api_compatibility="azure_openai",
                billing_source="organization",
                provider_credential_id=credential_id,
            ))
        elif provider == "openai":
            name = "OrgOpenAICompatible" if credential.get("base_url") else "OrgOpenAI"
            if is_blacklisted(name):
                continue
            providers.append(ModelProviderInfo(
                name=name,
                model=model,
                provider=_make_provider(api_key, credential.get("base_url")),
                base_url=credential.get("base_url"),
                transport="openai_compatible" if credential.get("base_url") else "openai",
                api_compatibility="openai",
                billing_source="organization",
                provider_credential_id=credential_id,
            ))
        elif provider == "gemini":
            name = "OrgGemini"
            if is_blacklisted(name):
                continue
            providers.append(ModelProviderInfo(
                name=name,
                model=model,
                provider=_make_provider(api_key, credential.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai/"),
                base_url=credential.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai/",
                transport="openai_compatible",
                api_compatibility="openai",
                billing_source="organization",
                provider_credential_id=credential_id,
            ))
        elif provider == "groq":
            name = "OrgGroq"
            if is_blacklisted(name):
                continue
            providers.append(ModelProviderInfo(
                name=name,
                model=model,
                provider=_make_provider(api_key, credential.get("base_url") or "https://api.groq.com/openai/v1"),
                base_url=credential.get("base_url") or "https://api.groq.com/openai/v1",
                transport="openai_compatible",
                api_compatibility="openai",
                billing_source="organization",
                provider_credential_id=credential_id,
            ))
        elif provider == "cerebras":
            name = "OrgCerebras"
            if is_blacklisted(name):
                continue
            providers.append(ModelProviderInfo(
                name=name,
                model=model,
                provider=_make_provider(api_key, credential.get("base_url") or "https://api.cerebras.ai/v1"),
                base_url=credential.get("base_url") or "https://api.cerebras.ai/v1",
                transport="openai_compatible",
                api_compatibility="openai",
                billing_source="organization",
                provider_credential_id=credential_id,
            ))
        elif provider == "openrouter":
            name = "OrgOpenRouter"
            if is_blacklisted(name):
                continue
            providers.append(ModelProviderInfo(
                name=name,
                model=model,
                provider=_make_provider(api_key, credential.get("base_url") or "https://openrouter.ai/api/v1"),
                base_url=credential.get("base_url") or "https://openrouter.ai/api/v1",
                transport="openai_compatible",
                api_compatibility="openai",
                billing_source="organization",
                provider_credential_id=credential_id,
            ))
    return providers, policy


def get_available_providers(organization_id: int | None = None) -> List[ModelProviderInfo]:
    """Get list of available model providers based on configured API keys, skipping blacklisted ones.
    
    Supports multiple comma-separated API keys per provider (e.g. GROQ_API_KEY=key1,key2).
    Each key gets its own entry with a unique name (Groq, Groq-2, etc.) so each has
    an independent rate-limit budget.
    """
    providers = []

    all_configured = []
    if settings.azure_openai_api_key and settings.azure_openai_endpoint and settings.azure_openai_deployment:
        all_configured.append("AzureOpenAI")
    if settings.azure_deepseek_api_key and settings.azure_deepseek_endpoint:
        all_configured.append("AzureDeepSeek")
    openai_provider_name = "OpenAICompatible" if settings.openai_base_url else "OpenAI"
    if settings.openai_api_key:
        all_configured.append(openai_provider_name)
    for i, _ in enumerate(settings.groq_api_keys):
        all_configured.append(f"Groq{_suffix(i)}")
    for i, _ in enumerate(settings.cerebras_api_keys):
        all_configured.append(f"Cerebras{_suffix(i)}")
    if settings.gemini_api_key:
        all_configured.append("Gemini")
    or_key = settings.openrouter_api_keys[0] if settings.openrouter_api_keys else None
    if or_key:
        all_configured.extend(["Meta", "OpenRouter-Llama", "DeepSeek", "Google", "OpenRouter-Auto"])

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
            base_url=settings.azure_openai_endpoint,
            transport="azure_openai" if settings.azure_openai_wire_api != "responses" else "openai_compatible",
            api_compatibility="azure_openai" if settings.azure_openai_wire_api != "responses" else "openai_responses",
        ))

    # --- 1b. AZURE DEEPSEEK (Serverless API) ---
    if (
        settings.azure_deepseek_api_key
        and settings.azure_deepseek_endpoint
        and not is_blacklisted("AzureDeepSeek")
    ):
        providers.append(ModelProviderInfo(
            name="AzureDeepSeek",
            model=settings.azure_deepseek_model,
            provider=_make_provider(
                api_key=settings.azure_deepseek_api_key,
                base_url=settings.azure_deepseek_endpoint.rstrip("/") + "/v1"
            ),
            base_url=settings.azure_deepseek_endpoint,
            transport="openai_compatible",
            api_compatibility="openai",
        ))

    # ── 2. OPENAI / OPENAI-COMPATIBLE (direct OpenAI or LiteLLM proxy) ──
    if settings.openai_api_key and not is_blacklisted(openai_provider_name):
        provider = _make_provider(settings.openai_api_key, settings.openai_base_url) if settings.openai_base_url else None
        providers.append(ModelProviderInfo(
            name=openai_provider_name,
            model=settings.outreach_model,
            provider=provider,
            base_url=settings.openai_base_url,
            transport="openai_compatible" if settings.openai_base_url else "openai_agents_default",
            api_compatibility="openai",
        ))

    # ── 3. GROQ (free, fast, 70B — good fallback but no json_schema) ──
    for i, key in enumerate(settings.groq_api_keys):
        name = f"Groq{_suffix(i)}"
        if not is_blacklisted(name):
            providers.append(ModelProviderInfo(
                name=name,
                model=settings.groq_model,
                provider=_make_provider(key, "https://api.groq.com/openai/v1"),
                base_url="https://api.groq.com/openai/v1",
                transport="openai_compatible",
                api_compatibility="openai",
            ))

    # ── 4. CEREBRAS (free, ultra-fast, 8B — no tool calling) ──
    for i, key in enumerate(settings.cerebras_api_keys):
        name = f"Cerebras{_suffix(i)}"
        if not is_blacklisted(name):
            providers.append(ModelProviderInfo(
                name=name,
                model=settings.cerebras_model,
                provider=_make_provider(key, "https://api.cerebras.ai/v1"),
                base_url="https://api.cerebras.ai/v1",
                transport="openai_compatible",
                api_compatibility="openai",
            ))

    # ── 4.5. GOOGLE GEMINI (native API) ──
    if settings.gemini_api_key and not is_blacklisted("Gemini"):
        providers.append(ModelProviderInfo(
            name="Gemini",
            model=settings.gemini_model,
            provider=_make_provider(settings.gemini_api_key, "https://generativelanguage.googleapis.com/v1beta/openai/"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            transport="openai_compatible",
            api_compatibility="openai",
        ))

    # ── 5. OPENROUTER MODELS (free tier) ──
    if or_key and not is_blacklisted("Meta"):
        providers.append(ModelProviderInfo(
            name="Meta",
            model=settings.openrouter_meta_model,
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
            base_url="https://openrouter.ai/api/v1",
            transport="openai_compatible",
            api_compatibility="openai",
        ))
    if or_key and not is_blacklisted("OpenRouter-Llama"):
        providers.append(ModelProviderInfo(
            name="OpenRouter-Llama",
            model=settings.openrouter_llama_model,
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
            base_url="https://openrouter.ai/api/v1",
            transport="openai_compatible",
            api_compatibility="openai",
        ))
    if or_key and not is_blacklisted("DeepSeek"):
        providers.append(ModelProviderInfo(
            name="DeepSeek",
            model=settings.openrouter_deepseek_model,
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
            base_url="https://openrouter.ai/api/v1",
            transport="openai_compatible",
            api_compatibility="openai",
        ))
    if or_key and not is_blacklisted("Google"):
        providers.append(ModelProviderInfo(
            name="Google",
            model=settings.openrouter_google_model,
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
            base_url="https://openrouter.ai/api/v1",
            transport="openai_compatible",
            api_compatibility="openai",
        ))
    if or_key and not is_blacklisted("OpenRouter-Auto"):
        providers.append(ModelProviderInfo(
            name="OpenRouter-Auto",
            model=settings.openrouter_auto_model,
            provider=_make_provider(or_key, "https://openrouter.ai/api/v1"),
            base_url="https://openrouter.ai/api/v1",
            transport="openai_compatible",
            api_compatibility="openai",
        ))

    org_providers, org_policy = _organization_provider_infos(organization_id)
    mode = org_policy.get("provider_mode") or settings.organization_llm_provider_mode
    if mode == "organization_only":
        return org_providers
    if mode == "organization_first":
        return [*org_providers, *providers]
    return [*providers, *org_providers]

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


@observe(as_type="generation")
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
    profile = get_agent_fallback_profile(name)
    providers = get_available_providers(organization_id)

    if tools:
        before_providers = providers
        providers = [p for p in providers if _provider_family_name(p.name) != "Cerebras"]
        skipped = _skipped_providers(before_providers, providers)
        if skipped:
            await _close_provider_clients(skipped)
            logger.info(f"Skipped {len(skipped)} Cerebras provider(s) (no tool-call support) for {name}")

    if output_type is not None:
        before_providers = providers
        providers = [p for p in providers if _provider_family_name(p.name) != "Groq"]
        skipped = _skipped_providers(before_providers, providers)
        if skipped:
            await _close_provider_clients(skipped)
            logger.info(f"Skipped {len(skipped)} Groq provider(s) (no json_schema support) for {name}")

    routing_policy = _effective_llm_routing_policy(organization_id)
    routing_mode = str(routing_policy.get("resolved_mode") or _active_llm_routing_mode())
    providers = _ordered_providers_for_agent(providers, profile, routing_mode)
    provider_names = [p.name for p in providers]
    effective_temperature = temperature if temperature is not None else profile.default_temperature
    effective_max_tokens = max_tokens if max_tokens is not None else profile.default_max_tokens
    logger.info(
        f"Starting {name} with providers: {provider_names}",
        extra={
            "kind": "agent_start",
            "component": name,
            "routing_mode": routing_mode,
            "routing_requested_mode": routing_policy.get("requested_mode"),
            "routing_downgraded": routing_policy.get("downgraded"),
            "routing_plan_id": routing_policy.get("plan_id"),
            "routing_plan_name": routing_policy.get("plan_name"),
            "routing_plan_slug": routing_policy.get("plan_slug"),
            "routing_plan_currency_code": routing_policy.get("plan_currency_code"),
            "routing_plan_market_code": routing_policy.get("plan_market_code"),
            "routing_plan_allow_byok": routing_policy.get("plan_allow_byok"),
            "routing_plan_byok_provider_mode": routing_policy.get("plan_byok_provider_mode"),
            "routing_subscription_status": routing_policy.get("subscription_status"),
            "task_class": profile.task_class,
            "cost_sensitivity": profile.cost_sensitivity,
            "capability_requirement": profile.capability_requirement,
        },
    )
    base_trace_metadata = _trace_metadata({
        "agent_name": name,
        "request_id": get_request_id(),
        "organization_id": organization_id,
        "providers_configured": provider_names,
        "routing_requested_mode": routing_policy.get("requested_mode"),
        "routing_default_mode": routing_policy.get("default_mode"),
        "routing_mode": routing_mode,
        "routing_allowed_modes": routing_policy.get("allowed_modes"),
        "routing_plan_id": routing_policy.get("plan_id"),
        "routing_plan_name": routing_policy.get("plan_name"),
        "routing_plan_slug": routing_policy.get("plan_slug"),
        "routing_plan_currency_code": routing_policy.get("plan_currency_code"),
        "routing_plan_market_code": routing_policy.get("plan_market_code"),
        "routing_plan_allow_byok": routing_policy.get("plan_allow_byok"),
        "routing_plan_byok_provider_mode": routing_policy.get("plan_byok_provider_mode"),
        "routing_subscription_status": routing_policy.get("subscription_status"),
        "routing_downgraded": routing_policy.get("downgraded"),
        "routing_profile": profile.task_class,
        "routing_rationale": profile.rationale,
        "cost_sensitivity": profile.cost_sensitivity,
        "capability_requirement": profile.capability_requirement,
        "output_schema": output_type.__name__ if output_type is not None else None,
        "tool_count": len(tools or []),
    })
    _update_langfuse_span(
        name=name,
        metadata={
            **base_trace_metadata,
            "status": "started",
        },
    )
    
    if not providers:
        raise RuntimeError(
            "Configuration Error: No API keys found for any supported AI provider. "
            "Please set Azure OpenAI (AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_DEPLOYMENT) or at least one of OPENAI_API_KEY, OPENROUTER_API_KEY, "
            "CEREBRAS_API_KEY, GEMINI_API_KEY, or GROQ_API_KEY in your .env file."
        )

    errors = []
    
    for p_info in providers:
        attempt_started = time.perf_counter()
        try:
            logger.info(f"Attempting {name} with {p_info.name} model: {p_info.model}")

            model_settings = {
                "max_tokens": effective_max_tokens if effective_max_tokens is not None else settings.outreach_max_tokens,
            }
            if _model_supports_temperature(p_info.model):
                model_settings["temperature"] = (
                    effective_temperature if effective_temperature is not None else settings.outreach_temperature
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
                action_type, base_credits = metering_service.action_defaults_for_agent(name)
                credits_used = metering_service.credits_for_routing_mode(base_credits, routing_mode)
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
                            "actual_provider": p_info.name,
                            "actual_model": p_info.model,
                            "transport": p_info.transport,
                            "api_compatibility": p_info.api_compatibility,
                            "billing_source": p_info.billing_source,
                            "provider_credential_id": p_info.provider_credential_id,
                            "routing_mode": routing_mode,
                            "routing_default_mode": routing_policy.get("default_mode"),
                            "routing_profile": profile.task_class,
                            "routing_plan_id": routing_policy.get("plan_id"),
                            "routing_plan_name": routing_policy.get("plan_name"),
                            "routing_plan_slug": routing_policy.get("plan_slug"),
                            "routing_subscription_status": routing_policy.get("subscription_status"),
                            "base_credits": base_credits,
                            "credit_multiplier": credits_used // max(base_credits, 1),
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
                    routing_mode=routing_mode,
                    billing_source=p_info.billing_source,
                    provider_credential_id=p_info.provider_credential_id,
                )
            except Exception as usage_error:
                usage_record = {"estimated_cost_usd": None, "pricing_source": "record_failed"}
                logger.warning(f"Failed to record LLM usage for {name}: {usage_error}")
            _update_langfuse_span(
                name=name,
                metadata={
                    **base_trace_metadata,
                    "status": "success",
                    "provider": p_info.name,
                    "model": p_info.model,
                    "actual_provider": p_info.name,
                    "actual_model": p_info.model,
                    "transport": p_info.transport,
                    "api_compatibility": p_info.api_compatibility,
                    "billing_source": p_info.billing_source,
                    "provider_credential_id": p_info.provider_credential_id,
                    "fallback_triggered": fallback_triggered,
                    "attempt_count": len(errors) + 1,
                    "latency_ms": round(latency_ms, 2),
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                    "estimated_cost_usd": usage_record.get("estimated_cost_usd"),
                    "tool_call_count": tool_call_count,
                },
            )
            logger.info(
                f"Agent {name} completed successfully with {p_info.name}",
                extra={
                    "kind": "agent_output",
                    "component": name,
                    "provider": p_info.name,
                    "model": p_info.model,
                    "actual_provider": p_info.name,
                    "actual_model": p_info.model,
                    "transport": p_info.transport,
                    "api_compatibility": p_info.api_compatibility,
                    "billing_source": p_info.billing_source,
                    "routing_mode": routing_mode,
                    "routing_profile": profile.task_class,
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

            await _close_provider_clients(providers)
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
            _update_langfuse_span(
                name=name,
                level="WARNING",
                status_message=error_msg,
                metadata={
                    **base_trace_metadata,
                    "status": "provider_failed",
                    "provider": p_info.name,
                    "model": p_info.model,
                    "actual_provider": p_info.name,
                    "actual_model": p_info.model,
                    "transport": p_info.transport,
                    "api_compatibility": p_info.api_compatibility,
                    "attempt_count": len(errors),
                    "errors": errors,
                },
            )
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
            _update_langfuse_span(
                name=name,
                level="WARNING",
                status_message=error_msg,
                metadata={
                    **base_trace_metadata,
                    "status": "provider_failed",
                    "provider": p_info.name,
                    "model": p_info.model,
                    "actual_provider": p_info.name,
                    "actual_model": p_info.model,
                    "transport": p_info.transport,
                    "api_compatibility": p_info.api_compatibility,
                    "attempt_count": len(errors),
                    "errors": errors,
                },
            )

    # If all providers fail, raise a clear error
    await _close_provider_clients(providers)
    all_errors = "\\n".join([f"  • {err}" for err in errors])
    _update_langfuse_span(
        name=name,
        level="ERROR",
        status_message=f"All AI providers failed for {name}",
        metadata={
            **base_trace_metadata,
            "status": "failed",
            "attempt_count": len(errors),
            "errors": errors,
        },
    )
    raise RuntimeError(
        f"All AI providers failed for {name}.\\n"
        f"Provider attempts:\\n{all_errors}\\n\\n"
        f"Check your API keys and network connection."
    )
