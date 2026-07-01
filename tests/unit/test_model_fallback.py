import asyncio

from utils import model_fallback
from config import settings
from services import platform_settings_service


def clear_optional_provider_keys(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "cerebras_api_key", None)
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)


def test_azure_provider_is_first_when_configured(monkeypatch):
    model_fallback._BLACKLIST.clear()
    monkeypatch.setattr(settings, "azure_openai_api_key", "azure-key")
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://example.openai.azure.com")
    monkeypatch.setattr(settings, "azure_openai_deployment", "gpt-4o-mini-deployment")
    monkeypatch.setattr(settings, "azure_openai_api_version", "2024-10-21")
    monkeypatch.setattr(settings, "azure_openai_wire_api", "chat_completions")
    monkeypatch.setattr(settings, "openai_api_key", "openai-key")
    monkeypatch.setattr(settings, "openai_base_url", None)
    clear_optional_provider_keys(monkeypatch)

    providers = model_fallback.get_available_providers()

    assert [p.name for p in providers[:2]] == ["AzureOpenAI", "OpenAI"]
    assert providers[0].model == "gpt-4o-mini-deployment"


def test_azure_provider_is_skipped_when_partially_configured(monkeypatch):
    model_fallback._BLACKLIST.clear()
    monkeypatch.setattr(settings, "azure_openai_api_key", "azure-key")
    monkeypatch.setattr(settings, "azure_openai_endpoint", None)
    monkeypatch.setattr(settings, "azure_openai_deployment", "deployment")
    monkeypatch.setattr(settings, "openai_api_key", "openai-key")
    monkeypatch.setattr(settings, "openai_base_url", None)
    clear_optional_provider_keys(monkeypatch)

    providers = model_fallback.get_available_providers()

    assert [p.name for p in providers] == ["OpenAI"]


def test_openai_base_url_uses_openai_compatible_provider(monkeypatch):
    model_fallback._BLACKLIST.clear()
    monkeypatch.setattr(settings, "azure_openai_api_key", None)
    monkeypatch.setattr(settings, "azure_openai_endpoint", None)
    monkeypatch.setattr(settings, "azure_openai_deployment", None)
    monkeypatch.setattr(settings, "openai_api_key", "litellm-key")
    monkeypatch.setattr(settings, "openai_base_url", "https://litellm.example.com/v1")
    monkeypatch.setattr(settings, "outreach_model", "azure/gpt-4o-mini")
    clear_optional_provider_keys(monkeypatch)

    providers = model_fallback.get_available_providers()

    assert [p.name for p in providers] == ["OpenAICompatible"]
    assert providers[0].model == "azure/gpt-4o-mini"
    assert providers[0].provider is not None


def test_azure_responses_base_url_uses_v1_endpoint():
    assert (
        model_fallback._azure_responses_base_url("https://example.openai.azure.com")
        == "https://example.openai.azure.com/openai/v1/"
    )


def test_gpt5_models_skip_temperature():
    assert model_fallback._model_supports_temperature("gpt-4o-mini")
    assert not model_fallback._model_supports_temperature("gpt-5.5")
    assert not model_fallback._model_supports_temperature("o3-mini")
    assert (
        model_fallback._azure_responses_base_url("https://example.openai.azure.com/openai")
        == "https://example.openai.azure.com/openai/v1/"
    )
    assert (
        model_fallback._azure_responses_base_url("https://example.openai.azure.com/openai/v1/")
        == "https://example.openai.azure.com/openai/v1/"
    )


class _FakeProvider:
    def __init__(self):
        self.close_count = 0
        self._client = None

    async def aclose(self):
        self.close_count += 1


class _FakeRawClient:
    def __init__(self):
        self.close_count = 0

    async def close(self):
        self.close_count += 1


def test_close_provider_clients_closes_each_provider_once():
    provider = _FakeProvider()
    providers = [
        model_fallback.ModelProviderInfo(name="One", model="m", provider=provider),
        model_fallback.ModelProviderInfo(name="Duplicate", model="m", provider=provider),
        model_fallback.ModelProviderInfo(name="Default", model="m", provider=None),
    ]

    asyncio.run(model_fallback._close_provider_clients(providers))

    assert provider.close_count == 1


def test_close_provider_clients_closes_raw_openai_client():
    provider = _FakeProvider()
    provider._client = _FakeRawClient()
    providers = [model_fallback.ModelProviderInfo(name="OpenAI", model="m", provider=provider)]

    asyncio.run(model_fallback._close_provider_clients(providers))

    assert provider.close_count == 1
    assert provider._client.close_count == 1


def test_skipped_providers_returns_filtered_instances():
    first = model_fallback.ModelProviderInfo(name="First", model="m", provider=_FakeProvider())
    second = model_fallback.ModelProviderInfo(name="Second", model="m", provider=_FakeProvider())

    assert model_fallback._skipped_providers([first, second], [second]) == [first]


def test_trace_metadata_stringifies_exporter_values():
    metadata = model_fallback._trace_metadata({
        "organization_id": 1,
        "providers_configured": ["Gemini", "AzureOpenAI"],
        "output_schema": None,
    })

    assert metadata == {
        "organization_id": "1",
        "providers_configured": "Gemini, AzureOpenAI",
        "output_schema": "",
    }


