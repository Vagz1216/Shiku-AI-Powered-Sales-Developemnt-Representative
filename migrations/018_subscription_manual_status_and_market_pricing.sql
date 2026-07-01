ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS currency_code TEXT NOT NULL DEFAULT 'USD';

ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS market_code TEXT NOT NULL DEFAULT 'GLOBAL';

UPDATE subscription_plans
SET
    currency_code = UPPER(COALESCE(NULLIF(currency_code, ''), 'USD')),
    market_code = UPPER(COALESCE(NULLIF(market_code, ''), 'GLOBAL'));

CREATE INDEX IF NOT EXISTS idx_subscription_plans_market_currency
    ON subscription_plans(market_code, currency_code, active);
