-- Store tenant-owned Resend credentials on mailbox connections.

ALTER TABLE mailbox_connections ADD COLUMN resend_api_key_secret TEXT;
ALTER TABLE mailbox_connections ADD COLUMN resend_webhook_secret_secret TEXT;
