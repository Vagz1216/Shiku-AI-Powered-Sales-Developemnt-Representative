-- Durable per-lead campaign context for deterministic follow-ups and reply memory.

CREATE TABLE IF NOT EXISTS campaign_lead_contexts (
    organization_id INTEGER NOT NULL DEFAULT 1,
    campaign_id INTEGER NOT NULL,
    lead_id INTEGER NOT NULL,
    last_outbound_subject TEXT,
    last_outbound_summary TEXT,
    last_inbound_subject TEXT,
    last_inbound_summary TEXT,
    latest_intent TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (campaign_id, lead_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_campaign_lead_contexts_lead ON campaign_lead_contexts(lead_id);
