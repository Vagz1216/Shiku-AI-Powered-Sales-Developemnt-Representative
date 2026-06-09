"""Database connection layer supporting SQLite, Aurora Data API, and PostgreSQL."""

import os
import re
import sqlite3
import threading
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(__file__))
DB_DIR = os.path.join(ROOT, 'db')
DEFAULT_DB_FILE = os.path.join(DB_DIR, 'database.sqlite3')
SCHEMA_FILE = os.path.join(DB_DIR, 'schema.sql')
SEED_FILE = os.path.join(DB_DIR, 'seed.sql')

_bootstrap_done: set[str] = set()
_bootstrap_lock = threading.Lock()


_POSTGRES_ID_TABLES = {
    "ai_usage_actions",
    "app_users",
    "campaign_sequence_steps",
    "campaigns",
    "email_attachments",
    "email_messages",
    "events",
    "leads",
    "llm_usage_events",
    "mailbox_connections",
    "meetings",
    "organization_billing_periods",
    "organization_subscriptions",
    "organizations",
    "outbound_webhooks",
    "platform_cost_allocations",
    "platform_usage_events",
    "staff",
    "subscription_plans",
    "webhook_deliveries",
}


def _is_aurora() -> bool:
    return bool(os.environ.get("DB_CLUSTER_ARN"))


def _database_url() -> str:
    from config.settings import settings

    return settings.database_url or ""


def _is_postgres_url(url: str | None = None) -> bool:
    value = (url if url is not None else _database_url()).lower()
    return value.startswith(("postgres://", "postgresql://"))


def using_aurora() -> bool:
    """True when app should use Aurora Data API (same as Terraform/App Runner DB env)."""
    return _is_aurora()


def using_postgres() -> bool:
    """True when the active database speaks PostgreSQL SQL semantics."""
    return _is_aurora() or _is_postgres_url()


