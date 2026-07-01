-- Store user-facing AI review context for draft approvals.
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS selected_draft_type TEXT;
ALTER TABLE email_messages ADD COLUMN IF NOT EXISTS review_rationale TEXT;
