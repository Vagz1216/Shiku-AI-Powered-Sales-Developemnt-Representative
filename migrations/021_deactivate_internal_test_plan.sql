UPDATE subscription_plans
SET
    description = COALESCE(description, 'Internal-only test plan. Not assignable to tenant customers.'),
    allowed_llm_routing_modes = 'cost_optimized',
    default_llm_routing_mode = 'cost_optimized',
    trial_allowed_llm_routing_modes = 'cost_optimized',
    overage_allowed = 0,
    allow_byok = 0,
    byok_provider_mode = 'platform_first',
    max_llm_credentials = 0,
    active = 0,
    updated_at = NOW()
WHERE slug = 'test';
