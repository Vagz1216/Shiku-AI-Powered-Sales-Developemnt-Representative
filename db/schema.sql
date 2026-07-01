PRAGMA foreign_keys = ON;

-- Organizations / tenant ownership
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi',
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','SUSPENDED','ARCHIVED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clerk_user_id TEXT NOT NULL UNIQUE,
    email TEXT,
    name TEXT,
    platform_role TEXT NOT NULL DEFAULT 'user' CHECK(platform_role IN ('system_owner','user')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS organization_users (
    organization_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('org_admin','sales_manager','sales_user','viewer')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','INVITED','DISABLED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (organization_id, user_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subscription_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    monthly_price_cents INTEGER NOT NULL DEFAULT 0,
    currency_code TEXT NOT NULL DEFAULT 'USD',
    market_code TEXT NOT NULL DEFAULT 'GLOBAL',
    trial_days INTEGER NOT NULL DEFAULT 14,
    max_users INTEGER,
    max_campaigns INTEGER,
    max_leads INTEGER,
    max_monthly_emails INTEGER,
    max_monthly_ai_tokens INTEGER,
    max_monthly_ai_credits INTEGER,
    overage_allowed INTEGER NOT NULL DEFAULT 0 CHECK(overage_allowed IN (0,1)),
    overage_price_cents_per_ai_credit INTEGER,
    allow_byok INTEGER NOT NULL DEFAULT 0 CHECK(allow_byok IN (0,1)),
    byok_provider_mode TEXT NOT NULL DEFAULT 'platform_first' CHECK(byok_provider_mode IN ('platform_first','organization_first','organization_only')),
    max_llm_credentials INTEGER,
    allowed_llm_routing_modes TEXT NOT NULL DEFAULT 'cost_optimized,balanced,quality_first',
    default_llm_routing_mode TEXT NOT NULL DEFAULT 'balanced' CHECK(default_llm_routing_mode IN ('cost_optimized','balanced','quality_first')),
    trial_allowed_llm_routing_modes TEXT NOT NULL DEFAULT 'cost_optimized',
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS organization_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

CREATE TABLE IF NOT EXISTS mailbox_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('smtp_imap','resend','gmail','microsoft')),
    display_name TEXT,
    email_address TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','CONNECTED','FAILED','DISABLED')),
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_use_ssl INTEGER NOT NULL DEFAULT 1 CHECK(smtp_use_ssl IN (0,1)),
    smtp_username TEXT,
    smtp_password_secret TEXT,
    imap_host TEXT,
    imap_port INTEGER,
    imap_use_ssl INTEGER NOT NULL DEFAULT 1 CHECK(imap_use_ssl IN (0,1)),
    imap_username TEXT,
    imap_password_secret TEXT,
    resend_domain TEXT,
    resend_from_email TEXT,
    resend_reply_to TEXT,
    resend_api_key_secret TEXT,
    resend_webhook_secret_secret TEXT,
    oauth_access_token_secret TEXT,
    oauth_refresh_token_secret TEXT,
    oauth_token_expires_at TEXT,
    oauth_scopes TEXT,
    oauth_external_account_id TEXT,
    daily_limit INTEGER NOT NULL DEFAULT 100,
    last_sync_at TEXT,
    last_tested_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    UNIQUE (organization_id, email_address)
);

CREATE TABLE IF NOT EXISTS organization_llm_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('openai','azure_openai','gemini','groq','cerebras','openrouter')),
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DISABLED')),
    api_key_secret TEXT NOT NULL,
    base_url TEXT,
    azure_endpoint TEXT,
    azure_deployment TEXT,
    azure_api_version TEXT,
    default_model TEXT,
    created_by_user_id INTEGER,
    last_used_at TEXT,
    last_tested_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES app_users(id) ON DELETE SET NULL,
    UNIQUE (organization_id, provider, label)
);

INSERT OR IGNORE INTO organizations (id, name, slug, status)
VALUES (1, 'Default Organization', 'default', 'ACTIVE');

-- Leads
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL DEFAULT 1,
    email TEXT NOT NULL,
    phone_number TEXT,
    linkedin_url TEXT,
    name TEXT,
    company TEXT,
    industry TEXT,
    pain_points TEXT,
    job_title TEXT,
    seniority TEXT,
    location TEXT,
    company_size TEXT,
    company_website TEXT,
    company_description TEXT,
    recent_activity TEXT,
    enrichment_source TEXT,
    enrichment_updated_at TEXT,
    icp_score INTEGER,
    icp_rationale TEXT,
    status TEXT NOT NULL DEFAULT 'NEW' CHECK(status IN ('NEW','CONTACTED','WARM','QUALIFIED','MEETING_PROPOSED','MEETING_BOOKED','COLD','OPTED_OUT')),
    email_opt_out INTEGER NOT NULL DEFAULT 0 CHECK(email_opt_out IN (0,1)),
    touch_count INTEGER NOT NULL DEFAULT 0,
    last_contacted_at TEXT,
    last_inbound_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    UNIQUE (organization_id, email)
);

