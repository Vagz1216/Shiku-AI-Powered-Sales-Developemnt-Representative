-- Migration 028: Add omnichannel campaign sequence metadata table for PostgreSQL deployments.
CREATE TABLE IF NOT EXISTS campaign_sequences (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    channel TEXT NOT NULL DEFAULT 'email' CHECK(channel IN ('email','linkedin','whatsapp')),
    delay_days INTEGER NOT NULL DEFAULT 3,
    prompt_context TEXT,
    UNIQUE (campaign_id, step_number)
);

CREATE INDEX IF NOT EXISTS idx_campaign_sequences_campaign_step
ON campaign_sequences(campaign_id, step_number);
