import asyncio
from types import SimpleNamespace

from outreach import workers
from schema.outreach import OutreachEmailDraft


def test_drafter_prompt_includes_rich_lead_personalization_context(monkeypatch):
    captured = {}

    async def fake_run_agent_with_fallback(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return (
            SimpleNamespace(
                final_output=workers.DraftsResponse(
                    professional_draft=OutreachEmailDraft(subject="A", body="A"),
                    engaging_draft=OutreachEmailDraft(subject="B", body="B"),
                    concise_draft=OutreachEmailDraft(subject="C", body="C"),
                )
            ),
            "fake",
        )

    monkeypatch.setattr(workers, "run_agent_with_fallback", fake_run_agent_with_fallback)

    asyncio.run(
        workers.run_drafter_agent(
            {
                "name": "Ops Leaders",
                "value_proposition": "reduce manual reporting",
                "cta": "Open to a quick chat?",
                "organization_id": 1,
            },
            {
                "name": "Ada",
                "email": "ada@example.com",
                "company": "Acme",
                "industry": "Logistics",
                "pain_points": "manual reporting",
                "job_title": "COO",
                "seniority": "Executive",
                "location": "Nairobi",
                "company_size": "200-500",
                "company_description": "Regional logistics operator",
                "recent_activity": "expanded into Nairobi",
                "icp_score": 87,
                "icp_rationale": "Strong fit due to operational reporting load",
                "touch_count": 0,
                "emails_sent": 0,
                "responded": 0,
            },
        )
    )

    assert "- Job Title: COO" in captured["prompt"]
    assert "- Recent Activity: expanded into Nairobi" in captured["prompt"]
    assert "- ICP Rationale: Strong fit due to operational reporting load" in captured["prompt"]
    assert "Use at least two concrete lead/company-specific facts" in captured["prompt"]
