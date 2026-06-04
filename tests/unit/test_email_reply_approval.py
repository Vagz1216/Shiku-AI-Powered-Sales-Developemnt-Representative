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
