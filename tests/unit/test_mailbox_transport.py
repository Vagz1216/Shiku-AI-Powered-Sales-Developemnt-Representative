import sqlite3

import pytest

from schema import SendEmailResult
from services import mailbox_transport


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def route_db(tmp_path, monkeypatch):
    db_path = tmp_path / "mailbox-route.sqlite3"
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                email_opt_out INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL
            );
            CREATE TABLE campaign_leads (
                campaign_id INTEGER NOT NULL,
                lead_id INTEGER NOT NULL
            );
            """
        )

    monkeypatch.setattr(mailbox_transport, "get_conn", lambda: _connect(db_path))
    return db_path


def test_unknown_sender_is_not_processed(route_db):
    route = mailbox_transport._route_inbound_sender("unknown@example.com")

    assert route == {
        "process": False,
        "reason": "sender is not a known lead",
        "campaign_id": None,
    }


def test_known_lead_without_active_campaign_is_not_processed(route_db):
    with _connect(route_db) as conn:
        conn.execute("INSERT INTO leads (email) VALUES ('lead@example.com')")

    route = mailbox_transport._route_inbound_sender("lead@example.com")

    assert route == {
        "process": False,
        "reason": "known lead has no active campaign",
        "campaign_id": None,
    }


def test_opted_out_lead_is_not_processed(route_db):
    with _connect(route_db) as conn:
        conn.execute("INSERT INTO leads (email, email_opt_out) VALUES ('lead@example.com', 1)")

    route = mailbox_transport._route_inbound_sender("lead@example.com")

    assert route == {
        "process": False,
        "reason": "lead is opted out",
        "campaign_id": None,
    }


def test_known_campaign_lead_is_processed(route_db):
    with _connect(route_db) as conn:
        cur = conn.execute("INSERT INTO leads (email) VALUES ('lead@example.com')")
        lead_id = cur.lastrowid
        cur = conn.execute("INSERT INTO campaigns (status) VALUES ('ACTIVE')")
        campaign_id = cur.lastrowid
        conn.execute(
            "INSERT INTO campaign_leads (campaign_id, lead_id) VALUES (?, ?)",
            (campaign_id, lead_id),
        )

    route = mailbox_transport._route_inbound_sender("lead@example.com")

    assert route == {
        "process": True,
        "reason": "known campaign lead",
        "campaign_id": campaign_id,
    }


def test_send_mailbox_email_uses_tenant_resend_credentials(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        mailbox_transport,
        "_resolve_mailbox",
        lambda mailbox_id=None, organization_id=None, provider=None: {
            "id": 7,
            "organization_id": organization_id or 2,
            "provider": "resend",
            "email_address": "sdr@tenant.test",
            "resend_from_email": "Tenant <sdr@tenant.test>",
            "resend_reply_to": "reply@tenant.test",
            "resend_api_key_secret": "local:cmVfdGVuYW50",
            "daily_limit": 0,
        },
    )

    def fake_send_resend_email(**kwargs):
        captured.update(kwargs)
        return SendEmailResult(ok=True, message_id="email_tenant")

    monkeypatch.setattr(mailbox_transport, "send_resend_email", fake_send_resend_email)

    result = mailbox_transport.send_mailbox_email(
        email="lead@example.com",
        name="Lead",
        subject="Hello",
        body="Body",
        organization_id=2,
    )

    assert result.ok is True
    assert captured["api_key"] == "re_tenant"
    assert captured["from_email"] == "Tenant <sdr@tenant.test>"
    assert captured["reply_to"] == "reply@tenant.test"
