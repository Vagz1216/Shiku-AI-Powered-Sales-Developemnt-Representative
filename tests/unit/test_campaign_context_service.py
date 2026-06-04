import sqlite3

from services import campaign_context_service


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE campaign_leads (
            campaign_id INTEGER NOT NULL,
            lead_id INTEGER NOT NULL,
            emails_sent INTEGER NOT NULL DEFAULT 0,
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
        INSERT INTO campaign_leads (campaign_id, lead_id) VALUES (10, 1);
        """
    )
    return conn


def test_record_inbound_sets_response_flags_and_context():
    conn = _conn()

    campaign_context_service.record_inbound(
        conn,
        organization_id=1,
        campaign_id=10,
        lead_id=1,
        subject="Re: Demo",
        body="Yes, this is interesting. Tuesday afternoon could work for a call.",
        intent="meeting_confirmation",
    )

    flags = conn.execute("SELECT responded, meeting_booked FROM campaign_leads").fetchone()
    context = conn.execute(
        "SELECT last_inbound_summary, latest_intent FROM campaign_lead_contexts "
        "WHERE campaign_id = 10 AND lead_id = 1"
    ).fetchone()

    assert flags["responded"] == 1
    assert flags["meeting_booked"] == 1
    assert "Tuesday afternoon" in context["last_inbound_summary"]
    assert context["latest_intent"] == "meeting_confirmation"


def test_record_outbound_keeps_latest_outbound_summary():
    conn = _conn()

    campaign_context_service.record_outbound(
        conn,
        organization_id=1,
        campaign_id=10,
        lead_id=1,
        subject="Hello",
        body="Hi Ada, I wanted to discuss better pipeline hygiene for your sales team.",
    )

    context = campaign_context_service.get_context(conn, 10, 1)

    assert context["last_outbound_subject"] == "Hello"
    assert "pipeline hygiene" in context["last_outbound_summary"]
