-- PostgreSQL schema for SDR platform (Aurora Serverless v2)

CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    company TEXT,
    industry TEXT,
    pain_points TEXT,
    status TEXT NOT NULL DEFAULT 'NEW' CHECK(status IN ('NEW','CONTACTED','WARM','QUALIFIED','MEETING_PROPOSED','MEETING_BOOKED','COLD','OPTED_OUT')),
    email_opt_out BOOLEAN NOT NULL DEFAULT FALSE,
    touch_count INTEGER NOT NULL DEFAULT 0,
    last_contacted_at TIMESTAMP,
    last_inbound_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    value_proposition TEXT,
    cta TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','PAUSED','INACTIVE')),
    meeting_delay_days INTEGER NOT NULL DEFAULT 1,
    max_leads_per_campaign INTEGER,
    lead_selection_order TEXT NOT NULL DEFAULT 'newest_first',
    auto_approve_drafts BOOLEAN NOT NULL DEFAULT FALSE,
    max_emails_per_lead INTEGER NOT NULL DEFAULT 5
);

CREATE TABLE IF NOT EXISTS campaign_leads (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    emails_sent INTEGER NOT NULL DEFAULT 0,
    responded BOOLEAN NOT NULL DEFAULT FALSE,
    meeting_booked BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (campaign_id, lead_id)
);

-- staff must exist before campaign_staff (FK to staff.id)
CREATE TABLE IF NOT EXISTS staff (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    timezone TEXT,
    availability TEXT,
    dummy_slots TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_staff (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, staff_id)
);

CREATE TABLE IF NOT EXISTS email_messages (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    subject TEXT,
    body TEXT,
    status TEXT,
    intent TEXT,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1,-1)),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
    meet_link TEXT,
    start_time TIMESTAMP NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK(status IN ('SCHEDULED','CANCELLED','COMPLETED')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    payload TEXT,
    metadata TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_campaign_leads_lead_id ON campaign_leads(lead_id);
CREATE INDEX IF NOT EXISTS idx_campaign_staff_staff_id ON campaign_staff(staff_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_lead_id ON email_messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_processed ON email_messages(processed);
CREATE INDEX IF NOT EXISTS idx_meetings_lead_id ON meetings(lead_id);
