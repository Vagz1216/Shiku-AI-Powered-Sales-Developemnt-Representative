-- PostgreSQL schema for SDR platform (Aurora Serverless v2)

CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi',
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','SUSPENDED','ARCHIVED')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app_users (
    id SERIAL PRIMARY KEY,
    clerk_user_id TEXT NOT NULL UNIQUE,
    email TEXT,
    name TEXT,
    platform_role TEXT NOT NULL DEFAULT 'user' CHECK(platform_role IN ('system_owner','user')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organization_users (
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('org_admin','sales_manager','sales_user','viewer')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','INVITED','DISABLED')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS subscription_plans (
    id SERIAL PRIMARY KEY,
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
    max_monthly_ai_credits INTEGER,
    overage_allowed INTEGER NOT NULL DEFAULT 0 CHECK(overage_allowed IN (0,1)),
    overage_price_cents_per_ai_credit INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organization_subscriptions (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
    plan_id INTEGER NOT NULL REFERENCES subscription_plans(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'TRIALING' CHECK(status IN ('TRIALING','ACTIVE','PAST_DUE','CANCELED','EXPIRED')),
    trial_ends_at TIMESTAMP,
    current_period_started_at TIMESTAMP,
    current_period_ends_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organization_billing_periods (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    subscription_id INTEGER REFERENCES organization_subscriptions(id) ON DELETE SET NULL,
    plan_id INTEGER REFERENCES subscription_plans(id) ON DELETE SET NULL,
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    included_ai_credits INTEGER,
    included_emails INTEGER,
    included_users INTEGER,
    included_leads INTEGER,
    overage_allowed INTEGER NOT NULL DEFAULT 0 CHECK(overage_allowed IN (0,1)),
    overage_price_cents_per_ai_credit INTEGER,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','VOID')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP,
    UNIQUE (organization_id, period_start, period_end)
);

CREATE TABLE IF NOT EXISTS ai_usage_actions (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    request_id TEXT,
    action_type TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    credits_used INTEGER NOT NULL DEFAULT 0,
    billing_period_start TIMESTAMP,
    billing_period_end TIMESTAMP,
    source_object_type TEXT,
    source_object_id TEXT,
    status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success','error','void')),
    idempotency_key TEXT UNIQUE,
    metadata TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform_usage_events (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    source_object_type TEXT,
    source_object_id TEXT,
    idempotency_key TEXT UNIQUE,
    metadata TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform_cost_allocations (
    id SERIAL PRIMARY KEY,
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    category TEXT NOT NULL,
    provider TEXT,
    total_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    allocation_method TEXT NOT NULL DEFAULT 'manual',
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mailbox_connections (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK(provider IN ('smtp_imap','resend','gmail','microsoft')),
    display_name TEXT,
    email_address TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','CONNECTED','FAILED','DISABLED')),
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_use_ssl BOOLEAN NOT NULL DEFAULT TRUE,
    smtp_username TEXT,
    smtp_password_secret TEXT,
    imap_host TEXT,
    imap_port INTEGER,
    imap_use_ssl BOOLEAN NOT NULL DEFAULT TRUE,
    imap_username TEXT,
    imap_password_secret TEXT,
    resend_domain TEXT,
    resend_from_email TEXT,
    resend_reply_to TEXT,
    resend_api_key_secret TEXT,
    resend_webhook_secret_secret TEXT,
    daily_limit INTEGER NOT NULL DEFAULT 100,
    last_sync_at TIMESTAMP,
    last_tested_at TIMESTAMP,
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP,
    UNIQUE (organization_id, email_address)
);

INSERT INTO organizations (id, name, slug, status)
VALUES (1, 'Default Organization', 'default', 'ACTIVE')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL DEFAULT 1 REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    name TEXT,
    company TEXT,
    industry TEXT,
    pain_points TEXT,
    status TEXT NOT NULL DEFAULT 'NEW' CHECK(status IN ('NEW','CONTACTED','WARM','QUALIFIED','MEETING_PROPOSED','MEETING_BOOKED','COLD','OPTED_OUT')),
    email_opt_out BOOLEAN NOT NULL DEFAULT FALSE,
    touch_count INTEGER NOT NULL DEFAULT 0,
    last_contacted_at TIMESTAMP,
    last_inbound_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, email)
);

CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL DEFAULT 1 REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    value_proposition TEXT,
    cta TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','PAUSED','INACTIVE')),
    meeting_delay_days INTEGER NOT NULL DEFAULT 1,
    max_leads_per_campaign INTEGER,
    lead_selection_order TEXT NOT NULL DEFAULT 'newest_first',
    auto_approve_drafts BOOLEAN NOT NULL DEFAULT FALSE,
    auto_approve_monitor_replies BOOLEAN NOT NULL DEFAULT FALSE,
    max_emails_per_lead INTEGER NOT NULL DEFAULT 5,
    UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS campaign_leads (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    emails_sent INTEGER NOT NULL DEFAULT 0,
    responded BOOLEAN NOT NULL DEFAULT FALSE,
    meeting_booked BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (campaign_id, lead_id)
);

CREATE TABLE IF NOT EXISTS campaign_lead_contexts (
    organization_id INTEGER NOT NULL DEFAULT 1 REFERENCES organizations(id) ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    last_outbound_subject TEXT,
    last_outbound_summary TEXT,
    last_inbound_subject TEXT,
    last_inbound_summary TEXT,
    latest_intent TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (campaign_id, lead_id)
);

-- staff must exist before campaign_staff (FK to staff.id)
CREATE TABLE IF NOT EXISTS staff (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL DEFAULT 1 REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    timezone TEXT,
    availability TEXT,
    dummy_slots TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, email)
);

CREATE TABLE IF NOT EXISTS campaign_staff (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, staff_id)
);

CREATE TABLE IF NOT EXISTS campaign_sequence_steps (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    delay_days INTEGER NOT NULL DEFAULT 3,
    subject_template TEXT,
    body_template TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, step_number)
);

CREATE TABLE IF NOT EXISTS email_messages (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL DEFAULT 1 REFERENCES organizations(id) ON DELETE CASCADE,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    sequence_step_id INTEGER REFERENCES campaign_sequence_steps(id) ON DELETE SET NULL,
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    subject TEXT,
    body TEXT,
    status TEXT,
    intent TEXT,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1,-1)),
    approved_by TEXT,
    approved_at TIMESTAMP,
    scheduled_send_at TIMESTAMP,
    sent_at TIMESTAMP,
    send_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    external_message_id TEXT,
    external_thread_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_attachments (
    id SERIAL PRIMARY KEY,
    email_message_id INTEGER NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT,
    content_base64 TEXT,
    extracted_text TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'user_upload' CHECK(source IN ('user_upload','inbound')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    meet_link TEXT,
    start_time TIMESTAMP NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK(status IN ('SCHEDULED','CANCELLED','COMPLETED')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    payload TEXT,
    metadata TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outbound_webhooks (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    target_url TEXT NOT NULL,
    event_types TEXT NOT NULL DEFAULT 'all',
    secret TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id SERIAL PRIMARY KEY,
    webhook_id INTEGER NOT NULL REFERENCES outbound_webhooks(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DELIVERED','FAILED')),
    response_status INTEGER,
    error TEXT,
    delivered_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_usage_events (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL DEFAULT 1,
    user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    ai_usage_action_id INTEGER REFERENCES ai_usage_actions(id) ON DELETE SET NULL,
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
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    pricing_source TEXT,
    pricing_version TEXT,
    fallback_triggered BOOLEAN NOT NULL DEFAULT FALSE,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success','error')),
    error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_users_clerk_user_id ON app_users(clerk_user_id);
CREATE INDEX IF NOT EXISTS idx_app_users_email ON app_users(email);
CREATE INDEX IF NOT EXISTS idx_organization_users_user_id ON organization_users(user_id);
CREATE INDEX IF NOT EXISTS idx_subscription_plans_active ON subscription_plans(active);
CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_plan ON organization_subscriptions(plan_id);
CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_status ON organization_subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_billing_periods_org ON organization_billing_periods(organization_id, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_ai_usage_org_created ON ai_usage_actions(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_period ON ai_usage_actions(organization_id, billing_period_start, billing_period_end);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage_actions(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_usage_org_created ON platform_usage_events(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_cost_period ON platform_cost_allocations(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_mailbox_connections_org ON mailbox_connections(organization_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_org ON campaigns(organization_id);
CREATE INDEX IF NOT EXISTS idx_leads_org_email ON leads(organization_id, email);
CREATE INDEX IF NOT EXISTS idx_staff_org_email ON staff(organization_id, email);
CREATE INDEX IF NOT EXISTS idx_email_messages_org ON email_messages(organization_id);
CREATE INDEX IF NOT EXISTS idx_events_org ON events(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_campaign_leads_lead_id ON campaign_leads(lead_id);
CREATE INDEX IF NOT EXISTS idx_campaign_lead_contexts_lead ON campaign_lead_contexts(lead_id);
CREATE INDEX IF NOT EXISTS idx_campaign_staff_staff_id ON campaign_staff(staff_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_lead_id ON email_messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_processed ON email_messages(processed);
CREATE INDEX IF NOT EXISTS idx_email_messages_scheduled ON email_messages(status, approved, scheduled_send_at);
CREATE INDEX IF NOT EXISTS idx_email_attachments_message_id ON email_attachments(email_message_id);
CREATE INDEX IF NOT EXISTS idx_meetings_lead_id ON meetings(lead_id);
CREATE INDEX IF NOT EXISTS idx_sequence_steps_campaign ON campaign_sequence_steps(campaign_id, step_number);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries(webhook_id, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage_events(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_org_created_at ON llm_usage_events(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_action ON llm_usage_events(ai_usage_action_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_user_created ON llm_usage_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_request_id ON llm_usage_events(request_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage_events(provider, model);
