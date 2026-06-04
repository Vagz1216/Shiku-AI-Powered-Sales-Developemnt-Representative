import pytest
from pydantic import ValidationError

from schema.email import EmailIntent, WebhookEvent
from schema.outreach import CampaignCreate, OutreachEmailDraft


def test_email_intent_rejects_extra_fields():
    with pytest.raises(ValidationError):
        EmailIntent(
            rationale="The sender asked to meet.",
            intent="meeting_request",
            confidence=0.9,
            send_calendar_invite=True,
        )


def test_campaign_create_rejects_unknown_admin_override():
    with pytest.raises(ValidationError):
        CampaignCreate(
            name="Test",
            value_proposition="Value",
            cta="Book time",
            admin_override=True,
        )


def test_outreach_email_draft_accepts_expected_shape():
    draft = OutreachEmailDraft(subject="Quick question", body="Open to a short call?")

    assert draft.subject == "Quick question"


def test_webhook_event_accepts_agentmail_envelope_metadata():
    event = WebhookEvent(
        event_type="message.received",
        event_id="evt_123",
        message={"from": "Ada <ada@example.com>", "subject": "Hello", "text": "Interested"},
        type="event",
        thread={"created_at": "2026-05-30T14:51:09.510Z"},
    )

    assert event.event_type == "message.received"
    assert event.event_id == "evt_123"
    assert event.message["subject"] == "Hello"
