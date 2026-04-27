import os
import sqlite3
import threading
from typing import Optional
from config.settings import AppConfig

settings = AppConfig()

ROOT = os.path.dirname(os.path.dirname(__file__))
DB_DIR = os.path.join(ROOT, 'db')
DEFAULT_DB_FILE = os.path.join(DB_DIR, 'database.sqlite3')
SCHEMA_FILE = os.path.join(DB_DIR, 'schema.sql')
SEED_FILE = os.path.join(DB_DIR, 'seed.sql')

_bootstrap_done: set[str] = set()
_bootstrap_lock = threading.Lock()


def _ensure_db_dir():
    os.makedirs(DB_DIR, exist_ok=True)


def _resolve_db_path() -> str:
    """Resolve the database file path from settings."""
    if settings.database_url:
        if settings.database_url.startswith('sqlite:///'):
            db_file = settings.database_url.replace('sqlite:///', '')
            if not os.path.isabs(db_file):
                db_file = os.path.join(ROOT, db_file)
        else:
            db_file = settings.database_url
    else:
        _ensure_db_dir()
        db_file = DEFAULT_DB_FILE

    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    return db_file


def _bootstrap_schema(conn: sqlite3.Connection, db_file: str):
    """Apply schema + seed data once per database file per process."""
    with _bootstrap_lock:
        if db_file in _bootstrap_done:
            return

        if os.path.exists(SCHEMA_FILE):
            with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())

        cur = conn.execute("SELECT count(1) as cnt FROM campaigns LIMIT 1")
        row = cur.fetchone()
        if (row is None or row['cnt'] == 0) and os.path.exists(SEED_FILE):
            with open(SEED_FILE, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())

        _bootstrap_done.add(db_file)


def get_conn() -> sqlite3.Connection:
    """Return a sqlite3.Connection with foreign keys enabled and row factory as dict.

    Schema bootstrap and seeding only run once per process per database file.
    """
    db_file = _resolve_db_path()

    conn = sqlite3.connect(db_file, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')

    _bootstrap_schema(conn, db_file)
    return conn


def dict_from_row(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}
