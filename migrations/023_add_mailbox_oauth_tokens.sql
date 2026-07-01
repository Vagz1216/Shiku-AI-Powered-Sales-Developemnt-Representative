ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS oauth_access_token_secret TEXT;
ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS oauth_refresh_token_secret TEXT;
ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS oauth_token_expires_at TIMESTAMP;
ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS oauth_scopes TEXT;
ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS oauth_external_account_id TEXT;
