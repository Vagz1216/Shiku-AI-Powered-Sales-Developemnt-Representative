-- Prevent duplicate first-touch outreach for the same organization/campaign/lead.
-- Follow-up sequence messages are excluded because they carry sequence_step_id.

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_messages_unique_campaign_first_touch
ON email_messages(organization_id, campaign_id, lead_id)
WHERE direction = 'outbound'
  AND sequence_step_id IS NULL
  AND campaign_id IS NOT NULL
  AND UPPER(COALESCE(status, '')) IN ('DRAFT','SCHEDULED','SENT','GENERATING');
