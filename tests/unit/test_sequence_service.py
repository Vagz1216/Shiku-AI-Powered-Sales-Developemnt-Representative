import sqlite3
import datetime

from services import sequence_service


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE campaigns (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            value_proposition TEXT,
            cta TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            max_emails_per_lead INTEGER NOT NULL DEFAULT 3
        );
        CREATE TABLE leads (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL DEFAULT 1,
            email TEXT NOT NULL,
            name TEXT,
            company TEXT,
            industry TEXT,
            pain_points TEXT,
            status TEXT NOT NULL DEFAULT 'CONTACTED',
            email_opt_out INTEGER NOT NULL DEFAULT 0,
            last_contacted_at TEXT
        );
        CREATE TABLE campaign_leads (
            campaign_id INTEGER NOT NULL,
            lead_id INTEGER NOT NULL,
            emails_sent INTEGER NOT NULL DEFAULT 1,
            responded INTEGER NOT NULL DEFAULT 0,
            meeting_booked INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (campaign_id, lead_id)
        );
        CREATE TABLE campaign_lead_contexts (
            organization_id INTEGER NOT NULL DEFAULT 1,
            campaign_id INTEGER NOT NULL,
            lead_id INTEGER NOT NULL,
            last_outbound_subject TEXT,
            last_outbound_summary TEXT,
            last_inbound_subject TEXT,
            last_inbound_summary TEXT,
            latest_intent TEXT,
            updated_at TEXT,
            PRIMARY KEY (campaign_id, lead_id)
        );
        CREATE TABLE campaign_sequence_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            step_number INTEGER NOT NULL,
            delay_days INTEGER NOT NULL DEFAULT 3,
            subject_template TEXT,
            body_template TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        );
        CREATE TABLE campaign_sequences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            step_number INTEGER NOT NULL,
            channel TEXT NOT NULL DEFAULT 'email',
            delay_days INTEGER NOT NULL DEFAULT 3,
            prompt_context TEXT,
            created_at TEXT
        );
        CREATE TABLE email_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL DEFAULT 1,
            lead_id INTEGER NOT NULL,
            campaign_id INTEGER,
            sequence_step_id INTEGER,
            direction TEXT NOT NULL,
            subject TEXT,
            body TEXT,
            status TEXT,
            processed INTEGER NOT NULL DEFAULT 0,
            approved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            channel TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER,
            type TEXT NOT NULL,
            payload TEXT,
            metadata TEXT
        );
        INSERT INTO campaigns (id, name, value_proposition, cta) VALUES (10, 'Demo', 'better pipeline hygiene', 'Open to a 15-minute call?');
        INSERT INTO leads (id, email, name, company, pain_points, last_contacted_at)
        VALUES (1, 'ada@example.com', 'Ada', 'Example', 'manual prospecting', '2000-01-01T00:00:00Z');
        INSERT INTO campaign_leads (campaign_id, lead_id, emails_sent) VALUES (10, 1, 1);
        INSERT INTO campaign_sequence_steps (
            id, campaign_id, step_number, delay_days, subject_template, body_template, active
        ) VALUES
            (100, 10, 1, 1, 'Initial {campaign_name}', 'Hi {name}, first touch.', 1),
            (101, 10, 2, 1, 'Re: {campaign_name}', 'Hi {name}, checking on {value_proposition}. {cta}', 1);
        INSERT INTO campaign_sequences (campaign_id, step_number, channel, delay_days)
        VALUES (10, 1, 'whatsapp', 1), (10, 2, 'email', 1);
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


