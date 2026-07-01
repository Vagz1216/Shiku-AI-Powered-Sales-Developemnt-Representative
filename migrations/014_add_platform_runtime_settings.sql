CREATE TABLE IF NOT EXISTS platform_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
