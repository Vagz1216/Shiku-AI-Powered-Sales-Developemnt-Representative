import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

from outreach import marketing_agent
from schema import SendEmailResult


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

    import utils.db_connection

    monkeypatch.setattr(utils.db_connection, "get_conn", lambda: DummyConn())

    result = asyncio.run(
        marketing_agent.OutreachOrchestrator().execute_campaign(
            campaign_name="Auto Campaign",
            callback=fake_callback,
        )
    )

    assert result["sent"] == 1
    assert send_calls[0]["bypass_human_approval"] is True
    assert any("human draft approval will be skipped" in message for _, message in callback_events)
