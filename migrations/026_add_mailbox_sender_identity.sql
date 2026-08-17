-- Add tenant-controlled sender identity fields to mailbox connections.

ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS sender_display_name TEXT;
ALTER TABLE mailbox_connections ADD COLUMN IF NOT EXISTS company_display_name TEXT;
