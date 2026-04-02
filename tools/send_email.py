"""Send outbound email via AgentMail for use by agents."""

import time
from email.utils import formataddr

from agentmail import AgentMail
from agentmail.core.api_error import ApiError

from config import settings
from agents import function_tool
from schema import SendEmailResult


@function_tool
def send_agent_email(email: str, name: str, subject: str, body: str) -> SendEmailResult:
    """Send plain text email via AgentMail.
    
    Args:
        email: Recipient email address
        name: Recipient name (optional)
        subject: Email subject
        body: Email body text
        
    Returns:
        SendEmailResult with success/failure status and details
    """
    # Validate inputs
    if error := _validate_inputs(email, subject, body):
        return SendEmailResult(ok=False, error=error)
    
    # Validate configuration
    if error := _validate_config():
        return SendEmailResult(ok=False, error=error)
    
    # Send email with retry logic
    return _send_with_retry(email, name, subject, body)


def _validate_inputs(email: str, subject: str, body: str) -> str | None:
    """Validate email inputs. Returns error message or None if valid."""
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
    """Validate required configuration. Returns error message or None if valid."""
    if not settings.agent_mail_api:
        return "AGENTMAIL_API_KEY is not set."
    if not settings.agent_mail_inbox:
        return "AGENTMAIL_INBOX_ID is not set."
    return None


def _send_with_retry(email: str, name: str, subject: str, body: str) -> SendEmailResult:
    """Send email with automatic retry on rate limits."""
    client = AgentMail(api_key=settings.agent_mail_api)
    
    # Format recipient
    name = (name or "").strip()
    to = formataddr((name, email)) if name else email
    
    # Retry up to 5 times for rate limits
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
                thread_id=str(response.thread_id),
            )
        except ApiError as e:
            if e.status_code == 429 and attempt < 4:  # Rate limited, retry
                _sleep_for_rate_limit(attempt, e)
                continue
            return SendEmailResult(
                ok=False, 
                error=f"Send failed: {_get_error_message(e)}"
            )
    
    return SendEmailResult(ok=False, error="Failed after 5 attempts")


def _get_error_message(exc: ApiError) -> str:
    """Extract readable error message from API error."""
    body = exc.body
    
    # Try to get message from dict
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    
    # Try to get message from object attribute
    if hasattr(body, "message") and getattr(body, "message"):
        return str(body.message)
    
    # Fallback to string representation
    return str(exc)


def _sleep_for_rate_limit(attempt: int, exc: ApiError) -> None:
    """Sleep for rate limit with exponential backoff."""
    # Check for Retry-After header
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
    
    # Exponential backoff with max 60 seconds
    wait_time = min(2.0 ** attempt, 60.0)
    time.sleep(wait_time)