-- Add per-campaign approval control for webhook/email-monitor generated replies.

-- SQLite:
ALTER TABLE campaigns
ADD COLUMN auto_approve_monitor_replies INTEGER NOT NULL DEFAULT 0 CHECK(auto_approve_monitor_replies IN (0,1));

-- PostgreSQL/Aurora:
-- ALTER TABLE campaigns
-- ADD COLUMN auto_approve_monitor_replies BOOLEAN NOT NULL DEFAULT FALSE;
