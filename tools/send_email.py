"""Send outbound email via AgentMail for agent tools and the outreach pipeline."""

import logging
import time
from datetime import date
from email.utils import formataddr

from agentmail import AgentMail
from agentmail.core.api_error import ApiError
from agents import function_tool

from config import settings
from schema import SendEmailResult
import asyncio
from utils.llama_guard import check_email_safety

logger = logging.getLogger(__name__)

_daily_send_counts: dict[str, int] = {}


def _check_daily_limit() -> str | None:
    """Return an error string if the daily email limit has been reached."""
    today = date.today().isoformat()
    if today not in _daily_send_counts:
        _daily_send_counts.clear()
        _daily_send_counts[today] = 0
    if _daily_send_counts[today] >= settings.daily_email_limit:
        return f"Daily email limit reached ({settings.daily_email_limit}). Try again tomorrow."
    return None


def _increment_daily_count():
    today = date.today().isoformat()
    _daily_send_counts[today] = _daily_send_counts.get(today, 0) + 1


def _check_forbidden_phrases(body: str) -> str | None:
    """Return an error if the body contains any forbidden phrases."""
    if not settings.forbidden_phrases:
        return None
    phrases = [p.strip().lower() for p in settings.forbidden_phrases.split(",") if p.strip()]
    body_lower = body.lower()
    for phrase in phrases:
        if phrase in body_lower:
            return f"Email body contains forbidden phrase: '{phrase}'"
    return None


def _enforce_max_words(body: str) -> str:
    """Truncate body to max_words_per_email if exceeded."""
    words = body.split()
    if len(words) > settings.max_words_per_email:
        logger.warning(f"Email body truncated from {len(words)} to {settings.max_words_per_email} words")
        return " ".join(words[: settings.max_words_per_email])
    return body


def _ensure_opt_out_footer(body: str) -> str:
    """Append opt-out footer if no opt-out wording is present."""
    opt_out_keywords = ["stop", "unsubscribe", "opt out", "opt-out", "remove me"]
    if any(kw in body.lower() for kw in opt_out_keywords):
        return body
    return body + settings.opt_out_footer


async def send_plain_email(
    email: str, name: str, subject: str, body: str,
    skip_safety_check: bool = False,
    internal: bool = False,
    html_body: str | None = None,
) -> SendEmailResult:
    """Send a plain-text email via AgentMail (no agent wrapper).

    Args:
        internal: If True, skip safety check AND opt-out footer (for staff notifications).
        skip_safety_check: Legacy flag, same effect as internal for safety check only.
    """
    if error := _validate_inputs(email, subject, body):
        return SendEmailResult(ok=False, error=error)

    if error := _check_daily_limit():
        return SendEmailResult(ok=False, error=error)

    if not internal:
        if error := _check_forbidden_phrases(body):
            return SendEmailResult(ok=False, error=error)

    body = _enforce_max_words(body)
    if not internal:
        body = _ensure_opt_out_footer(body)

    if not (skip_safety_check or internal):
        safety_check = await check_email_safety(body, subject)
        if not safety_check.is_safe:
            return SendEmailResult(ok=False, error=f"Safety check failed: {safety_check.violation_reason}")
        
    if settings.require_human_approval:
        from utils.db_connection import get_conn
        import datetime
        conn = get_conn()
        try:
            with conn:
                # Find lead_id
                cur = conn.execute("SELECT id FROM leads WHERE email = ?", (email,))
                row = cur.fetchone()
                lead_id = row['id'] if row else None
                
                # Save as draft
                now_iso = datetime.datetime.utcnow().isoformat() + 'Z'
                conn.execute(
                    "INSERT INTO email_messages (lead_id, direction, subject, body, status, processed, created_at) VALUES (?, 'outbound', ?, ?, 'draft', 1, ?)",
                    (lead_id, subject, body, now_iso)
                )
            return SendEmailResult(ok=True, message_id="draft", thread_id="draft")
        except Exception as e:
            return SendEmailResult(ok=False, error=f"Failed to save draft: {e}")

    if error := _validate_config():
        return SendEmailResult(ok=False, error=error)
    result = _send_with_retry(email, name, subject, body, html_body=html_body)
    if result.ok:
        _increment_daily_count()
    return result


@function_tool
async def send_agent_email(email: str, name: str, subject: str, body: str) -> SendEmailResult:
    """Send plain text email via AgentMail (agent-callable tool)."""
    return await send_plain_email(email, name, subject, body)


def _validate_inputs(email: str, subject: str, body: str) -> str | None:
    email = email.strip()
    subject = subject.strip()
    body = body.strip()
    if not email or "@" not in email:
        return "Valid recipient email is required."
    if not subject:
        return "Subject is required."
    if not body:
        return "Body is required."
        
    return None


def _validate_config() -> str | None:
    if not settings.agent_mail_api:
        return "AGENTMAIL_API_KEY is not set."
    if not settings.agent_mail_inbox:
        return "AGENTMAIL_INBOX_ID is not set."
    return None


def _send_with_retry(email: str, name: str, subject: str, body: str, html_body: str | None = None) -> SendEmailResult:
    client = AgentMail(api_key=settings.agent_mail_api)
    name = (name or "").strip()
    to = formataddr((name, email)) if name else email
    for attempt in range(5):
        try:
            payload = {
                "to": to,
                "subject": subject.strip(),
                "text": body.strip(),
            }
            if html_body:
                payload["html"] = html_body.strip()

            try:
                response = client.inboxes.messages.send(settings.agent_mail_inbox, **payload)
            except TypeError as sdk_error:
                if "html" in payload:
                    logger.warning(f"AgentMail SDK rejected html payload, retrying text-only: {sdk_error}")
                    payload.pop("html", None)
                    response = client.inboxes.messages.send(settings.agent_mail_inbox, **payload)
                else:
                    raise
            return SendEmailResult(
                ok=True,
                message_id=str(response.message_id),
                thread_id=str(response.thread_id) if response.thread_id is not None else None,
            )
        except ApiError as e:
            if e.status_code == 429 and attempt < 4:
                _sleep_for_rate_limit(attempt, e)
                continue
            return SendEmailResult(ok=False, error=f"Send failed: {_get_error_message(e)}")
    return SendEmailResult(ok=False, error="Failed after 5 attempts")


def _get_error_message(exc: ApiError) -> str:
    body = exc.body
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    if hasattr(body, "message") and getattr(body, "message"):
        return str(body.message)
    return str(exc)


def _sleep_for_rate_limit(attempt: int, exc: ApiError) -> None:
    if exc.headers:
        retry_after = exc.headers.get("retry-after") or exc.headers.get("Retry-After")
        if retry_after:
            try:
                wait_time = float(retry_after)
                if wait_time > 0:
                    time.sleep(wait_time)
                    return
            except (TypeError, ValueError):
                pass
    time.sleep(min(2.0**attempt, 60.0))
