-- Adds approved scheduled sending, campaign follow-up sequences, and outbound webhook ledgers.

ALTER TABLE email_messages ADD COLUMN sequence_step_id INTEGER;
ALTER TABLE email_messages ADD COLUMN approved_by TEXT;
ALTER TABLE email_messages ADD COLUMN approved_at TEXT;
ALTER TABLE email_messages ADD COLUMN scheduled_send_at TEXT;
ALTER TABLE email_messages ADD COLUMN sent_at TEXT;
ALTER TABLE email_messages ADD COLUMN send_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE email_messages ADD COLUMN last_error TEXT;
ALTER TABLE email_messages ADD COLUMN external_message_id TEXT;
ALTER TABLE email_messages ADD COLUMN external_thread_id TEXT;

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

CREATE TABLE IF NOT EXISTS outbound_webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_url TEXT NOT NULL,
    event_types TEXT NOT NULL DEFAULT 'all',
    secret TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT
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

CREATE INDEX IF NOT EXISTS idx_email_messages_scheduled ON email_messages(status, approved, scheduled_send_at);
CREATE INDEX IF NOT EXISTS idx_sequence_steps_campaign ON campaign_sequence_steps(campaign_id, step_number);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries(webhook_id, created_at);
