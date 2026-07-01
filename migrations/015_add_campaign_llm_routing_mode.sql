ALTER TABLE campaigns
ADD COLUMN IF NOT EXISTS llm_routing_mode TEXT
CHECK(llm_routing_mode IS NULL OR llm_routing_mode IN ('quality_first','balanced','cost_optimized'));

ALTER TABLE llm_usage_events
ADD COLUMN IF NOT EXISTS routing_mode TEXT;
