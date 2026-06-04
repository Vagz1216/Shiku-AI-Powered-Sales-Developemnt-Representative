CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi',
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','SUSPENDED','ARCHIVED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clerk_user_id TEXT NOT NULL UNIQUE,
    email TEXT,
    name TEXT,
    platform_role TEXT NOT NULL DEFAULT 'user' CHECK(platform_role IN ('system_owner','user')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS organization_users (
    organization_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('org_admin','sales_manager','sales_user','viewer')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','INVITED','DISABLED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (organization_id, user_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mailbox_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('smtp_imap','resend','gmail','microsoft')),
    display_name TEXT,
    email_address TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','CONNECTED','FAILED','DISABLED')),
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_use_ssl INTEGER NOT NULL DEFAULT 1 CHECK(smtp_use_ssl IN (0,1)),
    smtp_username TEXT,
    smtp_password_secret TEXT,
    imap_host TEXT,
    imap_port INTEGER,
    imap_use_ssl INTEGER NOT NULL DEFAULT 1 CHECK(imap_use_ssl IN (0,1)),
    imap_username TEXT,
    imap_password_secret TEXT,
    resend_domain TEXT,
    resend_from_email TEXT,
    resend_reply_to TEXT,
    daily_limit INTEGER NOT NULL DEFAULT 100,
    last_sync_at TEXT,
    last_tested_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    UNIQUE (organization_id, email_address)
);

INSERT OR IGNORE INTO organizations (id, name, slug, status)
VALUES (1, 'Default Organization', 'default', 'ACTIVE');

CREATE INDEX IF NOT EXISTS idx_app_users_clerk_user_id ON app_users(clerk_user_id);
CREATE INDEX IF NOT EXISTS idx_app_users_email ON app_users(email);
CREATE INDEX IF NOT EXISTS idx_organization_users_user_id ON organization_users(user_id);
CREATE INDEX IF NOT EXISTS idx_mailbox_connections_org ON mailbox_connections(organization_id);