class AuroraConnection:
    """Wrapper around boto3 rds-data that mirrors sqlite3.Connection patterns."""

    def __init__(self, cluster_arn: str, secret_arn: str, database: str):
        import boto3
        self._client = boto3.client(
            "rds-data",
            region_name=os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-west-2")),
        )
        self._cluster_arn = cluster_arn
        self._secret_arn = secret_arn
        self._database = database

    def execute(self, sql: str, params: tuple = ()) -> "AuroraCursor":
        pg_sql, pg_params = _sqlite_to_pg(sql, params)
        try:
            resp = self._client.execute_statement(
                resourceArn=self._cluster_arn,
                secretArn=self._secret_arn,
                database=self._database,
                sql=pg_sql,
                parameters=pg_params,
                includeResultMetadata=True,
            )
            return AuroraCursor(resp)
        except Exception as e:
            logger.error(f"Aurora SQL error: {e}\nSQL: {pg_sql}")
            raise

    def executescript(self, script: str):
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                self.execute(stmt)

    def commit(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class AuroraCursor:
    """Wraps Data API response to give fetchone/fetchall with dict rows."""

    def __init__(self, response: dict):
        self._columns = [c["name"] for c in response.get("columnMetadata", [])]
        self._records = response.get("records", [])
        self._idx = 0
        self.rowcount = int(response.get("numberOfRecordsUpdated") or 0)
        self.lastrowid = None
        for gf in response.get("generatedFields") or []:
            if "longValue" in gf:
                self.lastrowid = int(gf["longValue"])
            elif "stringValue" in gf:
                try:
                    self.lastrowid = int(gf["stringValue"])
                except ValueError:
                    pass

    def fetchone(self) -> Optional[dict]:
        if self._idx >= len(self._records):
            return None
        row = self._records[self._idx]
        self._idx += 1
        return self._to_dict(row)

    def fetchall(self) -> list[dict]:
        rows = [self._to_dict(r) for r in self._records[self._idx:]]
        self._idx = len(self._records)
        return rows

    def _to_dict(self, record: list) -> dict:
        result = {}
        for col, field in zip(self._columns, record):
            val = None
            for k in ("stringValue", "longValue", "doubleValue", "booleanValue"):
                if k in field:
                    val = field[k]
                    break
            if field.get("isNull"):
                val = None
            result[col] = val
        return result


def _sqlite_to_pg(sql: str, params: tuple) -> tuple[str, list[dict]]:
    """Convert ? placeholders to Data API named params."""
    pg_params: list[dict] = []
    counter = [0]

    def _repl(_m):
        i = counter[0]
        counter[0] += 1
        name = f"p{i}"
        v = params[i] if i < len(params) else None
        entry: dict = {"name": name}
        if v is None:
            entry["value"] = {"isNull": True}
        elif isinstance(v, bool):
            entry["value"] = {"booleanValue": v}
        elif isinstance(v, int):
            entry["value"] = {"longValue": v}
        elif isinstance(v, float):
            entry["value"] = {"doubleValue": v}
        else:
            entry["value"] = {"stringValue": str(v)}
        pg_params.append(entry)
        return f":{name}"

    pg_sql = re.sub(r"\?", _repl, sql)

    if pg_sql.strip().upper().startswith("PRAGMA"):
        return "SELECT 1", []

    return pg_sql, pg_params


class PostgresConnection:
    """Small psycopg wrapper that mirrors the sqlite3 connection surface used by services."""

    def __init__(self, database_url: str):
        import psycopg
        from psycopg.rows import dict_row

        self._conn = psycopg.connect(database_url, row_factory=dict_row)

    def execute(self, sql: str, params: tuple = ()) -> "PostgresCursor":
        pg_sql, auto_returning_id = _sqlite_to_psycopg_sql(sql)
        try:
            cur = self._conn.execute(pg_sql, params)
            return PostgresCursor(cur, auto_returning_id=auto_returning_id)
        except Exception as e:
            logger.error(f"PostgreSQL SQL error: {e}\nSQL: {pg_sql}")
            raise

    def executescript(self, script: str):
        for stmt in _split_sql_script(script):
            self.execute(stmt)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        return False


class PostgresCursor:
    """Wraps a psycopg cursor with sqlite-like lastrowid behavior."""

    def __init__(self, cursor, *, auto_returning_id: bool = False):
        self._cursor = cursor
        self._buffer: list[dict[str, Any]] = []
        self.rowcount = cursor.rowcount
        self.lastrowid = None
        if auto_returning_id:
            try:
                row = cursor.fetchone()
                if row:
                    self._buffer.append(row)
                    self.lastrowid = row.get("id")
            except Exception:
                self.lastrowid = None

    def fetchone(self) -> Optional[dict]:
        if self._buffer:
            return self._buffer.pop(0)
        return self._cursor.fetchone()

    def fetchall(self) -> list[dict]:
        rows = self._buffer + list(self._cursor.fetchall())
        self._buffer = []
        return rows


def _split_sql_script(script: str) -> list[str]:
    cleaned_lines = [
        line for line in script.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    cleaned = "\n".join(cleaned_lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def _sqlite_to_psycopg_sql(sql: str) -> tuple[str, bool]:
    """Translate the app's SQLite-style parameter SQL to psycopg/PostgreSQL SQL."""
    stripped = sql.strip()
    upper = stripped.upper()
    if upper.startswith("PRAGMA"):
        return "SELECT 1", False
    pg_sql = re.sub(r"\?", "%s", sql)
    pg_sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", pg_sql, flags=re.IGNORECASE)

    auto_returning_id = False
    if upper.startswith("INSERT") and " RETURNING " not in upper:
        match = re.match(r"\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, flags=re.IGNORECASE)
        table = match.group(1).lower() if match else ""
        if table in _POSTGRES_ID_TABLES:
            pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"
            auto_returning_id = True

    return pg_sql, auto_returning_id


def sql_group_concat_distinct(column: str, separator: str = ", ") -> str:
    """SQLite GROUP_CONCAT vs PostgreSQL string_agg."""
    esc = separator.replace("'", "''")
    if using_postgres():
        return f"COALESCE(string_agg(DISTINCT {column}::text, '{esc}'), '')"
    return f"COALESCE(GROUP_CONCAT(DISTINCT {column}), '')"


def sql_order_by_datetime(column: str) -> str:
    """SQLite datetime(col) vs PostgreSQL timestamp ordering."""
    if using_postgres():
        return column
    return f"datetime({column})"


def sql_random_order() -> str:
    """SQLite RANDOM() vs PostgreSQL random()."""
    return "random()" if using_postgres() else "RANDOM()"


def sql_bool_true() -> str:
    """SQL literal true for the app's integer-backed boolean columns."""
    return "1"


def sql_bool_false() -> str:
    """SQL literal false for the app's integer-backed boolean columns."""
    return "0"


def _ensure_db_dir():
    os.makedirs(DB_DIR, exist_ok=True)


def _resolve_db_path() -> str:
    database_url = _database_url()
    if database_url:
        if database_url.startswith("sqlite:///"):
            db_file = database_url.replace("sqlite:///", "")
            if not os.path.isabs(db_file):
                db_file = os.path.join(ROOT, db_file)
        else:
            db_file = database_url
    else:
        _ensure_db_dir()
        db_file = DEFAULT_DB_FILE
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    return db_file


def _migrate_leads_status_check(conn: sqlite3.Connection):
    """Migrate leads table to add MEETING_PROPOSED status if the CHECK constraint is outdated."""
    try:
        cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='leads'")
        row = cur.fetchone()
        if row and 'MEETING_PROPOSED' not in (row['sql'] or ''):
            logger.info("Migrating leads table to add MEETING_PROPOSED status...")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS leads_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT,
                    company TEXT,
                    industry TEXT,
                    pain_points TEXT,
                    status TEXT NOT NULL DEFAULT 'NEW' CHECK(status IN ('NEW','CONTACTED','WARM','QUALIFIED','MEETING_PROPOSED','MEETING_BOOKED','COLD','OPTED_OUT')),
                    email_opt_out INTEGER NOT NULL DEFAULT 0 CHECK(email_opt_out IN (0,1)),
                    touch_count INTEGER NOT NULL DEFAULT 0,
                    last_contacted_at TEXT,
                    last_inbound_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT OR IGNORE INTO leads_new SELECT * FROM leads;
                DROP TABLE leads;
                ALTER TABLE leads_new RENAME TO leads;
                CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
            """)
            logger.info("Leads table migration complete.")
    except Exception as e:
        logger.warning(f"Leads migration check skipped: {e}")


def _ensure_campaign_approval_columns(conn: sqlite3.Connection):
    """Add approval toggle columns that may be missing in older local DBs."""
    try:
        rows = conn.execute("PRAGMA table_info(campaigns)").fetchall()
        columns = {row["name"] for row in rows}
        if "auto_approve_monitor_replies" not in columns:
            logger.info("Adding campaigns.auto_approve_monitor_replies column...")
            conn.execute(
                "ALTER TABLE campaigns "
                "ADD COLUMN auto_approve_monitor_replies INTEGER NOT NULL DEFAULT 0 "
                "CHECK(auto_approve_monitor_replies IN (0,1))"
            )
    except Exception as e:
        logger.warning(f"Campaign approval-column migration skipped: {e}")


def _ensure_llm_usage_table(conn: sqlite3.Connection):
    """Create local usage ledger objects for databases created before migration 003."""
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS llm_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT,
                agent_name TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                request_count INTEGER NOT NULL DEFAULT 1,
                latency_ms REAL NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0,
                pricing_source TEXT,
                fallback_triggered INTEGER NOT NULL DEFAULT 0 CHECK(fallback_triggered IN (0,1)),
                attempt_count INTEGER NOT NULL DEFAULT 1,
                tool_call_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success','error')),
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_llm_usage_request_id ON llm_usage_events(request_id);
            CREATE INDEX IF NOT EXISTS idx_llm_usage_model ON llm_usage_events(provider, model);
        """)
        _add_column_if_missing(conn, "llm_usage_events", "organization_id", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "llm_usage_events", "user_id", "INTEGER")
        _add_column_if_missing(conn, "llm_usage_events", "ai_usage_action_id", "INTEGER")
        _add_column_if_missing(conn, "llm_usage_events", "pricing_version", "TEXT")
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_llm_usage_org_created_at ON llm_usage_events(organization_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_llm_usage_action ON llm_usage_events(ai_usage_action_id);
            CREATE INDEX IF NOT EXISTS idx_llm_usage_user_created ON llm_usage_events(user_id, created_at);
        """)
    except Exception as e:
        logger.warning(f"LLM usage table migration skipped: {e}")


def _ensure_usage_metering_tables(conn: sqlite3.Connection):
    """Create product usage and cost-allocation ledgers for local databases."""
    try:
        _add_column_if_missing(conn, "subscription_plans", "max_monthly_ai_credits", "INTEGER")
        _add_column_if_missing(
            conn,
            "subscription_plans",
            "overage_allowed",
            "INTEGER NOT NULL DEFAULT 0 CHECK(overage_allowed IN (0,1))",
        )
        _add_column_if_missing(conn, "subscription_plans", "overage_price_cents_per_ai_credit", "INTEGER")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS organization_billing_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                subscription_id INTEGER,
                plan_id INTEGER,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                included_ai_credits INTEGER,
                included_emails INTEGER,
                included_users INTEGER,
                included_leads INTEGER,
                overage_allowed INTEGER NOT NULL DEFAULT 0 CHECK(overage_allowed IN (0,1)),
                overage_price_cents_per_ai_credit INTEGER,
                status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','VOID')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (subscription_id) REFERENCES organization_subscriptions(id) ON DELETE SET NULL,
                FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE SET NULL,
                UNIQUE (organization_id, period_start, period_end)
            );

            CREATE TABLE IF NOT EXISTS ai_usage_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                user_id INTEGER,
                request_id TEXT,
                action_type TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                credits_used INTEGER NOT NULL DEFAULT 0,
                billing_period_start TEXT,
                billing_period_end TEXT,
                source_object_type TEXT,
                source_object_id TEXT,
                status TEXT NOT NULL DEFAULT 'success' CHECK(status IN ('success','error','void')),
                idempotency_key TEXT UNIQUE,
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS platform_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER,
                user_id INTEGER,
                event_type TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                source_object_type TEXT,
                source_object_id TEXT,
                idempotency_key TEXT UNIQUE,
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL,
                FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS platform_cost_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                category TEXT NOT NULL,
                provider TEXT,
                total_cost_usd REAL NOT NULL DEFAULT 0,
                allocation_method TEXT NOT NULL DEFAULT 'manual',
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_billing_periods_org ON organization_billing_periods(organization_id, period_start, period_end);
            CREATE INDEX IF NOT EXISTS idx_ai_usage_org_created ON ai_usage_actions(organization_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_ai_usage_period ON ai_usage_actions(organization_id, billing_period_start, billing_period_end);
            CREATE INDEX IF NOT EXISTS idx_ai_usage_user ON ai_usage_actions(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_platform_usage_org_created ON platform_usage_events(organization_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_platform_cost_period ON platform_cost_allocations(period_start, period_end);
        """)
    except Exception as e:
        logger.warning(f"Usage metering migration skipped: {e}")


def _ensure_tenant_tables(conn: sqlite3.Connection):
    """Create local multi-tenant and mailbox tables for older SQLite DBs."""
    try:
        conn.executescript("""
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

            CREATE TABLE IF NOT EXISTS subscription_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                description TEXT,
                monthly_price_cents INTEGER NOT NULL DEFAULT 0,
                trial_days INTEGER NOT NULL DEFAULT 14,
                max_users INTEGER,
                max_campaigns INTEGER,
                max_leads INTEGER,
                max_monthly_emails INTEGER,
                max_monthly_ai_tokens INTEGER,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS organization_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL UNIQUE,
                plan_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'TRIALING' CHECK(status IN ('TRIALING','ACTIVE','PAST_DUE','CANCELED','EXPIRED')),
                trial_ends_at TEXT,
                current_period_started_at TEXT,
                current_period_ends_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT,
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT
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
            CREATE INDEX IF NOT EXISTS idx_subscription_plans_active ON subscription_plans(active);
            CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_plan ON organization_subscriptions(plan_id);
            CREATE INDEX IF NOT EXISTS idx_organization_subscriptions_status ON organization_subscriptions(status);
            CREATE INDEX IF NOT EXISTS idx_mailbox_connections_org ON mailbox_connections(organization_id);
        """)
        _add_column_if_missing(
            conn,
            "organizations",
            "timezone",
            "TEXT NOT NULL DEFAULT 'Africa/Nairobi'",
        )
    except Exception as e:
        logger.warning(f"Tenant table migration skipped: {e}")


def _ensure_core_tenant_columns(conn: sqlite3.Connection):
    """Add organization ownership to core workflow tables in older SQLite DBs."""
    try:
        for table in ("campaigns", "leads", "staff", "email_messages"):
            _add_column_if_missing(conn, table, "organization_id", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "events", "organization_id", "INTEGER")
        _add_column_if_missing(conn, "outbound_webhooks", "organization_id", "INTEGER")

        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_campaigns_org ON campaigns(organization_id);
            CREATE INDEX IF NOT EXISTS idx_leads_org_email ON leads(organization_id, email);
            CREATE INDEX IF NOT EXISTS idx_staff_org_email ON staff(organization_id, email);
            CREATE INDEX IF NOT EXISTS idx_email_messages_org ON email_messages(organization_id);
            CREATE INDEX IF NOT EXISTS idx_events_org ON events(organization_id, created_at);
        """)
    except Exception as e:
        logger.warning(f"Core tenant-column migration skipped: {e}")


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    columns = {row["name"] for row in rows}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_outreach_operations_tables(conn: sqlite3.Connection):
    """Create local scheduling, sequence, and outbound integration objects for older DBs."""
    try:
        _add_column_if_missing(conn, "email_messages", "sequence_step_id", "INTEGER")
        _add_column_if_missing(conn, "email_messages", "approved_by", "TEXT")
        _add_column_if_missing(conn, "email_messages", "approved_at", "TEXT")
        _add_column_if_missing(conn, "email_messages", "scheduled_send_at", "TEXT")
        _add_column_if_missing(conn, "email_messages", "sent_at", "TEXT")
        _add_column_if_missing(conn, "email_messages", "send_attempts", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "email_messages", "last_error", "TEXT")
        _add_column_if_missing(conn, "email_messages", "external_message_id", "TEXT")
        _add_column_if_missing(conn, "email_messages", "external_thread_id", "TEXT")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS campaign_sequence_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                step_number INTEGER NOT NULL,
                delay_days INTEGER NOT NULL DEFAULT 3,
                subject_template TEXT,
                body_template TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                UNIQUE (campaign_id, step_number)
            );

            CREATE TABLE IF NOT EXISTS campaign_lead_contexts (
                organization_id INTEGER NOT NULL DEFAULT 1,
                campaign_id INTEGER NOT NULL,
                lead_id INTEGER NOT NULL,
                last_outbound_subject TEXT,
                last_outbound_summary TEXT,
                last_inbound_subject TEXT,
                last_inbound_summary TEXT,
                latest_intent TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (campaign_id, lead_id),
                FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS outbound_webhooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                target_url TEXT NOT NULL,
                event_types TEXT NOT NULL DEFAULT 'all',
                secret TEXT,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                webhook_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DELIVERED','FAILED')),
                response_status INTEGER,
                error TEXT,
                delivered_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (webhook_id) REFERENCES outbound_webhooks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_email_messages_scheduled ON email_messages(status, approved, scheduled_send_at);
            CREATE INDEX IF NOT EXISTS idx_sequence_steps_campaign ON campaign_sequence_steps(campaign_id, step_number);
            CREATE INDEX IF NOT EXISTS idx_campaign_lead_contexts_lead ON campaign_lead_contexts(lead_id);
            CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries(webhook_id, created_at);
        """)
    except Exception as e:
        logger.warning(f"Outreach operations migration skipped: {e}")


def _bootstrap_schema(conn: sqlite3.Connection, db_file: str):
    with _bootstrap_lock:
        if db_file in _bootstrap_done:
            return
        if os.path.exists(SCHEMA_FILE):
            with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
                try:
                    conn.executescript(f.read())
                except sqlite3.OperationalError as e:
                    # Existing SQLite files may have old table definitions. If the
                    # current schema adds indexes on newly introduced columns, let
                    # the compatibility migrations below add those columns first.
                    logger.warning(f"Schema bootstrap continued after compatibility error: {e}")
        _migrate_leads_status_check(conn)
        _ensure_campaign_approval_columns(conn)
        _ensure_llm_usage_table(conn)
        _ensure_tenant_tables(conn)
        _ensure_usage_metering_tables(conn)
        _ensure_core_tenant_columns(conn)
        _ensure_outreach_operations_tables(conn)
        cur = conn.execute("SELECT count(1) as cnt FROM campaigns LIMIT 1")
        row = cur.fetchone()
        if (row is None or row["cnt"] == 0) and os.path.exists(SEED_FILE):
            with open(SEED_FILE, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
        _bootstrap_done.add(db_file)


def get_conn():
    """Return a database connection.
    Aurora Data API when DB_CLUSTER_ARN is set, PostgreSQL when DATABASE_URL is
    postgresql://, otherwise SQLite."""
    if _is_aurora():
        return AuroraConnection(
            cluster_arn=os.environ["DB_CLUSTER_ARN"],
            secret_arn=os.environ["DB_SECRET_ARN"],
            database=os.environ.get("DB_NAME", "sdr"),
        )

    database_url = _database_url()
    if _is_postgres_url(database_url):
        return PostgresConnection(database_url)

    db_file = _resolve_db_path()
    conn = sqlite3.connect(
        db_file, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _bootstrap_schema(conn, db_file)
    return conn


def dict_from_row(row) -> Optional[dict]:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return {k: row[k] for k in row.keys()}
