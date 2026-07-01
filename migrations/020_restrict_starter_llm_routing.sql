UPDATE subscription_plans
SET
    description = 'Entry plan for small outbound teams. Uses cost-optimized routing on platform keys.',
    allowed_llm_routing_modes = 'cost_optimized',
    default_llm_routing_mode = 'cost_optimized',
    trial_allowed_llm_routing_modes = 'cost_optimized',
    allow_byok = 0,
    byok_provider_mode = 'platform_first',
    max_llm_credentials = 0,
    updated_at = NOW()
WHERE slug = 'starter';
