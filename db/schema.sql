PRAGMA foreign_keys = ON;

-- Leads
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    company TEXT,
    industry TEXT,
    pain_points TEXT,
    status TEXT NOT NULL DEFAULT 'NEW' CHECK(status IN ('NEW','CONTACTED','WARM','QUALIFIED','MEETING_BOOKED','COLD','OPTED_OUT')),
    email_opt_out INTEGER NOT NULL DEFAULT 0 CHECK(email_opt_out IN (0,1)),
    touch_count INTEGER NOT NULL DEFAULT 0,
    last_contacted_at TEXT,
    last_inbound_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    value_proposition TEXT,
    cta TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','PAUSED','INACTIVE'))
);

-- Campaign Leads (join)
CREATE TABLE IF NOT EXISTS campaign_leads (
    campaign_id INTEGER NOT NULL,
    lead_id INTEGER NOT NULL,
    emails_sent INTEGER NOT NULL DEFAULT 0,
    responded INTEGER NOT NULL DEFAULT 0 CHECK(responded IN (0,1)),
    meeting_booked INTEGER NOT NULL DEFAULT 0 CHECK(meeting_booked IN (0,1)),
    PRIMARY KEY (campaign_id, lead_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

-- Email messages
CREATE TABLE IF NOT EXISTS email_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    campaign_id INTEGER,
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    subject TEXT,
    body TEXT,
    status TEXT,
    intent TEXT,
    processed INTEGER NOT NULL DEFAULT 0 CHECK(processed IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL
);

-- Meetings
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    staff_id INTEGER NOT NULL,
    meet_link TEXT,
    start_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK(status IN ('SCHEDULED','CANCELLED','COMPLETED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE
);

-- Staff
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    timezone TEXT,
    availability TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Events (audit log)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    payload TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_campaign_leads_lead_id ON campaign_leads(lead_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_lead_id ON email_messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_processed ON email_messages(processed);
CREATE INDEX IF NOT EXISTS idx_meetings_lead_id ON meetings(lead_id);