def test_agent_profile_preserves_quality_first_hierarchy(monkeypatch):
    monkeypatch.setattr(settings, "llm_routing_mode", "quality_first")
    monkeypatch.setattr(platform_settings_service, "get_llm_routing_mode", lambda: "quality_first")
    providers = [
        model_fallback.ModelProviderInfo(name="Cerebras", model="fast"),
        model_fallback.ModelProviderInfo(name="AzureOpenAI", model="gpt-5.5"),
        model_fallback.ModelProviderInfo(name="Gemini", model="flash"),
    ]

    ordered = model_fallback._ordered_providers_for_agent(
        providers,
        model_fallback.get_agent_fallback_profile("DrafterAgent"),
    )

    assert [p.name for p in ordered] == ["AzureOpenAI", "Gemini", "Cerebras"]


def test_agent_profile_cost_optimizes_short_structured_tasks(monkeypatch):
    monkeypatch.setattr(settings, "llm_routing_mode", "cost_optimized")
    monkeypatch.setattr(platform_settings_service, "get_llm_routing_mode", lambda: "cost_optimized")
    providers = [
        model_fallback.ModelProviderInfo(name="AzureOpenAI", model="gpt-5.5"),
        model_fallback.ModelProviderInfo(name="OpenAI", model="gpt-4o-mini"),
        model_fallback.ModelProviderInfo(name="Cerebras", model="gpt-oss-120b"),
        model_fallback.ModelProviderInfo(name="Gemini", model="gemini-2.5-flash"),
    ]

    ordered = model_fallback._ordered_providers_for_agent(
        providers,
        model_fallback.get_agent_fallback_profile("EmailIntentExtractor"),
    )

    assert [p.name for p in ordered] == ["Cerebras", "Gemini", "AzureOpenAI", "OpenAI"]


def test_agent_profile_balances_writing_quality_and_cost(monkeypatch):
    monkeypatch.setattr(settings, "llm_routing_mode", "balanced")
    monkeypatch.setattr(platform_settings_service, "get_llm_routing_mode", lambda: "balanced")
    providers = [
        model_fallback.ModelProviderInfo(name="AzureOpenAI", model="gpt-5.5"),
        model_fallback.ModelProviderInfo(name="Cerebras", model="gpt-oss-120b"),
        model_fallback.ModelProviderInfo(name="Gemini", model="gemini-2.5-flash"),
        model_fallback.ModelProviderInfo(name="OpenRouter-Auto", model="openrouter/free"),
    ]

    ordered = model_fallback._ordered_providers_for_agent(
        providers,
        model_fallback.get_agent_fallback_profile("EmailResponseAgent"),
    )

    assert [p.name for p in ordered] == ["Gemini", "AzureOpenAI", "Cerebras", "OpenRouter-Auto"]


def test_agent_profile_balanced_keeps_safety_reliable(monkeypatch):
    monkeypatch.setattr(settings, "llm_routing_mode", "balanced")
    monkeypatch.setattr(platform_settings_service, "get_llm_routing_mode", lambda: "balanced")
    providers = [
        model_fallback.ModelProviderInfo(name="Cerebras", model="gpt-oss-120b"),
        model_fallback.ModelProviderInfo(name="AzureOpenAI", model="gpt-5.5"),
        model_fallback.ModelProviderInfo(name="Gemini", model="gemini-2.5-flash"),
    ]

    ordered = model_fallback._ordered_providers_for_agent(
        providers,
        model_fallback.get_agent_fallback_profile("LlamaGuardAgent"),
    )

    assert [p.name for p in ordered] == ["AzureOpenAI", "Gemini", "Cerebras"]


def test_provider_model_overrides_are_used(monkeypatch):
    model_fallback._BLACKLIST.clear()
    monkeypatch.setattr(settings, "azure_openai_api_key", None)
    monkeypatch.setattr(settings, "azure_openai_endpoint", None)
    monkeypatch.setattr(settings, "azure_openai_deployment", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_base_url", None)
    monkeypatch.setattr(settings, "groq_api_key", "groq-key")
    monkeypatch.setattr(settings, "groq_model", "custom-groq-model")
    monkeypatch.setattr(settings, "cerebras_api_key", "cerebras-key")
    monkeypatch.setattr(settings, "cerebras_model", "custom-cerebras-model")
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    providers = model_fallback.get_available_providers()

    assert [(p.name, p.model) for p in providers] == [
        ("Groq", "custom-groq-model"),
        ("Cerebras", "custom-cerebras-model"),
    ]
    assert all(p.transport == "openai_compatible" for p in providers)
    assert all(p.api_compatibility == "openai" for p in providers)


def test_gemini_provider_is_labeled_as_openai_compatible_transport(monkeypatch):
    model_fallback._BLACKLIST.clear()
    monkeypatch.setattr(settings, "azure_openai_api_key", None)
    monkeypatch.setattr(settings, "azure_openai_endpoint", None)
    monkeypatch.setattr(settings, "azure_openai_deployment", None)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_base_url", None)
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "cerebras_api_key", None)
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-flash")

    providers = model_fallback.get_available_providers()

    assert len(providers) == 1
    assert providers[0].name == "Gemini"
    assert providers[0].model == "gemini-2.5-flash"
    assert providers[0].transport == "openai_compatible"
    assert providers[0].api_compatibility == "openai"
    assert providers[0].base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_openai_async_httpx_del_patch_suppresses_missing_state():
    wrapper = object.__new__(model_fallback.AsyncHttpxClientWrapper)

    wrapper.__del__()