CREATE TABLE IF NOT EXISTS lead_discovery_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    campaign_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED')),
    candidates_found INTEGER NOT NULL DEFAULT 0,
    leads_qualified INTEGER NOT NULL DEFAULT 0,
    leads_imported INTEGER NOT NULL DEFAULT 0,
    search_queries TEXT,
    config TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

-- Campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    value_proposition TEXT,
    cta TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','PAUSED','INACTIVE')),
    meeting_delay_days INTEGER NOT NULL DEFAULT 1,
    max_leads_per_campaign INTEGER,
    lead_selection_order TEXT NOT NULL DEFAULT 'newest_first',
    auto_approve_drafts INTEGER NOT NULL DEFAULT 0 CHECK(auto_approve_drafts IN (0,1)),
    auto_approve_monitor_replies INTEGER NOT NULL DEFAULT 0 CHECK(auto_approve_monitor_replies IN (0,1)),
    max_emails_per_lead INTEGER NOT NULL DEFAULT 5,
    llm_routing_mode TEXT CHECK(llm_routing_mode IS NULL OR llm_routing_mode IN ('quality_first','balanced','cost_optimized')),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    UNIQUE (organization_id, name)
);

-- Campaign Sequences (Defines omnichannel follow-up steps)
CREATE TABLE IF NOT EXISTS campaign_sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    step_number INTEGER NOT NULL,
    channel TEXT NOT NULL DEFAULT 'email' CHECK(channel IN ('email','linkedin','whatsapp')),
    delay_days INTEGER NOT NULL DEFAULT 3,
    prompt_context TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE (campaign_id, step_number)
);

