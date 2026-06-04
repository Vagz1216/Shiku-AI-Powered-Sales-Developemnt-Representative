-- Scope LLM usage/cost reporting to organizations.
-- Legacy rows are assigned to the default organization.

ALTER TABLE llm_usage_events ADD COLUMN organization_id INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_llm_usage_org_created_at ON llm_usage_events(organization_id, created_at);
