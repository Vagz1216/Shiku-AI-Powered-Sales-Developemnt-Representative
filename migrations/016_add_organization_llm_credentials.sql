ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS allow_byok INTEGER NOT NULL DEFAULT 0 CHECK(allow_byok IN (0,1));

ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS byok_provider_mode TEXT NOT NULL DEFAULT 'platform_first'
    CHECK(byok_provider_mode IN ('platform_first','organization_first','organization_only'));

ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS max_llm_credentials INTEGER;

CREATE TABLE IF NOT EXISTS organization_llm_credentials (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK(provider IN ('openai','azure_openai','gemini','groq','cerebras','openrouter')),
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DISABLED')),
    api_key_secret TEXT NOT NULL,
    base_url TEXT,
    azure_endpoint TEXT,
    azure_deployment TEXT,
    azure_api_version TEXT,
    default_model TEXT,
    created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    last_used_at TIMESTAMP,
    last_tested_at TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP,
    UNIQUE (organization_id, provider, label)
);

CREATE INDEX IF NOT EXISTS idx_org_llm_credentials_org_status
    ON organization_llm_credentials(organization_id, status);

ALTER TABLE llm_usage_events
    ADD COLUMN IF NOT EXISTS billing_source TEXT NOT NULL DEFAULT 'platform'
    CHECK(billing_source IN ('platform','organization'));

ALTER TABLE llm_usage_events
    ADD COLUMN IF NOT EXISTS provider_credential_id INTEGER REFERENCES organization_llm_credentials(id) ON DELETE SET NULL;
