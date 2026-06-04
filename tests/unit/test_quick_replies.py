from utils.quick_replies import (
    clean_quick_reply_text,
    detect_quick_reply_keyword,
    quick_replies_for_followup,
    quick_replies_for_meeting_proposal,
    quick_replies_for_outreach,
    quick_replies_html_for_followup,
    quick_replies_html_for_meeting_proposal,
    quick_replies_html_for_outreach,
    strip_quick_reply_block,
)


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _sql, _params=()):
        return self

    def fetchone(self):
        return {
            "email_address": "info@markethacks.co.ke",
            "provider": "smtp_imap",
            "resend_from_email": None,
            "resend_reply_to": None,
        }


def test_quick_reply_output_does_not_expose_internal_tokens():
    outputs = [
        quick_replies_for_outreach("Hello"),
        quick_replies_html_for_outreach("Hello"),
        quick_replies_for_meeting_proposal("Hello"),
        quick_replies_html_for_meeting_proposal("Hello"),
        quick_replies_for_followup("Hello"),
        quick_replies_html_for_followup("Hello"),
    ]

    for output in outputs:
        assert "Fallback:" not in output
        assert "[INTENT_" not in output
        assert "reply with one token" not in output


def test_plain_text_quick_replies_do_not_expose_mailto_uris():
    outputs = [
        quick_replies_for_outreach("Hello"),
        quick_replies_for_meeting_proposal("Hello"),
        quick_replies_for_followup("Hello"),
    ]

    for output in outputs:
        assert "mailto:" not in output
        assert "<" not in output
        assert "Quick reply options:" in output


def test_html_quick_replies_target_tenant_mailbox(monkeypatch):
    import utils.quick_replies as quick_replies

    monkeypatch.setattr(quick_replies.settings, "email_provider", "mailbox")
    monkeypatch.setattr(quick_replies.settings, "default_mailbox_id", None)
    monkeypatch.setattr(quick_replies, "get_conn", lambda: _FakeConn())

    output = quick_replies_html_for_outreach("Hello", organization_id=2)

    assert "mailto:info@markethacks.co.ke" in output
    assert "agentmail.to" not in output


def test_legacy_mailto_quick_replies_are_cleaned_for_draft_display():
    text = (
        "Thanks.\n\n"
        "--- Quick Reply ---\n"
        "  - Schedule a call: <mailto:business_dev@agentmail.to?"
        "body=Yes%2C%20let%27s%20schedule%20a%20call.&subject=Schedule%20a%20call>"
    )

    cleaned = clean_quick_reply_text(text)

    assert "mailto:" not in cleaned
    assert "<" not in cleaned
    assert "  - Schedule a call: Yes, let's schedule a call." in cleaned


def test_quick_reply_detector_accepts_natural_button_replies():
    assert detect_quick_reply_keyword("Yes, let's schedule a call.") == "meeting_request"
    assert detect_quick_reply_keyword("Please send me more information.") == "interest"
    assert detect_quick_reply_keyword("Thanks, but I am not interested.") == "opt_out"
    assert detect_quick_reply_keyword("Yes, that time works for me.") == "meeting_confirmation"
    assert detect_quick_reply_keyword("I have a few questions.") == "question"


def test_quick_reply_detector_keeps_legacy_token_support():
    assert detect_quick_reply_keyword("[INTENT_SCHEDULE_CALL]") == "meeting_request"


def test_strip_quick_reply_block_removes_plain_text_options():
    body = (
        "Thanks for your interest.\n\n"
        "Quick reply options:\n"
        "  - Schedule a call: Yes, let's schedule a call.\n"
        "  - Tell me more: Please send me more information.\n\n"
        "Best regards,\nTeam"
    )

    stripped = strip_quick_reply_block(body)

    assert "Quick reply options" not in stripped
    assert "Schedule a call" not in stripped
    assert "Thanks for your interest." in stripped
    assert "Best regards" in stripped
