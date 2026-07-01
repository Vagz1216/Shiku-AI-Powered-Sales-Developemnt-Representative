CREATE INDEX IF NOT EXISTS idx_organization_users_user_status_org
    ON organization_users(user_id, status, organization_id, role);

CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_org
    ON organization_subscriptions(organization_id);
