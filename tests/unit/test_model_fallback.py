from utils import model_fallback
from config import settings


def test_azure_provider_is_first_when_configured(monkeypatch):
    model_fallback._BLACKLIST.clear()
    monkeypatch.setattr(settings, "azure_openai_api_key", "azure-key")
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://example.openai.azure.com")
    monkeypatch.setattr(settings, "azure_openai_deployment", "gpt-4o-mini-deployment")
    monkeypatch.setattr(settings, "azure_openai_api_version", "2024-10-21")
    monkeypatch.setattr(settings, "azure_openai_wire_api", "chat_completions")
    monkeypatch.setattr(settings, "openai_api_key", "openai-key")
    monkeypatch.setattr(settings, "openai_base_url", None)
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "cerebras_api_key", None)
    monkeypatch.setattr(settings, "openrouter_api_key", None)

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
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "cerebras_api_key", None)
    monkeypatch.setattr(settings, "openrouter_api_key", None)

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
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "cerebras_api_key", None)
    monkeypatch.setattr(settings, "openrouter_api_key", None)

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
