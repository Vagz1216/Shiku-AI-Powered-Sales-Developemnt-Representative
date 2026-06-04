-- Add customer-facing usage metering and internal cost allocation ledgers.

ALTER TABLE subscription_plans ADD COLUMN max_monthly_ai_credits INTEGER;
ALTER TABLE subscription_plans ADD COLUMN overage_allowed INTEGER NOT NULL DEFAULT 0 CHECK(overage_allowed IN (0,1));
ALTER TABLE subscription_plans ADD COLUMN overage_price_cents_per_ai_credit INTEGER;

CREATE TABLE IF NOT EXISTS organization_billing_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    subscription_id INTEGER,
    plan_id INTEGER,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    included_ai_credits INTEGER,
    included_emails INTEGER,
    included_users INTEGER,
    included_leads INTEGER,
    overage_allowed INTEGER NOT NULL DEFAULT 0 CHECK(overage_allowed IN (0,1)),
    overage_price_cents_per_ai_credit INTEGER,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','VOID')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (subscription_id) REFERENCES organization_subscriptions(id) ON DELETE SET NULL,
    FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE SET NULL,
    UNIQUE (organization_id, period_start, period_end)
);

CREATE TABLE IF NOT EXISTS ai_usage_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    user_id INTEGER,
    request_id TEXT,
    action_type TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    credits_used INTEGER NOT NULL DEFAULT 0,
    billing_period_start TEXT,
    billing_period_end TEXT,
    source_object_type TEXT,
    source_object_id TEXT,
    status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success','error','void')),
    idempotency_key TEXT UNIQUE,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS platform_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER,
    user_id INTEGER,
    event_type TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    source_object_type TEXT,
    source_object_id TEXT,
    idempotency_key TEXT UNIQUE,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS platform_cost_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    category TEXT NOT NULL,
    provider TEXT,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    allocation_method TEXT NOT NULL DEFAULT 'manual',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE llm_usage_events ADD COLUMN user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL;
ALTER TABLE llm_usage_events ADD COLUMN ai_usage_action_id INTEGER REFERENCES ai_usage_actions(id) ON DELETE SET NULL;
ALTER TABLE llm_usage_events ADD COLUMN pricing_version TEXT;

CREATE INDEX IF NOT EXISTS idx_billing_periods_org ON organization_billing_periods(organization_id, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_ai_usage_org_created ON ai_usage_actions(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_period ON ai_usage_actions(organization_id, billing_period_start, billing_period_end);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage_actions(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_usage_org_created ON platform_usage_events(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_cost_period ON platform_cost_allocations(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_llm_usage_action ON llm_usage_events(ai_usage_action_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_user_created ON llm_usage_events(user_id, created_at);
