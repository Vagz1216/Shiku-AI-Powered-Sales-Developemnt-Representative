import sqlite3

from tools import email_reply


def test_campaign_auto_approves_monitor_replies(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE campaigns (
            id INTEGER PRIMARY KEY,
            auto_approve_monitor_replies INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO campaigns (id, auto_approve_monitor_replies) VALUES (1, 1), (2, 0);
        """
    )

    class DummyConn:
        def __enter__(self):
            return conn

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(email_reply, "get_conn", lambda: DummyConn(), raising=False)

    import utils.db_connection

    monkeypatch.setattr(utils.db_connection, "get_conn", lambda: DummyConn())

    assert email_reply.campaign_auto_approves_monitor_replies(1) is True
    assert email_reply.campaign_auto_approves_monitor_replies(2) is False
    assert email_reply.campaign_auto_approves_monitor_replies(None) is False


def test_save_reply_draft_reuses_existing_source_message(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE campaigns (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            auto_approve_monitor_replies INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            email TEXT NOT NULL
        );
        CREATE TABLE email_messages (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            lead_id INTEGER,
            campaign_id INTEGER,
            direction TEXT NOT NULL,
            subject TEXT,
            body TEXT,
            status TEXT,
            processed INTEGER,
            approved INTEGER,
            external_message_id TEXT,
            external_thread_id TEXT,
            created_at TEXT
        );
        INSERT INTO campaigns (id, organization_id) VALUES (20, 1);
        INSERT INTO leads (id, organization_id, email) VALUES (1, 1, 'lead@example.com');
        """
    )

    import utils.db_connection

    monkeypatch.setattr(utils.db_connection, "get_conn", lambda: conn)

    first = email_reply.save_reply_draft(
        "lead@example.com",
        "First body",
        thread_id="<thread@example.com>",
        subject="Re: Tell me more",
        campaign_id=20,
        original_message_id="<source@example.com>",
    )
    second = email_reply.save_reply_draft(
        "lead@example.com",
        "Second body should not overwrite",
        thread_id="<thread@example.com>",
        subject="Re: Tell me more",
        campaign_id=20,
        original_message_id="<source@example.com>",
    )

    rows = conn.execute("SELECT * FROM email_messages").fetchall()
    assert len(rows) == 1
    assert first["draft_id"] == second["draft_id"]
    assert second["method"] == "existing_draft"
    assert rows[0]["body"] == "First body"
    assert rows[0]["external_message_id"] == "<source@example.com>"
