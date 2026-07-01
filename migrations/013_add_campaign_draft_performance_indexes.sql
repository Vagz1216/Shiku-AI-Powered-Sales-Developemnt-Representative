-- Adds compound indexes for tenant-scoped campaign and draft review reads.

CREATE INDEX IF NOT EXISTS idx_campaigns_org_status
    ON campaigns(organization_id, status);

CREATE INDEX IF NOT EXISTS idx_email_messages_org_status_review
    ON email_messages(organization_id, status, approved, direction, created_at);

CREATE INDEX IF NOT EXISTS idx_email_messages_org_campaign_created
    ON email_messages(organization_id, campaign_id, created_at);
