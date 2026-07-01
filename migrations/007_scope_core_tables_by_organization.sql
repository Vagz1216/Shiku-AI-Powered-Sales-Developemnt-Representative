-- Scope core SDR workflow tables to organizations.
-- Existing rows are assigned to the default organization.

ALTER TABLE campaigns ADD COLUMN organization_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE leads ADD COLUMN organization_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE staff ADD COLUMN organization_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE email_messages ADD COLUMN organization_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE events ADD COLUMN organization_id INTEGER;
ALTER TABLE outbound_webhooks ADD COLUMN organization_id INTEGER;

CREATE INDEX IF NOT EXISTS idx_campaigns_org ON campaigns(organization_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_org_status ON campaigns(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_leads_org_email ON leads(organization_id, email);
CREATE INDEX IF NOT EXISTS idx_staff_org_email ON staff(organization_id, email);
CREATE INDEX IF NOT EXISTS idx_email_messages_org ON email_messages(organization_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_org_status_review ON email_messages(organization_id, status, approved, direction, created_at);
CREATE INDEX IF NOT EXISTS idx_email_messages_org_campaign_created ON email_messages(organization_id, campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_org ON events(organization_id, created_at);
