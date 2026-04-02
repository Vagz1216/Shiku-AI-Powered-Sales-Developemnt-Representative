import os
import sqlite3
from typing import Optional
from config.settings import AppConfig

settings = AppConfig()

ROOT = os.path.dirname(os.path.dirname(__file__))
DB_DIR = os.path.join(ROOT, 'db')
DEFAULT_DB_FILE = os.path.join(DB_DIR, 'database.sqlite3')
SCHEMA_FILE = os.path.join(DB_DIR, 'schema.sql')
SEED_FILE = os.path.join(DB_DIR, 'seed.sql')


def _ensure_db_dir():
    os.makedirs(DB_DIR, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    """Return a sqlite3.Connection with foreign keys enabled and row factory as dict.

    This function bootstraps the schema (safe to call multiple times) and seeds sample
    data if the database is empty.
    """
    # Handle both file paths and database URLs
    if settings.database_url:
        if settings.database_url.startswith('sqlite:///'):
            # Extract file path from SQLite URL and make it absolute
            db_file = settings.database_url.replace('sqlite:///', '')
            if not os.path.isabs(db_file):
                db_file = os.path.join(ROOT, db_file)
        else:
            # Use the database_url as is (could be a file path)
            db_file = settings.database_url
    else:
        # Default to sqlite file in db directory
        _ensure_db_dir()
        db_file = DEFAULT_DB_FILE
    
    # Ensure the directory exists for the database file
    db_dir = os.path.dirname(db_file)
    os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(db_file, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')

    # Apply schema (idempotent)
    if os.path.exists(SCHEMA_FILE):
        with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
            sql = f.read()
            conn.executescript(sql)

    # Seed if campaigns table is empty
    cur = conn.execute("SELECT count(1) as cnt FROM campaigns LIMIT 1")
    row = cur.fetchone()
    need_seed = True
    if row is not None and row['cnt'] > 0:
        need_seed = False

    if need_seed and os.path.exists(SEED_FILE):
        with open(SEED_FILE, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())

    return conn


def dict_from_row(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}
