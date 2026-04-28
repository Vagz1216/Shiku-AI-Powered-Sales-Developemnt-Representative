"""Quick-reply link generation for outbound emails.

Generates compact mailto: links with embedded intent tokens.
The intent extractor can fast-path detect these keywords before calling the LLM.
"""

import html
import urllib.parse
from typing import Optional

from config import settings

# Keyword markers embedded in quick-reply pre-filled text.
# Keep these in sync with the fast-path detection in intent_extractor.
QUICK_REPLY_KEYWORDS = {
    "INTENT_SCHEDULE_CALL": "meeting_request",
    "INTENT_CONFIRM_MEETING": "meeting_confirmation",
    "INTENT_TELL_ME_MORE": "interest",
    "INTENT_NOT_INTERESTED": "opt_out",
    "INTENT_HAVE_QUESTIONS": "question",
    "INTENT_DIFFERENT_TIME": "meeting_request",
}

# Compact token bodies keep links short and readable in plain-text clients.
_REPLY_BODIES = {
    "schedule_call": "[INTENT_SCHEDULE_CALL]",
    "confirm_meeting": "[INTENT_CONFIRM_MEETING]",
    "different_time": "[INTENT_DIFFERENT_TIME]",
    "tell_me_more": "[INTENT_TELL_ME_MORE]",
    "not_interested": "[INTENT_NOT_INTERESTED]",
    "have_questions": "[INTENT_HAVE_QUESTIONS]",
}

_REPLY_SUBJECTS = {
    "schedule_call": "Schedule a call [INTENT_SCHEDULE_CALL]",
    "confirm_meeting": "Meeting confirmed [INTENT_CONFIRM_MEETING]",
    "different_time": "Need a different time [INTENT_DIFFERENT_TIME]",
    "tell_me_more": "Tell me more [INTENT_TELL_ME_MORE]",
    "not_interested": "Not interested [INTENT_NOT_INTERESTED]",
    "have_questions": "I have questions [INTENT_HAVE_QUESTIONS]",
}


def _mailto_link(reply_to: str, body: str, subject: str | None = None) -> str:
    """Build an RFC-6068 mailto: URI."""
    payload = {"body": body}
    if subject:
        payload["subject"] = subject
    params = urllib.parse.urlencode(payload, quote_via=urllib.parse.quote)
    return f"mailto:{reply_to}?{params}"


def _mailto_href(reply_to: str, action: str) -> str:
    body = _REPLY_BODIES.get(action, "")
    subject = _REPLY_SUBJECTS.get(action)
    return _mailto_link(reply_to, body, subject=subject)


def _make_link(label: str, reply_to: str, action: str, lead_email: Optional[str] = None, campaign_id: Optional[int] = None) -> str:
    """Return a plain-text quick-reply line with compact URI."""
    _ = lead_email, campaign_id  # accepted for API compatibility
    url = _mailto_href(reply_to, action)
    return f"  - {label}: <{url}>"


def _make_html_button(label: str, reply_to: str, action: str, lead_email: Optional[str] = None, campaign_id: Optional[int] = None) -> str:
    _ = lead_email, campaign_id  # accepted for API compatibility
    href = html.escape(_mailto_href(reply_to, action), quote=True)
    safe_label = html.escape(label)
    return (
        f'<a href="{href}" '
        'style="display:inline-block;padding:8px 12px;margin:6px 8px 0 0;'
        'background:#2563eb;color:#ffffff;text-decoration:none;border-radius:6px;'
        'font-family:Arial,sans-serif;font-size:13px;">'
        f"{safe_label}</a>"
    )


def _reply_address() -> str:
    """Derive the reply-to address from the configured inbox."""
    inbox = settings.agentmail_inbox_id or ""
    if "@" in inbox:
        return inbox
    return f"{inbox}@agentmail.to" if inbox else "business_dev@agentmail.to"


# -- Public API ------------------------------------------------------