def test_generate_due_followup_drafts_creates_one_draft(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(sequence_service, "get_conn", lambda: DummyConn(conn))

    first = sequence_service.generate_due_followup_drafts(campaign_id=10)
    second = sequence_service.generate_due_followup_drafts(campaign_id=10)

    row = conn.execute("SELECT subject, body, sequence_step_id, status, channel FROM email_messages").fetchone()

    assert first["generated"] == 1
    assert second["generated"] == 0
    assert row["subject"] == "Demo"
    assert row["sequence_step_id"] == 101
    assert row["status"] == "DRAFT"
    assert row["channel"] == "email"
    assert "Ada" in row["body"]


def test_generate_due_followup_drafts_records_context(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(sequence_service, "get_conn", lambda: DummyConn(conn))

    result = sequence_service.generate_due_followup_drafts(campaign_id=10)
    context = conn.execute(
        "SELECT last_outbound_subject, last_outbound_summary FROM campaign_lead_contexts "
        "WHERE campaign_id = 10 AND lead_id = 1"
    ).fetchone()

    assert result["generated"] == 1
    assert context["last_outbound_subject"] == "Demo"
    assert "better pipeline hygiene" in context["last_outbound_summary"]


def test_generate_due_followup_drafts_uses_configured_next_channel(monkeypatch):
    conn = _conn()
    conn.execute("UPDATE campaign_leads SET emails_sent = 0 WHERE campaign_id = 10 AND lead_id = 1")
    monkeypatch.setattr(sequence_service, "get_conn", lambda: DummyConn(conn))

    result = sequence_service.generate_due_followup_drafts(campaign_id=10)
    row = conn.execute("SELECT sequence_step_id, channel FROM email_messages").fetchone()

    assert result["generated"] == 1
    assert result["drafts"][0]["step_number"] == 1
    assert result["drafts"][0]["channel"] == "whatsapp"
    assert row["sequence_step_id"] == 100
    assert row["channel"] == "whatsapp"


def test_generate_due_followup_drafts_can_ignore_delay_for_testing(monkeypatch):
    conn = _conn()
    recent = datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conn.execute("UPDATE leads SET last_contacted_at = ? WHERE id = 1", (recent,))
    conn.execute("UPDATE campaign_sequence_steps SET delay_days = 3 WHERE campaign_id = 10 AND step_number = 2")
    monkeypatch.setattr(sequence_service, "get_conn", lambda: DummyConn(conn))

    blocked = sequence_service.generate_due_followup_drafts(campaign_id=10)
    bypassed = sequence_service.generate_due_followup_drafts(campaign_id=10, ignore_delay=True)

    row = conn.execute("SELECT sequence_step_id, status, channel FROM email_messages").fetchone()

    assert blocked["generated"] == 0
    assert blocked["skipped"] == 1
    assert bypassed["generated"] == 1
    assert bypassed["drafts"][0]["delay_ignored"] is True
    assert row["sequence_step_id"] == 101
    assert row["status"] == "DRAFT"
    assert row["channel"] == "email"


def test_replace_sequence_steps_preserves_referenced_step_ids(monkeypatch):
    conn = _conn()
    conn.execute(
        "INSERT INTO email_messages "
        "(organization_id, lead_id, campaign_id, sequence_step_id, direction, subject, body, status, processed, approved, created_at, channel) "
        "VALUES (1, 1, 10, 100, 'outbound', 'Initial Demo', 'Hi Ada', 'SENT', 1, 1, '2000-01-01T00:00:00Z', 'email')"
    )
    monkeypatch.setattr(sequence_service, "get_conn", lambda: DummyConn(conn))

    steps = sequence_service.replace_sequence_steps(
        10,
        [
            {
                "step_number": 1,
                "delay_days": 1,
                "subject_template": "Updated first step",
                "body_template": "Updated body",
                "active": True,
            },
            {
                "step_number": 2,
                "delay_days": 1,
                "subject_template": "Updated second step",
                "body_template": "Second body",
                "active": True,
            },
            {
                "step_number": 3,
                "delay_days": 2,
                "subject_template": "Third step",
                "body_template": "Third body",
                "active": True,
            },
        ],
    )
    message = conn.execute("SELECT sequence_step_id FROM email_messages WHERE subject = 'Initial Demo'").fetchone()
    first_step = conn.execute("SELECT subject_template FROM campaign_sequence_steps WHERE id = 100").fetchone()

    assert message["sequence_step_id"] == 100
    assert first_step["subject_template"] == "Updated first step"
    assert [step["step_number"] for step in steps] == [1, 2, 3]
