"""Database connection layer supporting SQLite (local) and Aurora Data API (production)."""

import os
import re
import sqlite3
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(__file__))
DB_DIR = os.path.join(ROOT, 'db')
DEFAULT_DB_FILE = os.path.join(DB_DIR, 'database.sqlite3')
SCHEMA_FILE = os.path.join(DB_DIR, 'schema.sql')
SEED_FILE = os.path.join(DB_DIR, 'seed.sql')

_bootstrap_done: set[str] = set()
_bootstrap_lock = threading.Lock()


def _is_aurora() -> bool:
    return bool(os.environ.get("DB_CLUSTER_ARN"))


def using_aurora() -> bool:
    """True when app should use Aurora Data API (same as Terraform/App Runner DB env)."""
    return _is_aurora()


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


def sql_group_concat_distinct(column: str, separator: str = ", ") -> str:
    """SQLite GROUP_CONCAT vs PostgreSQL string_agg for Aurora."""
    esc = separator.replace("'", "''")
    if _is_aurora():
        return f"COALESCE(string_agg(DISTINCT {column}::text, '{esc}'), '')"
    return f"COALESCE(GROUP_CONCAT(DISTINCT {column}), '')"


def sql_order_by_datetime(column: str) -> str:
    """SQLite datetime(col) vs PostgreSQL timestamp ordering."""
    if _is_aurora():
        return column
    return f"datetime({column})"


def sql_random_order() -> str:
    """SQLite RANDOM() vs PostgreSQL random()."""
    return "random()" if _is_aurora() else "RANDOM()"


def _ensure_db_dir():
    os.makedirs(DB_DIR, exist_ok=True)


def _resolve_db_path() -> str:
    from config.settings import settings
    if settings.database_url:
        if settings.database_url.startswith("sqlite:///"):
            db_file = settings.database_url.replace("sqlite:///", "")
            if not os.path.isabs(db_file):
                db_file = os.path.join(ROOT, db_file)
        else:
            db_file = settings.database_url
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


def _bootstrap_schema(conn: sqlite3.Connection, db_file: str):
    with _bootstrap_lock:
        if db_file in _bootstrap_done:
            return
        if os.path.exists(SCHEMA_FILE):
            with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
        _migrate_leads_status_check(conn)
        cur = conn.execute("SELECT count(1) as cnt FROM campaigns LIMIT 1")
        row = cur.fetchone()
        if (row is None or row["cnt"] == 0) and os.path.exists(SEED_FILE):
            with open(SEED_FILE, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
        _bootstrap_done.add(db_file)


def get_conn():
    """Return a database connection.
    Aurora Data API when DB_CLUSTER_ARN is set, otherwise SQLite."""
    if _is_aurora():
        return AuroraConnection(
            cluster_arn=os.environ["DB_CLUSTER_ARN"],
            secret_arn=os.environ["DB_SECRET_ARN"],
            database=os.environ.get("DB_NAME", "sdr"),
        )

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
