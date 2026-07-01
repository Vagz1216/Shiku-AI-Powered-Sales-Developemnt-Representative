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


def test_summarize_text_keeps_complete_context_and_cta():
    body = (
        "Dear Benjamin,I understand that within Legal Technology, managing complex documentation "
        "and ensuring compliance can significantly impact sales velocity and pipeline generation."
        "At Euclid Tech, our AI sales assistant is designed to streamline your sales workflows, "
        "allowing your team to focus on high-value interactions rather than administrative burdens. "
        "This strategic shift has consistently helped companies like Benjamin Legal Tech achieve "
        "substantial pipeline growth and improve sales efficiency. I believe a brief discussion "
        "would highlight how our solution can directly contribute to your revenue objectives. "
        "Would you be open to booking a quick demo to explore this further? Alex Euclid Tech"
    )

    summary = campaign_context_service.summarize_text(body, limit=360)

    assert "Dear Benjamin, I understand" in summary
    assert "Next step: Would you be open to booking a quick demo" in summary
    assert not summary.endswith("...")


def test_build_draft_generation_summary_explains_followup_context():
    summary = campaign_context_service.build_draft_generation_summary(
        source="outreach",
        lead_name="Benjamin",
        campaign_name="Outbound Outreach - Q2",
        emails_sent=1,
        last_outbound_summary="Introduced Euclid Tech's AI sales assistant and asked about a quick demo.",
        last_inbound_summary=None,
        intent=None,
    )

    assert "Generated as follow-up for Benjamin" in summary
    assert "Previous outbound" in summary
    assert "quick demo" in summary


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakePostgresConn:
    def __init__(self, row):
        self.row = row
        self.sql = None
        self.params = None

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = params
        return _FakeCursor(self.row)


def test_table_exists_uses_postgres_catalog(monkeypatch):
    monkeypatch.setattr(campaign_context_service, "using_postgres", lambda: True)
    conn = _FakePostgresConn({"table_name": "campaign_lead_contexts"})

    assert campaign_context_service._table_exists(conn) is True

    assert "to_regclass" in conn.sql
    assert "sqlite_master" not in conn.sql
    assert conn.params == ("public.campaign_lead_contexts",)


def test_table_exists_handles_missing_postgres_table(monkeypatch):
    monkeypatch.setattr(campaign_context_service, "using_postgres", lambda: True)
    conn = _FakePostgresConn({"table_name": None})

    assert campaign_context_service._table_exists(conn) is False
