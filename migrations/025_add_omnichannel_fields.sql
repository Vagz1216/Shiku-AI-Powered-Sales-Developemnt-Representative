-- Migration 025: Add omnichannel fields for leads and messages
-- Add phone_number and linkedin_url to leads
ALTER TABLE leads ADD COLUMN IF NOT EXISTS phone_number TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_url TEXT;

-- Add channel and deep_link_url to email_messages
-- SQLite does not support adding constraints like CHECK with ALTER TABLE easily, so we just add the columns
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'email';
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS deep_link_url TEXT;
