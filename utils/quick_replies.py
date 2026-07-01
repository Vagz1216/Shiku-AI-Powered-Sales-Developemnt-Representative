"""Quick-reply link generation for outbound emails.

Generates compact mailto: links with embedded intent tokens.
The intent extractor can fast-path detect these keywords before calling the LLM.
"""

import html
import urllib.parse
from typing import Optional

from config import settings
from utils.db_connection import dict_from_row, get_conn

# Legacy keyword markers. Keep detection for old emails already sent.
QUICK_REPLY_KEYWORDS = {
    "INTENT_SCHEDULE_CALL": "meeting_request",
    "INTENT_CONFIRM_MEETING": "meeting_confirmation",
    "INTENT_TELL_ME_MORE": "interest",
    "INTENT_NOT_INTERESTED": "opt_out",
    "INTENT_HAVE_QUESTIONS": "question",
    "INTENT_DIFFERENT_TIME": "meeting_request",
}

_REPLY_BODIES = {
    "schedule_call": "Yes, let's schedule a call.",
    "confirm_meeting": "Yes, that time works for me.",
    "different_time": "That time does not work for me. Can we find another time?",
    "tell_me_more": "Please send me more information.",
    "not_interested": "Thanks, but I am not interested.",
    "have_questions": "I have a few questions.",
}

_REPLY_SUBJECTS = {
    "schedule_call": "Schedule a call",
    "confirm_meeting": "Meeting confirmed",
    "different_time": "Need a different time",
    "tell_me_more": "Tell me more",
    "not_interested": "Not interested",
    "have_questions": "I have questions",
}

