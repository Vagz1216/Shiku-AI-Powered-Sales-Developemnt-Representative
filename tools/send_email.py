"""Send outbound email via AgentMail for agent tools and the outreach pipeline."""

import time
from email.utils import formataddr

from agentmail import AgentMail
from agentmail.core.api_error import ApiError
from agents import function_tool

from config import settings
from schema import SendEmailResult
import asyncio
from utils.llama_guard import check_email_safety


async def send_plain_email(email: str, name: str, subject: str, body: str) -> SendEmailResult:
    """Send a plain-text email via AgentMail (no agent wrapper).

    Use this from the outreach pipeline.     The monitoring stack wraps the same logic as send_agent_email for OpenAI Agents.
    """
    if error := _validate_inputs(email, subject, body):
        return SendEmailResult(ok=False, error=error)
        
    # AI-based Validation Guardrail (Llama Guard logic)
    safety_check = await check_email_safety(body, subject)
    if not safety_check.is_safe:
        return SendEmailResult(ok=False, error=f"Safety check failed: {safety_check.violation_reason}")
        
    if error := _validate_config():
        return SendEmailResult(ok=False, error=error)
    return _send_with_retry(email, name, subject, body)


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


def _send_with_retry(email: str, name: str, subject: str, body: str) -> SendEmailResult:
    client = AgentMail(api_key=settings.agent_mail_api)
    name = (name or "").strip()
    to = formataddr((name, email)) if name else email
    for attempt in range(5):
        try:
            response = client.inboxes.messages.send(
                settings.agent_mail_inbox,
                to=to,
                subject=subject.strip(),
                text=body.strip(),
            )
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
