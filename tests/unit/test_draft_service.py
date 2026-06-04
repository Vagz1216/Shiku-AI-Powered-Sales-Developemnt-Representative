import asyncio
import sqlite3

import pytest

from services import draft_service
from schema import SendEmailResult


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL DEFAULT 1,
            name TEXT,
            email TEXT NOT NULL
        );
        CREATE TABLE email_messages (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL DEFAULT 1,
            lead_id INTEGER NOT NULL,
            campaign_id INTEGER,
            sequence_step_id INTEGER,
            direction TEXT NOT NULL,
            subject TEXT,
            body TEXT,
            status TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            approved_by TEXT,
            approved_at TEXT,
            scheduled_send_at TEXT,
            sent_at TEXT,
            send_attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            external_message_id TEXT,
            external_thread_id TEXT
        );
        CREATE TABLE email_attachments (
            id INTEGER PRIMARY KEY,
            email_message_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            content_type TEXT,
            content_base64 TEXT,
            extracted_text TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'user_upload',
            created_at TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER,
            type TEXT NOT NULL,
            payload TEXT,
            metadata TEXT
        );
        INSERT INTO leads (id, name, email) VALUES (1, 'Ada', 'ada@example.com');
        INSERT INTO email_messages (
            id, lead_id, campaign_id, direction, subject, body, status, approved
        ) VALUES (
            10, 1, 20, 'outbound', 'Hello', 'Body', 'DRAFT', 0
        );
        """
    )
    return conn


@pytest.fixture(autouse=True)
def _no_outbound_events(monkeypatch):
    async def noop_emit(*args, **kwargs):
        return None

    monkeypatch.setattr(draft_service.outbound_event_service, "emit_event", noop_emit)


def test_reject_draft_records_approval_event():
    conn = _conn()

    result = asyncio.run(
        draft_service.process_single_draft_approval(
            conn,
            draft_id=10,
            approved=False,
            actor_id="user_123",
        )
    )

    row = conn.execute("SELECT approved, status FROM email_messages WHERE id = 10").fetchone()
    event = conn.execute("SELECT type, payload FROM events").fetchone()

    assert result["status"] == "rejected"
    assert result["approval_id"].startswith("approval:10:user_123")
    assert row["approved"] == -1
    assert row["status"] == "REJECTED"
    assert event["type"] == "draft_rejected"
    assert "user_123" in event["payload"]


def test_approve_draft_bypasses_draft_only_mode(monkeypatch):
    conn = _conn()
    calls = []

    async def fake_send_plain_email(**kwargs):
        calls.append(kwargs)
        return SendEmailResult(ok=True, message_id="msg_123", thread_id="thread_123")

    monkeypatch.setattr(draft_service, "send_plain_email", fake_send_plain_email)

    result = asyncio.run(
        draft_service.process_single_draft_approval(
            conn,
            draft_id=10,
            approved=True,
            actor_id="user_123",
        )
    )

    row = conn.execute("SELECT approved, status FROM email_messages WHERE id = 10").fetchone()
    event = conn.execute("SELECT type, payload FROM events").fetchone()
    message_count = conn.execute("SELECT COUNT(*) AS count FROM email_messages").fetchone()["count"]

    assert result["status"] == "approved_sent"
    assert result["message_id"] == "msg_123"
    assert calls[0]["bypass_human_approval"] is True
    assert row["approved"] == 1
    assert row["status"] == "SENT"
    assert event["type"] == "draft_approved_sent"
    assert "msg_123" in event["payload"]
    assert message_count == 1


def test_update_draft_content_records_event(monkeypatch):
    conn = _conn()

    class DummyConn:
        def __enter__(self):
            return conn

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(draft_service, "get_conn", lambda: DummyConn())

    result = draft_service.update_draft_content(
        draft_id=10,
        subject="Updated subject",
        body="Updated body",
        actor_id="user_123",
    )

    row = conn.execute("SELECT subject, body FROM email_messages WHERE id = 10").fetchone()
    event = conn.execute("SELECT type, payload FROM events").fetchone()

    assert result["status"] == "updated"
    assert row["subject"] == "Updated subject"
    assert row["body"] == "Updated body"
    assert event["type"] == "draft_updated"


def test_approve_draft_sends_added_attachments(monkeypatch):
    conn = _conn()
    conn.execute(
        "INSERT INTO email_attachments "
        "(id, email_message_id, filename, content_type, content_base64, size_bytes, source) "
        "VALUES (1, 10, 'one-pager.pdf', 'application/pdf', 'SGVsbG8=', 5, 'user_upload')"
    )
    calls = []

    async def fake_send_plain_email(**kwargs):
        calls.append(kwargs)
        return SendEmailResult(ok=True, message_id="msg_123", thread_id="thread_123")

    monkeypatch.setattr(draft_service, "send_plain_email", fake_send_plain_email)

    result = asyncio.run(
        draft_service.process_single_draft_approval(
            conn,
            draft_id=10,
            approved=True,
            actor_id="user_123",
        )
    )

    assert result["status"] == "approved_sent"
    assert calls[0]["attachments"] == [
        {
            "filename": "one-pager.pdf",
            "content_type": "application/pdf",
            "content_base64": "SGVsbG8=",
        }
    ]


def test_approve_draft_can_schedule_without_sending(monkeypatch):
    conn = _conn()
    calls = []

    async def fake_send_plain_email(**kwargs):
        calls.append(kwargs)
        return SendEmailResult(ok=True, message_id="msg_123", thread_id="thread_123")

    monkeypatch.setattr(draft_service, "send_plain_email", fake_send_plain_email)

    result = asyncio.run(
        draft_service.process_single_draft_approval(
            conn,
            draft_id=10,
            approved=True,
            actor_id="user_123",
            scheduled_send_at="2999-01-01T10:00:00Z",
        )
    )

    row = conn.execute("SELECT approved, status, scheduled_send_at FROM email_messages WHERE id = 10").fetchone()

    assert result["status"] == "approved_scheduled"
    assert calls == []
    assert row["approved"] == 1
    assert row["status"] == "SCHEDULED"
    assert row["scheduled_send_at"] == "2999-01-01T10:00:00Z"


def test_send_due_scheduled_drafts_sends_due_email(monkeypatch):
    conn = _conn()
    conn.execute(
        "UPDATE email_messages SET approved = 1, status = 'SCHEDULED', scheduled_send_at = '2000-01-01T00:00:00Z' WHERE id = 10"
    )
    calls = []

    class DummyConn:
        def __enter__(self):
            return conn

        def __exit__(self, *args):
            return False

    async def fake_send_plain_email(**kwargs):
        calls.append(kwargs)
        return SendEmailResult(ok=True, message_id="msg_123", thread_id="thread_123")

    monkeypatch.setattr(draft_service, "get_conn", lambda: DummyConn())
    monkeypatch.setattr(draft_service, "send_plain_email", fake_send_plain_email)

    result = asyncio.run(draft_service.send_due_scheduled_drafts())
    row = conn.execute("SELECT status, sent_at, external_message_id FROM email_messages WHERE id = 10").fetchone()

    assert result["sent"] == 1
    assert len(calls) == 1
    assert row["status"] == "SENT"
    assert row["sent_at"]
    assert row["external_message_id"] == "msg_123"


def test_scheduled_safety_outage_returns_to_review_after_retry_cap(monkeypatch):
    conn = _conn()
    conn.execute(
        "UPDATE email_messages SET approved = 1, status = 'SCHEDULED', "
        "scheduled_send_at = '2000-01-01T00:00:00Z', send_attempts = 2 WHERE id = 10"
    )

    class DummyConn:
        def __enter__(self):
            return conn

        def __exit__(self, *args):
            return False

    async def fake_send_plain_email(**kwargs):
        return SendEmailResult(ok=False, error="Safety check failed: Safety check system unavailable.")

    monkeypatch.setattr(draft_service.settings, "scheduled_sender_max_attempts", 3)
    monkeypatch.setattr(draft_service, "get_conn", lambda: DummyConn())
    monkeypatch.setattr(draft_service, "send_plain_email", fake_send_plain_email)

    result = asyncio.run(draft_service.send_due_scheduled_drafts())
    row = conn.execute(
        "SELECT status, approved, scheduled_send_at, send_attempts, last_error FROM email_messages WHERE id = 10"
    ).fetchone()

    assert result["failed"] == 1
    assert row["status"] == "DRAFT"
    assert row["approved"] == 0
    assert row["scheduled_send_at"] is None
    assert row["send_attempts"] == 3
    assert "Review provider configuration" in row["last_error"]


def test_scheduled_unsafe_content_marks_failed(monkeypatch):
    conn = _conn()
    conn.execute(
        "UPDATE email_messages SET approved = 1, status = 'SCHEDULED', "
        "scheduled_send_at = '2000-01-01T00:00:00Z' WHERE id = 10"
    )

    class DummyConn:
        def __enter__(self):
            return conn

        def __exit__(self, *args):
            return False

    async def fake_send_plain_email(**kwargs):
        return SendEmailResult(ok=False, error="Safety check failed: Prompt injection detected.")

    monkeypatch.setattr(draft_service, "get_conn", lambda: DummyConn())
    monkeypatch.setattr(draft_service, "send_plain_email", fake_send_plain_email)

    result = asyncio.run(draft_service.send_due_scheduled_drafts())
    row = conn.execute(
        "SELECT status, approved, scheduled_send_at, send_attempts, last_error FROM email_messages WHERE id = 10"
    ).fetchone()

    assert result["failed"] == 1
    assert row["status"] == "FAILED"
    assert row["approved"] == 1
    assert row["scheduled_send_at"] == "2000-01-01T00:00:00Z"
    assert row["send_attempts"] == 1
    assert row["last_error"] == "Safety check failed: Prompt injection detected."
