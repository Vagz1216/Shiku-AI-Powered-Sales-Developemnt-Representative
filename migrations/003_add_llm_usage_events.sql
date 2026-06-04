CREATE TABLE IF NOT EXISTS llm_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    agent_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 1,
    latency_ms REAL NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    pricing_source TEXT,
    fallback_triggered INTEGER NOT NULL DEFAULT 0 CHECK(fallback_triggered IN (0,1)),
    attempt_count INTEGER NOT NULL DEFAULT 1,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success','error')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage_events(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_request_id ON llm_usage_events(request_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage_events(provider, model);
