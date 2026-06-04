import sqlite3

from services import lead_service


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL DEFAULT 1,
            email TEXT NOT NULL UNIQUE,
            name TEXT,
            company TEXT,
            industry TEXT,
            pain_points TEXT,
            status TEXT NOT NULL DEFAULT 'NEW',
            email_opt_out INTEGER NOT NULL DEFAULT 0,
            touch_count INTEGER NOT NULL DEFAULT 0,
            last_contacted_at TEXT,
            last_inbound_at TEXT,
            created_at TEXT
        );
        CREATE TABLE campaigns (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL
        );
        CREATE TABLE campaign_leads (
            campaign_id INTEGER NOT NULL,
            lead_id INTEGER NOT NULL,
            emails_sent INTEGER NOT NULL DEFAULT 0,
            responded INTEGER NOT NULL DEFAULT 0,
            meeting_booked INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, lead_id)
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER,
            type TEXT NOT NULL,
            payload TEXT,
            metadata TEXT
        );
        INSERT INTO campaigns (id, name) VALUES (10, 'Demo');
        """
    )
    return conn


class DummyConn:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *args):
        return False


def test_create_lead_assigns_campaign(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(lead_service, "get_conn", lambda: DummyConn(conn))

    result = lead_service.create_lead(
        {
            "email": "ADA@Example.com",
            "name": "Ada",
            "company": "Example",
            "campaign_ids": [10],
        }
    )

    assert result["success"] is True
    lead = conn.execute("SELECT email, name FROM leads").fetchone()
    assignment = conn.execute("SELECT campaign_id FROM campaign_leads").fetchone()
    assert lead["email"] == "ada@example.com"
    assert lead["name"] == "Ada"
    assert assignment["campaign_id"] == 10


def test_bulk_import_upserts_by_email(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(lead_service, "get_conn", lambda: DummyConn(conn))

    first = lead_service.bulk_import_leads(
        [{"email": "ada@example.com", "name": "Ada"}],
        campaign_ids=[10],
        source="test",
    )
    second = lead_service.bulk_import_leads(
        [{"email": "ada@example.com", "name": "Ada Lovelace", "company": "Analytical Engines"}],
        campaign_ids=[10],
        source="test",
    )

    row = conn.execute("SELECT name, company FROM leads WHERE email = 'ada@example.com'").fetchone()
    count = conn.execute("SELECT COUNT(*) AS count FROM leads").fetchone()["count"]
    assert first["data"]["created"] == 1
    assert second["data"]["updated"] == 1
    assert count == 1
    assert row["name"] == "Ada Lovelace"
    assert row["company"] == "Analytical Engines"
