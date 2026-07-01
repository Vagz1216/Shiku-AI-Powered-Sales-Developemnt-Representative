# LLM Routing And Billing

## Runtime Routing

The platform has one LLM routing entry point: `utils.model_fallback.run_agent_with_fallback`.
Each agent has a routing profile that declares:

- task class
- capability requirement
- cost sensitivity
- quality-first fallback order
- cost-optimized fallback order

`LLM_ROUTING_MODE=quality_first` is the default. It keeps the current platform hierarchy and therefore preserves the existing Azure-first production behavior when Azure is configured.

`LLM_ROUTING_MODE=balanced` is the recommended production setting when cost matters. It keeps reliable providers first for safety and tool-calling agents, while using cheaper capable models earlier for classification, review, and ordinary generation.

`LLM_ROUTING_MODE=cost_optimized` changes only the order in which compatible providers are attempted. It does not bypass existing capability filters:

- Groq is skipped for structured-output agents because the current integration does not support `json_schema`.
- Cerebras is skipped for tool-calling agents because the current integration does not support tool calls reliably.
- Models that reject temperature, such as `gpt-5*` and reasoning-family models, are called without temperature.

## Agent Profiles

| Agent | Task | Quality-first rationale | Balanced rationale | Cost-optimized rationale |
| --- | --- | --- | --- |
| `DrafterAgent` | Cold outreach draft generation | User-facing copy needs stronger writing quality, so Azure/OpenAI/Gemini are preferred before lower-capability routers. | Gemini first, then Azure/OpenAI, then cheaper/free fallbacks. | Gemini/Cerebras can reduce cost for draft variants while still preserving structured output and fallback to Azure/OpenAI. |
| `ReviewerAgent` | Cold outreach quality selection | Review output must be structured and conservative. | Cheaper structured providers first because review is short and deterministic. | Review is short and deterministic, so cheaper structured providers are acceptable before premium generators. |
| `EmailIntentExtractor` | Inbound intent classification | Keeps platform hierarchy for maximum reliability. | Cheaper structured providers first because classification is short and low risk. | Classification is short and structured; low-cost models are usually sufficient. |
| `LlamaGuardAgent` | Safety and prompt-injection gate | Safety fails closed, so reliability is prioritized. | Keeps Azure/OpenAI first because false negatives are more expensive than token cost. | Still keeps Azure/OpenAI first because false negatives are more expensive than token cost. |
| `EmailResponseAgent` | Inbound reply generation | User-facing reply quality and context handling matter. | Gemini first, then Azure/OpenAI, then cheaper/free fallbacks. | Gemini/Cerebras are tried earlier, but weak free routers remain late fallbacks. |
| `EmailResponseEvaluator` | Inbound reply quality gate | Conservative structured evaluation. | Cheaper structured providers first because evaluation is short and deterministic. | Short deterministic evaluation can use cheaper structured models first. |
| `EmailSenderAgent` | Tool orchestration and side effects | Tool-call reliability matters more than token price. | Keeps proven tool-call providers first. | Cost mode still keeps proven tool-call providers first. |

## Provider Model Knobs

These environment variables control which model is attached to each configured provider:

```env
GROQ_MODEL=llama-3.3-70b-versatile
CEREBRAS_MODEL=gpt-oss-120b
GEMINI_MODEL=gemini-2.5-flash
OPENROUTER_META_MODEL=meta-llama/llama-3.2-3b-instruct:free
OPENROUTER_LLAMA_MODEL=meta-llama/llama-3.1-8b-instruct:free
OPENROUTER_DEEPSEEK_MODEL=qwen/qwen-2-7b-instruct:free
OPENROUTER_GOOGLE_MODEL=google/gemini-2.0-flash-lite-preview-02-05:free
OPENROUTER_AUTO_MODEL=openrouter/free
```

Keep `config/llm_pricing.json` aligned with any model override so usage ledgers can estimate cost.

## Platform Keys Versus Organization Keys

Current production behavior uses platform-level provider keys from environment variables.

The next step for BYOK is an organization-level provider credential table with encrypted API keys. The routing layer already carries `billing_source` and `provider_credential_id` metadata on provider attempts so usage and Langfuse traces can distinguish platform-funded calls from customer-key calls once those credentials are enabled.

Recommended billing semantics:

- Platform key usage counts against included AI credits and platform cost.
- Organization key usage records estimated token cost for visibility but should not count as platform provider cost.
- Plans can charge a platform orchestration fee for BYOK usage separately from raw model cost.
- Enterprise plans can allow `organization_first` or `organization_only` routing.

Proposed future env flags:

```env
ORGANIZATION_LLM_KEYS_ENABLED=false
ORGANIZATION_LLM_PROVIDER_MODE=platform_first
```

Do not enable organization-owned keys until the encrypted credential storage, admin UI, and billing ledger fields are deployed together.
