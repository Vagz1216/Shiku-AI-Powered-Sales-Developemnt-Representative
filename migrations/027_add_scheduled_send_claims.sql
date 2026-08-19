-- Add claim timestamp for multi-worker scheduled-send processing.

ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS scheduled_claimed_at TIMESTAMP;

DROP INDEX IF EXISTS idx_email_messages_unique_campaign_first_touch;

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_messages_unique_campaign_first_touch
ON email_messages(organization_id, campaign_id, lead_id)
WHERE direction = 'outbound'
  AND sequence_step_id IS NULL
  AND campaign_id IS NOT NULL
  AND UPPER(COALESCE(status, '')) IN ('DRAFT','SCHEDULED','SENDING','SENT','GENERATING');