-- Campaign Leads (join)
CREATE TABLE IF NOT EXISTS campaign_leads (
    campaign_id INTEGER NOT NULL,
    lead_id INTEGER NOT NULL,
    emails_sent INTEGER NOT NULL DEFAULT 0,
    responded INTEGER NOT NULL DEFAULT 0 CHECK(responded IN (0,1)),
    meeting_booked INTEGER NOT NULL DEFAULT 0 CHECK(meeting_booked IN (0,1)),
    PRIMARY KEY (campaign_id, lead_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS campaign_lead_contexts (
    organization_id INTEGER NOT NULL DEFAULT 1,
    campaign_id INTEGER NOT NULL,
    lead_id INTEGER NOT NULL,
    last_outbound_subject TEXT,
    last_outbound_summary TEXT,
    last_inbound_subject TEXT,
    last_inbound_summary TEXT,
    latest_intent TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (campaign_id, lead_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

-- Staff (must exist before campaign_staff and meetings)
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    timezone TEXT,
    availability TEXT,
    dummy_slots TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    UNIQUE (organization_id, email)
);

-- Campaign Staff (join)
CREATE TABLE IF NOT EXISTS campaign_staff (
    campaign_id INTEGER NOT NULL,
    staff_id INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, staff_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE
);

-- Email messages
CREATE TABLE IF NOT EXISTS email_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL DEFAULT 1,
    lead_id INTEGER NOT NULL,
    campaign_id INTEGER,
    sequence_step_id INTEGER,
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    channel TEXT NOT NULL DEFAULT 'email' CHECK(channel IN ('email','whatsapp','linkedin')),
    subject TEXT,
    body TEXT,
    deep_link_url TEXT,
    status TEXT,
    intent TEXT,
    selected_draft_type TEXT,
    review_rationale TEXT,
    processed INTEGER NOT NULL DEFAULT 0 CHECK(processed IN (0,1)),
    approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1,-1)), -- 0: pending, 1: approved, -1: rejected
    approved_by TEXT,
    approved_at TEXT,
    scheduled_send_at TEXT,
    sent_at TEXT,
    send_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    external_message_id TEXT,
    external_thread_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL,
    FOREIGN KEY (sequence_step_id) REFERENCES campaign_sequence_steps(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS campaign_sequence_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    step_number INTEGER NOT NULL,
    delay_days INTEGER NOT NULL DEFAULT 3,
    subject_template TEXT,
    body_template TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE (campaign_id, step_number)
);

CREATE TABLE IF NOT EXISTS email_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_message_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT,
    content_base64 TEXT,
    extracted_text TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'user_upload' CHECK(source IN ('user_upload','inbound')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (email_message_id) REFERENCES email_messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    staff_id INTEGER NOT NULL,
    meet_link TEXT,
    start_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK(status IN ('SCHEDULED','CANCELLED','COMPLETED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE
);

-- Events (audit log)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER,
    type TEXT NOT NULL,
    payload TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS outbound_webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER,
    name TEXT NOT NULL,
    target_url TEXT NOT NULL,
    event_types TEXT NOT NULL DEFAULT 'all',
    secret TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DELIVERED','FAILED')),
    response_status INTEGER,
    error TEXT,
    delivered_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (webhook_id) REFERENCES outbound_webhooks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS llm_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL DEFAULT 1,
    user_id INTEGER,
    ai_usage_action_id INTEGER,
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
    pricing_version TEXT,
    routing_mode TEXT,
    billing_source TEXT NOT NULL DEFAULT 'platform' CHECK(billing_source IN ('platform','organization')),
    provider_credential_id INTEGER,
    fallback_triggered INTEGER NOT NULL DEFAULT 0 CHECK(fallback_triggered IN (0,1)),
    attempt_count INTEGER NOT NULL DEFAULT 1,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success','error')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE SET NULL,
    FOREIGN KEY (ai_usage_action_id) REFERENCES ai_usage_actions(id) ON DELETE SET NULL,
    FOREIGN KEY (provider_credential_id) REFERENCES organization_llm_credentials(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS platform_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by_user_id INTEGER,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES app_users(id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_campaign_leads_lead_id ON campaign_leads(lead_id);
CREATE INDEX IF NOT EXISTS idx_campaign_lead_contexts_lead ON campaign_lead_contexts(lead_id);
CREATE INDEX IF NOT EXISTS idx_campaign_staff_staff_id ON campaign_staff(staff_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_lead_id ON email_messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_processed ON email_messages(processed);
CREATE INDEX IF NOT EXISTS idx_email_messages_scheduled ON email_messages(status, approved, scheduled_send_at);
CREATE INDEX IF NOT EXISTS idx_email_messages_inbound_external ON email_messages(organization_id, direction, external_message_id);
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
CREATE INDEX IF NOT EXISTS idx_app_users_clerk_user_id ON app_users(clerk_user_id);
CREATE INDEX IF NOT EXISTS idx_app_users_email ON app_users(email);
CREATE INDEX IF NOT EXISTS idx_organization_users_user_id ON organization_users(user_id);
CREATE INDEX IF NOT EXISTS idx_organization_users_user_status_org ON organization_users(user_id, status, organization_id, role);
CREATE INDEX IF NOT EXISTS idx_subscription_plans_active ON subscription_plans(active);
CREATE INDEX IF NOT EXISTS idx_subscription_plans_market_currency ON subscription_plans(market_code, currency_code, active);
CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_org ON organization_subscriptions(organization_id);
CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_plan ON organization_subscriptions(plan_id);
CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_status ON organization_subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_billing_periods_org ON organization_billing_periods(organization_id, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_ai_usage_org_created ON ai_usage_actions(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_period ON ai_usage_actions(organization_id, billing_period_start, billing_period_end);
CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage_actions(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_usage_org_created ON platform_usage_events(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_platform_cost_period ON platform_cost_allocations(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_mailbox_connections_org ON mailbox_connections(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_llm_credentials_org_status ON organization_llm_credentials(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_campaigns_org ON campaigns(organization_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_org_status ON campaigns(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_leads_org_email ON leads(organization_id, email);
CREATE INDEX IF NOT EXISTS idx_staff_org_email ON staff(organization_id, email);
CREATE INDEX IF NOT EXISTS idx_email_messages_org ON email_messages(organization_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_org_status_review ON email_messages(organization_id, status, approved, direction, created_at);
CREATE INDEX IF NOT EXISTS idx_email_messages_org_campaign_created ON email_messages(organization_id, campaign_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_email_messages_unique_campaign_first_touch
ON email_messages(organization_id, campaign_id, lead_id)
WHERE direction = 'outbound'
  AND sequence_step_id IS NULL
  AND campaign_id IS NOT NULL
  AND UPPER(COALESCE(status, '')) IN ('DRAFT','SCHEDULED','SENT','GENERATING');
CREATE INDEX IF NOT EXISTS idx_events_org ON events(organization_id, created_at);
