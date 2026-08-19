ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS signature_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS signature_text TEXT;
ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS signature_html TEXT;
