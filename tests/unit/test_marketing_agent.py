import asyncio
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace

from outreach import marketing_agent
from schema import SendEmailResult


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_auto_approved_campaign_bypasses_global_human_approval(monkeypatch):
    campaign = SimpleNamespace(
        id=42,
        name="Auto Campaign",
        value_proposition="Value",
        cta="Book a call",
        max_leads_per_campaign=1,
        lead_selection_order="newest_first",
        auto_approve_drafts=True,
    )
    lead = {
        "id": 7,
        "name": "Gabrielle",
        "email": "gabrielle@example.com",
        "company": "Acme",
        "industry": "Software",
        "pain_points": "Manual work",
        "touch_count": 0,
        "emails_sent": 0,
        "responded": 0,
        "status": "NEW",
    }
    send_calls = []
    callback_events = []

    async def fake_drafter(camp_info, lead_info):
        return SimpleNamespace()

    async def fake_reviewer(camp_info, lead_info, drafts):
        return SimpleNamespace(
            subject="Hello",
            body="Draft body",
            selected_draft_type="professional",
        )

    async def fake_send_plain_email(**kwargs):
        send_calls.append(kwargs)
        return SendEmailResult(ok=True, message_id="msg_1", thread_id="thread_1")

    async def fake_callback(status, message):
        callback_events.append((status, message))

    class DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            return None

    monkeypatch.setattr(marketing_agent, "trace", lambda **kwargs: nullcontext())
    monkeypatch.setattr(marketing_agent, "gen_trace_id", lambda: "trace_1")
    monkeypatch.setattr(marketing_agent, "fetch_campaign_info", lambda campaign_name=None, organization_id=None: campaign)
    monkeypatch.setattr(marketing_agent.lead_service, "get_leads", lambda **kwargs: {"success": True, "data": [lead]})
    monkeypatch.setattr(marketing_agent.lead_service, "update_lead_touch", lambda *args, **kwargs: None)
    monkeypatch.setattr(marketing_agent.lead_service, "update_lead_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(marketing_agent, "run_drafter_agent", fake_drafter)
    monkeypatch.setattr(marketing_agent, "run_reviewer_agent", fake_reviewer)
    monkeypatch.setattr(marketing_agent, "send_plain_email", fake_send_plain_email)
    monkeypatch.setattr(
        marketing_agent,
        "_claim_next_outreach_touch",
        lambda **kwargs: {"claimed": True, "message_id": 99, "step": {"step_number": 1, "channel": "email"}},
    )
    monkeypatch.setattr(marketing_agent, "_complete_initial_outreach_touch", lambda *args, **kwargs: None)
    monkeypatch.setattr(marketing_agent, "_fail_initial_outreach_touch", lambda *args, **kwargs: None)

    import utils.db_connection

    monkeypatch.setattr(utils.db_connection, "get_conn", lambda: DummyConn())
    monkeypatch.setattr(marketing_agent, "get_conn", lambda: DummyConn())

    result = asyncio.run(
        marketing_agent.OutreachOrchestrator().execute_campaign(
            campaign_name="Auto Campaign",
            callback=fake_callback,
        )
    )

    assert result["sent"] == 1
    assert send_calls[0]["bypass_human_approval"] is True
    assert any("human draft approval will be skipped" in message for _, message in callback_events)


def test_campaign_skips_lead_when_first_touch_already_exists(monkeypatch):
    campaign = SimpleNamespace(
        id=42,
        name="Duplicate Safe Campaign",
        value_proposition="Value",
        cta="Book a call",
        max_leads_per_campaign=1,
        lead_selection_order="newest_first",
        auto_approve_drafts=False,
    )
    lead = {
        "id": 7,
        "name": "Gabrielle",
        "email": "gabrielle@example.com",
        "company": "Acme",
        "industry": "Software",
        "pain_points": "Manual work",
        "touch_count": 0,
        "emails_sent": 0,
        "responded": 0,
        "status": "NEW",
    }
    drafter_called = False
    callback_events = []

    async def fake_drafter(camp_info, lead_info):
        nonlocal drafter_called
        drafter_called = True
        return SimpleNamespace()

    async def fake_callback(status, message):
        callback_events.append((status, message))

    monkeypatch.setattr(marketing_agent, "trace", lambda **kwargs: nullcontext())
    monkeypatch.setattr(marketing_agent, "gen_trace_id", lambda: "trace_1")
    monkeypatch.setattr(marketing_agent, "fetch_campaign_info", lambda campaign_name=None, organization_id=None: campaign)
    monkeypatch.setattr(marketing_agent.lead_service, "get_leads", lambda **kwargs: {"success": True, "data": [lead]})
    monkeypatch.setattr(marketing_agent, "run_drafter_agent", fake_drafter)
    monkeypatch.setattr(
        marketing_agent,
        "_claim_next_outreach_touch",
        lambda **kwargs: {"claimed": False, "error": "No eligible sequence step found (waiting, exhausted, or halted)."},
    )

    result = asyncio.run(
        marketing_agent.OutreachOrchestrator().execute_campaign(
            campaign_name="Duplicate Safe Campaign",
            callback=fake_callback,
        )
    )

    assert result["processed"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert drafter_called is False
    assert result["run_records"][0]["status"] == "skipped"
    assert any("No eligible sequence step found" in message for _, message in callback_events)


def test_claim_next_outreach_touch_is_campaign_lead_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "outreach-claim.sqlite3"
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE leads (id INTEGER, status TEXT, touch_count INTEGER);
            INSERT INTO leads VALUES (7, 'NEW', 0);
            
            CREATE TABLE email_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                lead_id INTEGER NOT NULL,
                campaign_id INTEGER,
                sequence_step_id INTEGER,
                direction TEXT NOT NULL,
                subject TEXT,
                body TEXT,
                status TEXT,
                processed INTEGER NOT NULL DEFAULT 0,
                approved INTEGER NOT NULL DEFAULT 0,
                channel TEXT,
                created_at TEXT,
                sent_at TEXT
            );
            
            CREATE TABLE campaign_sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER,
                step_number INTEGER,
                channel TEXT,
                delay_days INTEGER,
                prompt_context TEXT
            );

            CREATE TABLE campaign_sequence_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER,
                step_number INTEGER,
                delay_days INTEGER,
                subject_template TEXT,
                body_template TEXT,
                active INTEGER,
                created_at TEXT
            );
            """
        )

    monkeypatch.setattr(marketing_agent, "get_conn", lambda: _connect(db_path))

    first = marketing_agent._claim_next_outreach_touch(
        organization_id=1,
        campaign_id=42,
        lead_id=7,
        lead_email="gabrielle@example.com",
    )
    second = marketing_agent._claim_next_outreach_touch(
        organization_id=1,
        campaign_id=42,
        lead_id=7,
        lead_email="gabrielle@example.com",
    )

    assert first["claimed"] is True
    assert second["claimed"] is False
    assert "No eligible sequence step found" in second["error"]
