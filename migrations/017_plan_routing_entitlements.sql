ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS allowed_llm_routing_modes TEXT NOT NULL DEFAULT 'cost_optimized,balanced,quality_first';

ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS default_llm_routing_mode TEXT NOT NULL DEFAULT 'balanced'
    CHECK(default_llm_routing_mode IN ('cost_optimized','balanced','quality_first'));

ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS trial_allowed_llm_routing_modes TEXT NOT NULL DEFAULT 'cost_optimized';

UPDATE subscription_plans
SET
    allowed_llm_routing_modes = COALESCE(NULLIF(allowed_llm_routing_modes, ''), 'cost_optimized,balanced,quality_first'),
    default_llm_routing_mode = COALESCE(NULLIF(default_llm_routing_mode, ''), 'balanced'),
    trial_allowed_llm_routing_modes = COALESCE(NULLIF(trial_allowed_llm_routing_modes, ''), 'cost_optimized');

INSERT INTO subscription_plans (
    name, slug, description, monthly_price_cents, trial_days,
    max_users, max_campaigns, max_leads, max_monthly_emails,
    max_monthly_ai_tokens, max_monthly_ai_credits,
    overage_allowed, overage_price_cents_per_ai_credit,
    allow_byok, byok_provider_mode, max_llm_credentials,
    allowed_llm_routing_modes, default_llm_routing_mode, trial_allowed_llm_routing_modes,
    active, updated_at
) VALUES
    (
        'Trial Sandbox', 'trial-sandbox',
        'Short evaluation plan. Uses cost-optimized routing on platform keys to protect trial spend.',
        0, 14,
        2, 2, 500, 200,
        NULL, 100,
        0, NULL,
        0, 'platform_first', 0,
        'cost_optimized', 'cost_optimized', 'cost_optimized',
        1, NOW()
    ),
    (
        'Starter', 'starter',
        'Entry plan for small outbound teams. Uses cost-optimized routing on platform keys.',
        4900, 0,
        3, 5, 2500, 1000,
        NULL, 1000,
        1, 2,
        0, 'platform_first', 0,
        'cost_optimized', 'cost_optimized', 'cost_optimized',
        1, NOW()
    ),
    (
        'Growth', 'growth',
        'Production plan for growing teams with BYOK support and balanced routing by default.',
        14900, 0,
        10, 20, 20000, 5000,
        NULL, 5000,
        1, 2,
        1, 'organization_first', 3,
        'cost_optimized,balanced,quality_first', 'balanced', 'cost_optimized',
        1, NOW()
    ),
    (
        'Scale', 'scale',
        'Higher-volume plan with larger included credits, BYOK, and room for multiple model providers.',
        39900, 0,
        25, 75, 100000, 20000,
        NULL, 20000,
        1, 1,
        1, 'organization_first', 10,
        'cost_optimized,balanced,quality_first', 'balanced', 'cost_optimized',
        1, NOW()
    ),
    (
        'Enterprise', 'enterprise',
        'Custom plan for high-volume teams needing custom limits, procurement controls, and BYOK-first routing.',
        0, 0,
        NULL, NULL, NULL, NULL,
        NULL, NULL,
        1, 1,
        1, 'organization_first', 25,
        'cost_optimized,balanced,quality_first', 'balanced', 'cost_optimized',
        1, NOW()
    )
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    monthly_price_cents = EXCLUDED.monthly_price_cents,
    trial_days = EXCLUDED.trial_days,
    max_users = EXCLUDED.max_users,
    max_campaigns = EXCLUDED.max_campaigns,
    max_leads = EXCLUDED.max_leads,
    max_monthly_emails = EXCLUDED.max_monthly_emails,
    max_monthly_ai_tokens = EXCLUDED.max_monthly_ai_tokens,
    max_monthly_ai_credits = EXCLUDED.max_monthly_ai_credits,
    overage_allowed = EXCLUDED.overage_allowed,
    overage_price_cents_per_ai_credit = EXCLUDED.overage_price_cents_per_ai_credit,
    allow_byok = EXCLUDED.allow_byok,
    byok_provider_mode = EXCLUDED.byok_provider_mode,
    max_llm_credentials = EXCLUDED.max_llm_credentials,
    allowed_llm_routing_modes = EXCLUDED.allowed_llm_routing_modes,
    default_llm_routing_mode = EXCLUDED.default_llm_routing_mode,
    trial_allowed_llm_routing_modes = EXCLUDED.trial_allowed_llm_routing_modes,
    active = EXCLUDED.active,
    updated_at = NOW();
