-- Subscription plan catalog and per-organization plan selection.
-- SQLite and PostgreSQL compatible enough for manual application with minor
-- SERIAL/AUTOINCREMENT adjustments already reflected in the bootstrap schemas.

CREATE TABLE IF NOT EXISTS subscription_plans (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    monthly_price_cents INTEGER NOT NULL DEFAULT 0,
    trial_days INTEGER NOT NULL DEFAULT 14,
    max_users INTEGER,
    max_campaigns INTEGER,
    max_leads INTEGER,
    max_monthly_emails INTEGER,
    max_monthly_ai_tokens INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS organization_subscriptions (
    id INTEGER PRIMARY KEY,
    organization_id INTEGER NOT NULL UNIQUE,
    plan_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'TRIALING' CHECK(status IN ('TRIALING','ACTIVE','PAST_DUE','CANCELED','EXPIRED')),
    trial_ends_at TEXT,
    current_period_started_at TEXT,
    current_period_ends_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_subscription_plans_active ON subscription_plans(active);
CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_plan ON organization_subscriptions(plan_id);
CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_status ON organization_subscriptions(status);