def quick_replies_for_outreach(subject: str, lead_email: Optional[str] = None, campaign_id: Optional[int] = None) -> str:
    """Quick replies appended to initial outreach / campaign emails."""
    reply_to = _reply_address()
    _ = subject  # kept for API compatibility
    lines = [
        "",
        "--- Quick Reply ---",
        _make_link("Schedule a call", reply_to, "schedule_call", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Tell me more", reply_to, "tell_me_more", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id),
        "Or reply with one token: [INTENT_SCHEDULE_CALL] | [INTENT_TELL_ME_MORE] | [INTENT_NOT_INTERESTED]",
    ]
    return "\n".join(lines)


def quick_replies_html_for_outreach(subject: str, lead_email: Optional[str] = None, campaign_id: Optional[int] = None) -> str:
    """HTML quick replies for initial outreach / campaign emails."""
    reply_to = _reply_address()
    _ = subject  # kept for API compatibility
    return (
        '<div style="margin-top:18px;">'
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827;font-weight:600;'
        'margin-bottom:8px;">Quick Reply</div>'
        f'{_make_html_button("Schedule a call", reply_to, "schedule_call", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Tell me more", reply_to, "tell_me_more", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id)}'
        '<div style="margin-top:10px;font-family:Arial,sans-serif;font-size:12px;color:#6b7280;">'
        'Fallback: reply with token [INTENT_SCHEDULE_CALL], [INTENT_TELL_ME_MORE], or [INTENT_NOT_INTERESTED].'
        "</div>"
        "</div>"
    )


def quick_replies_for_meeting_proposal(subject: str, lead_email: Optional[str] = None, campaign_id: Optional[int] = None) -> str:
    """Quick replies appended to emails that propose a meeting time."""
    reply_to = _reply_address()
    _ = subject  # kept for API compatibility
    lines = [
        "",
        "--- Quick Reply ---",
        _make_link("Yes, that works for me", reply_to, "confirm_meeting", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Suggest a different time", reply_to, "different_time", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id),
        "Or reply with one token: [INTENT_CONFIRM_MEETING] | [INTENT_DIFFERENT_TIME] | [INTENT_NOT_INTERESTED]",
    ]
    return "\n".join(lines)


def quick_replies_html_for_meeting_proposal(subject: str, lead_email: Optional[str] = None, campaign_id: Optional[int] = None) -> str:
    """HTML quick replies for meeting proposal emails."""
    reply_to = _reply_address()
    _ = subject  # kept for API compatibility
    return (
        '<div style="margin-top:18px;">'
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827;font-weight:600;'
        'margin-bottom:8px;">Quick Reply</div>'
        f'{_make_html_button("Yes, that works for me", reply_to, "confirm_meeting", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Suggest a different time", reply_to, "different_time", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id)}'
        '<div style="margin-top:10px;font-family:Arial,sans-serif;font-size:12px;color:#6b7280;">'
        'Fallback: reply with token [INTENT_CONFIRM_MEETING], [INTENT_DIFFERENT_TIME], or [INTENT_NOT_INTERESTED].'
        "</div>"
        "</div>"
    )


def quick_replies_for_followup(subject: str, lead_email: Optional[str] = None, campaign_id: Optional[int] = None) -> str:
    """Quick replies for follow-up / question-answering emails."""
    reply_to = _reply_address()
    _ = subject  # kept for API compatibility
    lines = [
        "",
        "--- Quick Reply ---",
        _make_link("Schedule a call", reply_to, "schedule_call", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("I have questions", reply_to, "have_questions", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id),
        "Or reply with one token: [INTENT_SCHEDULE_CALL] | [INTENT_HAVE_QUESTIONS] | [INTENT_NOT_INTERESTED]",
    ]
    return "\n".join(lines)


def quick_replies_html_for_followup(subject: str, lead_email: Optional[str] = None, campaign_id: Optional[int] = None) -> str:
    """HTML quick replies for follow-up / question-answering emails."""
    reply_to = _reply_address()
    _ = subject  # kept for API compatibility
    return (
        '<div style="margin-top:18px;">'
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827;font-weight:600;'
        'margin-bottom:8px;">Quick Reply</div>'
        f'{_make_html_button("Schedule a call", reply_to, "schedule_call", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("I have questions", reply_to, "have_questions", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id)}'
        '<div style="margin-top:10px;font-family:Arial,sans-serif;font-size:12px;color:#6b7280;">'
        'Fallback: reply with token [INTENT_SCHEDULE_CALL], [INTENT_HAVE_QUESTIONS], or [INTENT_NOT_INTERESTED].'
        "</div>"
        "</div>"
    )


def plain_text_to_basic_html(text: str) -> str:
    """Convert plain text body to simple escaped HTML."""
    if not text:
        return "<p></p>"
    escaped = html.escape(text)
    return "<div style=\"font-family:Arial,sans-serif;font-size:14px;color:#111827;line-height:1.5;\">" + escaped.replace("\n", "<br>") + "</div>"


def detect_quick_reply_keyword(text: str) -> Optional[str]:
    """Fast-path: scan email text for a quick-reply keyword marker."""
    if not text:
        return None
    for keyword, intent in QUICK_REPLY_KEYWORDS.items():
        if f"[{keyword}]" in text:
            return intent
    return None
