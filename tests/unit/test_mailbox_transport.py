import sqlite3
import datetime
from email.message import EmailMessage

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
            "sender_display_name": "Alex",
            "resend_from_email": "sdr@tenant.test",
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
    assert captured["from_email"] == "Alex <sdr@tenant.test>"
    assert captured["reply_to"] == "reply@tenant.test"


def test_send_mailbox_email_appends_mailbox_signature(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        mailbox_transport,
        "_resolve_mailbox",
        lambda mailbox_id=None, organization_id=None, provider=None: {
            "id": 7,
            "organization_id": organization_id or 2,
            "provider": "resend",
            "email_address": "sdr@tenant.test",
            "sender_display_name": "Alex",
            "resend_from_email": "sdr@tenant.test",
            "resend_api_key_secret": "local:cmVfdGVuYW50",
            "daily_limit": 0,
            "signature_enabled": 1,
            "signature_text": "Alex\nStayEZ",
            "signature_html": "<strong>Alex</strong><br><span>StayEZ</span>",
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
        html_body="<p>Body</p>",
        organization_id=2,
    )

    assert result.ok is True
    assert captured["body"] == "Body\n\nAlex\nStayEZ"
    assert captured["html_body"] == "<p>Body</p><br><br><strong>Alex</strong><br><span>StayEZ</span>"


def test_mailbox_daily_limit_uses_portable_date_filter(tmp_path, monkeypatch):
    db_path = tmp_path / "mailbox-limit.sqlite3"
    today = datetime.date.today().isoformat()
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE email_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO email_messages (organization_id, direction, status, created_at) VALUES (?, ?, ?, ?)",
            (1, "outbound", "SENT", f"{today}T09:30:00Z"),
        )

    monkeypatch.setattr(mailbox_transport, "get_conn", lambda: _connect(db_path))

    error = mailbox_transport._mailbox_daily_limit_error(
        {"organization_id": 1, "daily_limit": 1}
    )

    assert error == "Mailbox daily limit reached (1). Try again tomorrow."


def test_smtp_send_sets_date_header_and_local_hostname(monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, local_hostname=None):
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout
            captured["local_hostname"] = local_hostname

        def login(self, username, password):
            captured["username"] = username
            captured["password"] = password

        def send_message(self, message):
            captured["message"] = message

        def quit(self):
            captured["quit"] = True

    monkeypatch.setattr(mailbox_transport.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mailbox_transport.settings, "smtp_helo_hostname", None)

    message_id = mailbox_transport._send_via_smtp(
        {
            "smtp_host": "mail.stayez.co.ke",
            "smtp_port": 465,
            "smtp_use_ssl": 1,
            "smtp_username": "info@stayez.co.ke",
            "smtp_password_secret": "local:cGFzcw==",
            "email_address": "info@stayez.co.ke",
            "display_name": "Stayez Homes",
        },
        to_email="lead@example.com",
        to_name="Lead",
        subject="Hello",
        body="Body",
        html_body=None,
        attachments=None,
        headers=None,
    )

    assert captured["local_hostname"] == "mail.stayez.co.ke"
    assert captured["username"] == "info@stayez.co.ke"
    assert captured["password"] == "pass"
    assert captured["message"]["Date"]
    assert captured["message"]["Message-ID"] == message_id


def test_smtp_send_prefers_configured_helo_hostname(monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, local_hostname=None):
            captured["local_hostname"] = local_hostname

        def login(self, username, password):
            pass

        def send_message(self, message):
            pass

        def quit(self):
            pass

    monkeypatch.setattr(mailbox_transport.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mailbox_transport.settings, "smtp_helo_hostname", "mail.example.com")

    mailbox_transport._send_via_smtp(
        {
            "smtp_host": "smtp.vendor.test",
            "smtp_port": 465,
            "smtp_use_ssl": 1,
            "smtp_username": "info@example.com",
            "smtp_password_secret": "local:cGFzcw==",
            "email_address": "info@example.com",
            "display_name": "Example",
        },
        to_email="lead@example.com",
        to_name="Lead",
        subject="Hello",
        body="Body",
        html_body=None,
        attachments=None,
        headers=None,
    )

    assert captured["local_hostname"] == "mail.example.com"


