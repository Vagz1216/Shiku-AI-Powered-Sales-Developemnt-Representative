from types import SimpleNamespace

from services import usage_service


def test_extract_usage_sums_agents_raw_responses():
    result = SimpleNamespace(
        raw_responses=[
            SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                    requests=1,
                    input_tokens_details=SimpleNamespace(cached_tokens=10),
                    output_tokens_details=SimpleNamespace(reasoning_tokens=3),
                )
            ),
            SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=50,
                    output_tokens=10,
                    total_tokens=60,
                    requests=1,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                    output_tokens_details=SimpleNamespace(reasoning_tokens=2),
                )
            ),
        ]
    )

    usage = usage_service.extract_usage(result)

    assert usage.input_tokens == 150
    assert usage.output_tokens == 30
    assert usage.total_tokens == 180
    assert usage.cached_input_tokens == 10
    assert usage.reasoning_output_tokens == 5
    assert usage.request_count == 2


def test_estimate_cost_uses_configured_price():
    usage = usage_service.TokenUsage(input_tokens=1000, output_tokens=500, total_tokens=1500)

    cost, source = usage_service.estimate_cost("OpenAI", "gpt-4o-mini", usage)

    assert source == "configured"
    assert cost == 0.00045


def test_estimate_cost_marks_unknown_model_unpriced():
    usage = usage_service.TokenUsage(input_tokens=1000, output_tokens=500, total_tokens=1500)

    cost, source = usage_service.estimate_cost("OpenRouter-Llama", "unknown/model", usage)

    assert source == "unpriced"
    assert cost == 0


def test_pricing_covers_configured_fallback_models():
    fallback_models = [
        ("OpenAI", "gpt-4o-mini"),
        ("AzureOpenAI", "gpt-4o-mini"),
        ("AzureOpenAI", "gpt-5.5"),
        ("Groq", "llama-3.3-70b-versatile"),
        ("Groq-2", "llama-3.3-70b-versatile"),
        ("Cerebras", "gpt-oss-120b"),
        ("Cerebras-2", "gpt-oss-120b"),
        ("Meta", "meta-llama/llama-3.2-3b-instruct:free"),
        ("OpenRouter-Llama", "meta-llama/llama-3.1-8b-instruct:free"),
        ("DeepSeek", "qwen/qwen-2-7b-instruct:free"),
        ("Google", "google/gemini-2.0-flash-lite-preview-02-05:free"),
        ("OpenRouter-Auto", "openrouter/free"),
    ]

    for provider, model in fallback_models:
        price = usage_service.find_price(provider, model)
        assert price.source != "unpriced", f"{provider}/{model} is missing from pricing config"