QUICK_REPLY_PHRASES = {
    _REPLY_BODIES["schedule_call"].lower(): "meeting_request",
    _REPLY_SUBJECTS["schedule_call"].lower(): "meeting_request",
    _REPLY_BODIES["confirm_meeting"].lower(): "meeting_confirmation",
    _REPLY_SUBJECTS["confirm_meeting"].lower(): "meeting_confirmation",
    _REPLY_BODIES["different_time"].lower(): "meeting_request",
    _REPLY_SUBJECTS["different_time"].lower(): "meeting_request",
    _REPLY_BODIES["tell_me_more"].lower(): "interest",
    _REPLY_SUBJECTS["tell_me_more"].lower(): "interest",
    _REPLY_BODIES["not_interested"].lower(): "opt_out",
    _REPLY_SUBJECTS["not_interested"].lower(): "opt_out",
    _REPLY_BODIES["have_questions"].lower(): "question",
    _REPLY_SUBJECTS["have_questions"].lower(): "question",
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
    """Return a plain-text quick-reply line.

    HTML emails still get clickable mailto buttons. The text part stays human
    readable so drafts do not expose long raw URI strings in the approval UI.
    """
    _ = reply_to, lead_email, campaign_id  # accepted for API compatibility
    body = _REPLY_BODIES.get(action, label)
    return f"  - {label}: {body}"


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


def _agentmail_reply_address() -> str:
    """Derive the legacy reply-to address from the configured AgentMail inbox."""
    inbox = settings.agentmail_inbox_id or ""
    if "@" in inbox:
        return inbox
    return f"{inbox}@agentmail.to" if inbox else "business_dev@agentmail.to"


def _mailbox_reply_address(organization_id: int | None = None, mailbox_id: int | None = None) -> str | None:
    """Return the best connected tenant mailbox address for quick replies."""
    params: list[object] = []
    where = ["status = 'CONNECTED'", "provider IN ('smtp_imap', 'resend', 'gmail', 'microsoft')"]
    if mailbox_id:
        where.append("id = ?")
        params.append(mailbox_id)
    elif organization_id:
        where.append("organization_id = ?")
        params.append(organization_id)
    elif settings.default_mailbox_id:
        where.append("id = ?")
        params.append(settings.default_mailbox_id)
    else:
        return None

    try:
        with get_conn() as conn:
            row = conn.execute(
                f"SELECT email_address, provider, resend_from_email, resend_reply_to "
                f"FROM mailbox_connections WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 1",
                tuple(params),
            ).fetchone()
    except Exception:
        return None

    mailbox = dict_from_row(row)
    if not mailbox:
        return None
    if mailbox.get("provider") == "resend":
        return mailbox.get("resend_reply_to") or mailbox.get("resend_from_email") or mailbox.get("email_address")
    return mailbox.get("email_address")


def _reply_address(organization_id: int | None = None, mailbox_id: int | None = None) -> str:
    """Resolve the visible quick-reply target for the current email provider."""
    if settings.email_provider == "mailbox":
        mailbox_address = _mailbox_reply_address(organization_id=organization_id, mailbox_id=mailbox_id)
        if mailbox_address:
            return mailbox_address
    if settings.email_provider == "resend" and settings.resend_reply_to:
        return settings.resend_reply_to
    if settings.email_provider == "resend" and settings.resend_from_email:
        return settings.resend_from_email
    return _agentmail_reply_address()


# -- Public API ------------------------------------------------------


def quick_replies_for_outreach(
    subject: str,
    lead_email: Optional[str] = None,
    campaign_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    mailbox_id: Optional[int] = None,
) -> str:
    """Quick replies appended to initial outreach / campaign emails."""
    reply_to = _reply_address(organization_id=organization_id, mailbox_id=mailbox_id)
    _ = subject  # kept for API compatibility
    lines = [
        "",
        "Quick reply options:",
        _make_link("Schedule a call", reply_to, "schedule_call", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Tell me more", reply_to, "tell_me_more", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id),
    ]
    return "\n".join(lines)


def quick_replies_html_for_outreach(
    subject: str,
    lead_email: Optional[str] = None,
    campaign_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    mailbox_id: Optional[int] = None,
) -> str:
    """HTML quick replies for initial outreach / campaign emails."""
    reply_to = _reply_address(organization_id=organization_id, mailbox_id=mailbox_id)
    _ = subject  # kept for API compatibility
    return (
        '<div style="margin-top:18px;">'
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827;font-weight:600;'
        'margin-bottom:8px;">Quick Reply</div>'
        f'{_make_html_button("Schedule a call", reply_to, "schedule_call", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Tell me more", reply_to, "tell_me_more", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id)}'
        "</div>"
    )


def quick_replies_for_meeting_proposal(
    subject: str,
    lead_email: Optional[str] = None,
    campaign_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    mailbox_id: Optional[int] = None,
) -> str:
    """Quick replies appended to emails that propose a meeting time."""
    reply_to = _reply_address(organization_id=organization_id, mailbox_id=mailbox_id)
    _ = subject  # kept for API compatibility
    lines = [
        "",
        "Quick reply options:",
        _make_link("Yes, that works for me", reply_to, "confirm_meeting", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Suggest a different time", reply_to, "different_time", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id),
    ]
    return "\n".join(lines)


def quick_replies_html_for_meeting_proposal(
    subject: str,
    lead_email: Optional[str] = None,
    campaign_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    mailbox_id: Optional[int] = None,
) -> str:
    """HTML quick replies for meeting proposal emails."""
    reply_to = _reply_address(organization_id=organization_id, mailbox_id=mailbox_id)
    _ = subject  # kept for API compatibility
    return (
        '<div style="margin-top:18px;">'
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827;font-weight:600;'
        'margin-bottom:8px;">Quick Reply</div>'
        f'{_make_html_button("Yes, that works for me", reply_to, "confirm_meeting", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Suggest a different time", reply_to, "different_time", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id)}'
        "</div>"
    )


def quick_replies_for_followup(
    subject: str,
    lead_email: Optional[str] = None,
    campaign_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    mailbox_id: Optional[int] = None,
) -> str:
    """Quick replies for follow-up / question-answering emails."""
    reply_to = _reply_address(organization_id=organization_id, mailbox_id=mailbox_id)
    _ = subject  # kept for API compatibility
    lines = [
        "",
        "Quick reply options:",
        _make_link("Schedule a call", reply_to, "schedule_call", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("I have questions", reply_to, "have_questions", lead_email=lead_email, campaign_id=campaign_id),
        _make_link("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id),
    ]
    return "\n".join(lines)


def quick_replies_html_for_followup(
    subject: str,
    lead_email: Optional[str] = None,
    campaign_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    mailbox_id: Optional[int] = None,
) -> str:
    """HTML quick replies for follow-up / question-answering emails."""
    reply_to = _reply_address(organization_id=organization_id, mailbox_id=mailbox_id)
    _ = subject  # kept for API compatibility
    return (
        '<div style="margin-top:18px;">'
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827;font-weight:600;'
        'margin-bottom:8px;">Quick Reply</div>'
        f'{_make_html_button("Schedule a call", reply_to, "schedule_call", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("I have questions", reply_to, "have_questions", lead_email=lead_email, campaign_id=campaign_id)}'
        f'{_make_html_button("Not interested", reply_to, "not_interested", lead_email=lead_email, campaign_id=campaign_id)}'
        "</div>"
    )


def plain_text_to_basic_html(text: str) -> str:
    """Convert plain text body to simple escaped HTML."""
    if not text:
        return "<p></p>"
    escaped = html.escape(text)
    return "<div style=\"font-family:Arial,sans-serif;font-size:14px;color:#111827;line-height:1.5;\">" + escaped.replace("\n", "<br>") + "</div>"


def has_quick_reply_block(text: str) -> bool:
    """Return True when the body already includes quick-reply options."""
    normalized = (text or "").lower()
    return "quick reply options:" in normalized or "--- quick reply ---" in normalized


def strip_quick_reply_block(text: str) -> str:
    """Remove the plain-text quick-reply block from a body."""
    if not text or not has_quick_reply_block(text):
        return text

    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        normalized = line.strip().lower()
        if normalized in {"quick reply options:", "--- quick reply ---"}:
            skipping = True
            continue
        if skipping:
            if not normalized or normalized.startswith("-") or normalized.startswith("*"):
                continue
            if line.startswith("  -") or line.startswith("  *"):
                continue
            skipping = False
        kept.append(line)

    return "\n".join(kept).strip()


def clean_quick_reply_text(text: str) -> str:
    """Replace legacy raw mailto quick-reply lines with readable text."""
    if not text or "<mailto:" not in text:
        return text

    cleaned_lines = []
    for line in text.splitlines():
        prefix, marker, suffix = line.partition("<mailto:")
        if not marker or not suffix.rstrip().endswith(">"):
            cleaned_lines.append(line)
            continue

        uri = "mailto:" + suffix.rstrip()[:-1]
        parsed = urllib.parse.urlparse(uri)
        params = urllib.parse.parse_qs(parsed.query)
        body = (params.get("body") or [""])[0].strip()
        cleaned_lines.append(f"{prefix}{body}" if body else line)

    return "\n".join(cleaned_lines)


def detect_quick_reply_keyword(text: str) -> Optional[str]:
    """Fast-path: scan email text for a quick-reply keyword marker."""
    if not text:
        return None
    normalized = " ".join(text.lower().split())
    for phrase, intent in QUICK_REPLY_PHRASES.items():
        if phrase in normalized:
            return intent
    for keyword, intent in QUICK_REPLY_KEYWORDS.items():
        if f"[{keyword}]" in text:
            return intent
    return None