@pytest.mark.anyio
async def test_sync_marks_skipped_imap_messages_seen(tmp_path, monkeypatch):
    db_path = tmp_path / "mailbox-sync.sqlite3"
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE email_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER,
                direction TEXT,
                external_message_id TEXT
            );
            """
        )

    raw = EmailMessage()
    raw["From"] = "Unknown <unknown@example.com>"
    raw["To"] = "info@example.com"
    raw["Subject"] = "Not a campaign reply"
    raw["Message-ID"] = "<skip-test@example.com>"
    raw.set_content("Hello")

    class FakeIMAP:
        def __init__(self):
            self.seen_uids = []

        def login(self, username, password):
            pass

        def select(self, mailbox):
            pass

        def uid(self, command, *args):
            if command == "SEARCH":
                return "OK", [b"101"]
            if command == "FETCH":
                return "OK", [(b"101 (BODY[])", raw.as_bytes())]
            if command == "STORE":
                self.seen_uids.append(args[0])
                return "OK", []
            raise AssertionError(command)

        def logout(self):
            pass

    fake_imap = FakeIMAP()
    monkeypatch.setattr(mailbox_transport, "get_conn", lambda: _connect(db_path))
    monkeypatch.setattr(
        mailbox_transport,
        "_resolve_mailbox",
        lambda mailbox_id=None, organization_id=None, provider=None: {
            "id": 12,
            "organization_id": organization_id or 1,
            "provider": "smtp_imap",
            "email_address": "info@example.com",
            "imap_username": "info@example.com",
            "imap_password_secret": "local:cGFzcw==",
        },
    )
    monkeypatch.setattr(mailbox_transport, "_imap_client", lambda mailbox: fake_imap)
    monkeypatch.setattr(
        mailbox_transport,
        "_route_inbound_sender",
        lambda sender_email, organization_id=None: {
            "process": False,
            "reason": "sender is not a known lead",
            "campaign_id": None,
        },
    )
    monkeypatch.setattr(mailbox_transport, "_update_mailbox_sync_state", lambda mailbox_id, error: None)

    result = await mailbox_transport.sync_unread_mailbox(organization_id=1, mailbox_id=12)

    assert result["checked"] == 1
    assert result["skipped"][0]["reason"] == "sender is not a known lead"
    assert fake_imap.seen_uids == [b"101"]


def test_list_connected_imap_mailboxes_filters_connected_smtp_imap(tmp_path, monkeypatch):
    db_path = tmp_path / "mailboxes.sqlite3"
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE mailbox_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                email_address TEXT NOT NULL,
                display_name TEXT
            );
            INSERT INTO mailbox_connections
                (organization_id, provider, status, email_address, display_name)
            VALUES
                (1, 'smtp_imap', 'CONNECTED', 'one@example.com', 'One'),
                (1, 'smtp_imap', 'ERROR', 'error@example.com', 'Error'),
                (1, 'resend', 'CONNECTED', 'resend@example.com', 'Resend'),
                (2, 'smtp_imap', 'CONNECTED', 'two@example.com', 'Two');
            """
        )

    monkeypatch.setattr(mailbox_transport, "get_conn", lambda: _connect(db_path))

    assert [
        mailbox["email_address"]
        for mailbox in mailbox_transport.list_connected_imap_mailboxes(organization_id=1)
    ] == ["one@example.com"]
    assert [
        mailbox["email_address"]
        for mailbox in mailbox_transport.list_connected_imap_mailboxes(mailbox_id=4)
    ] == ["two@example.com"]


def test_resolve_mailbox_ignores_global_default_for_tenant_scope(tmp_path, monkeypatch):
    db_path = tmp_path / "mailbox-resolve.sqlite3"
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE mailbox_connections (
                id INTEGER PRIMARY KEY,
                organization_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                email_address TEXT NOT NULL
            );
            INSERT INTO mailbox_connections
                (id, organization_id, provider, status, email_address)
            VALUES
                (1, 1, 'smtp_imap', 'CONNECTED', 'default@example.com'),
                (4, 2, 'smtp_imap', 'CONNECTED', 'tenant@example.com');
            """
        )

    monkeypatch.setattr(mailbox_transport, "get_conn", lambda: _connect(db_path))
    monkeypatch.setattr(mailbox_transport.settings, "default_mailbox_id", 1)

    mailbox = mailbox_transport._resolve_mailbox(organization_id=2)

    assert mailbox["id"] == 4
    assert mailbox["email_address"] == "tenant@example.com"


def test_resolve_mailbox_requires_explicit_selection_when_org_has_multiple_connected_senders(tmp_path, monkeypatch):
    db_path = tmp_path / "mailbox-ambiguous.sqlite3"
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE mailbox_connections (
                id INTEGER PRIMARY KEY,
                organization_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                email_address TEXT NOT NULL
            );
            INSERT INTO mailbox_connections
                (id, organization_id, provider, status, email_address)
            VALUES
                (8, 2, 'smtp_imap', 'CONNECTED', 'first@example.com'),
                (9, 2, 'resend', 'CONNECTED', 'second@example.com');
            """
        )

    monkeypatch.setattr(mailbox_transport, "get_conn", lambda: _connect(db_path))

    with pytest.raises(ValueError, match="Multiple connected sending mailboxes found"):
        mailbox_transport._resolve_mailbox(organization_id=2)

    mailbox = mailbox_transport._resolve_mailbox(mailbox_id=9, organization_id=2)

    assert mailbox["id"] == 9
    assert mailbox["email_address"] == "second@example.com"


def test_latest_unseen_uids_returns_newest_first():
    assert mailbox_transport._latest_unseen_uids([b"601 602 605 610"], 2) == [b"610", b"605"]


def test_unseen_uids_preserves_total_before_limit():
    assert mailbox_transport._unseen_uids([b"601 602 605 610"]) == [b"601", b"602", b"605", b"610"]
    assert mailbox_transport._unseen_uids([]) == []


def test_inbound_message_already_recorded_checks_external_message_id(tmp_path, monkeypatch):
    db_path = tmp_path / "dedupe.sqlite3"
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE email_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                external_message_id TEXT
            );
            INSERT INTO email_messages (organization_id, direction, external_message_id)
            VALUES
                (1, 'inbound', '<seen@example.com>'),
                (1, 'outbound', '<outbound@example.com>'),
                (2, 'inbound', '<other-org@example.com>');
            """
        )

    monkeypatch.setattr(mailbox_transport, "get_conn", lambda: _connect(db_path))

    assert mailbox_transport._inbound_message_already_recorded(
        organization_id=1,
        external_message_id="<seen@example.com>",
    )
    assert not mailbox_transport._inbound_message_already_recorded(
        organization_id=1,
        external_message_id="<outbound@example.com>",
    )
    assert not mailbox_transport._inbound_message_already_recorded(
        organization_id=1,
        external_message_id="<other-org@example.com>",
    )
    assert not mailbox_transport._inbound_message_already_recorded(
        organization_id=1,
        external_message_id=None,
    )
