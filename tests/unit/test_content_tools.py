import asyncio
from types import SimpleNamespace

from schema.outreach import OutreachEmailDraft
from tools import content_tools


def test_whatsapp_first_step_prompt_does_not_reference_previous_emails(monkeypatch):
    captured = {}

    async def fake_run_agent_with_fallback(**kwargs):
        captured["instructions"] = kwargs["instructions"]
        captured["prompt"] = kwargs["prompt"]
        return SimpleNamespace(final_output=OutreachEmailDraft(subject="", body="Hi Ada, intro?", channel="whatsapp")), "fake"

    monkeypatch.setattr(content_tools, "run_agent_with_fallback", fake_run_agent_with_fallback)

    result = asyncio.run(
        content_tools.create_whatsapp_message(
            campaign_name="Ops Leaders",
            value_proposition="reduce manual reporting",
            lead_info={
                "name": "Ada",
                "company": "Acme",
                "job_title": "COO",
                "industry": "Logistics",
                "pain_points": "manual reporting",
                "recent_activity": "expanded into Nairobi",
            },
            step_number=1,
        )
    )

    assert result.channel == "whatsapp"
    assert "Do not say or imply that you are following up" in captured["prompt"]
    assert "Reference the emails we previously sent" not in captured["prompt"]
    assert "Reference the emails we previously sent" not in captured["instructions"]
    assert "Ada at Acme" in captured["prompt"]
    assert "expanded into Nairobi" in captured["prompt"]


def test_whatsapp_followup_prompt_is_step_aware(monkeypatch):
    captured = {}

    async def fake_run_agent_with_fallback(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return SimpleNamespace(final_output=OutreachEmailDraft(subject="", body="Hi Ada, follow-up?", channel="whatsapp")), "fake"

    monkeypatch.setattr(content_tools, "run_agent_with_fallback", fake_run_agent_with_fallback)

    asyncio.run(
        content_tools.create_whatsapp_message(
            campaign_name="Ops Leaders",
            value_proposition="reduce manual reporting",
            lead_info={"name": "Ada", "company": "Acme"},
            step_number=3,
            context="Follow up after LinkedIn connection.",
        )
    )

    assert "Sequence Stage: follow-up step 3" in captured["prompt"]
    assert "Refer only to the previous campaign touch generally unless the step context names a specific channel" in captured["prompt"]
    assert "Follow up after LinkedIn connection." in captured["prompt"]
