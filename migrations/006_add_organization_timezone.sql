-- Store each organization's display timezone. Default is Nairobi / East Africa Time.

ALTER TABLE organizations ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi';
