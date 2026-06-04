"""Resend email transport helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from email.utils import formataddr
from typing import Any

import httpx

from config import settings
from schema import SendEmailResult

logger = logging.getLogger(__name__)

RESEND_API_BASE = "https://api.resend.com"
WEBHOOK_TOLERANCE_SECONDS = 5 * 60


def validate_resend_config(api_key: str | None = None, from_email: str | None = None) -> str | None:
    """Return an error string if required Resend send config is missing."""
    if not (api_key or settings.resend_api_key):
        return "RESEND_API_KEY is not set."
    if not (from_email or settings.resend_from_email):
        return "RESEND_FROM_EMAIL is not set."
    return None


def send_resend_email(
    email: str,
    name: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
    api_key: str | None = None,
    from_email: str | None = None,
    reply_to: str | None = None,
) -> SendEmailResult:
    """Send an email through Resend's HTTP API."""
    resolved_api_key = api_key or settings.resend_api_key
    resolved_from_email = from_email or settings.resend_from_email
    resolved_reply_to = reply_to if reply_to is not None else settings.resend_reply_to
    if error := validate_resend_config(resolved_api_key, resolved_from_email):
        return SendEmailResult(ok=False, error=error)

    recipient = formataddr((name.strip(), email)) if name and name.strip() else email
    payload: dict[str, Any] = {
        "from": resolved_from_email,
        "to": [recipient],
        "subject": subject.strip(),
        "text": body.strip(),
    }
    if html_body:
        payload["html"] = html_body.strip()
    if resolved_reply_to:
        payload["reply_to"] = resolved_reply_to
    if headers:
        payload["headers"] = {k: v for k, v in headers.items() if v}
    if attachments:
        mapped_attachments = _map_attachments(attachments)
        if mapped_attachments:
            payload["attachments"] = mapped_attachments

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{RESEND_API_BASE}/emails",
                headers={
                    "Authorization": f"Bearer {resolved_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code >= 400:
            logger.warning("Resend send failed: %s %s", response.status_code, response.text)
            return SendEmailResult(ok=False, error=f"Resend send failed: {_resend_error(response)}")
        data = response.json()
        message_id = data.get("id") or (data.get("data") or {}).get("id")
        return SendEmailResult(ok=True, message_id=str(message_id) if message_id else None)
    except Exception as exc:
        logger.error("Resend send failed: %s", exc)
        return SendEmailResult(ok=False, error=f"Resend send failed: {exc}")


def send_resend_reply(
    to_email: str,
    message: str,
    message_id: str | None = None,
    subject: str | None = None,
    api_key: str | None = None,
    from_email: str | None = None,
    reply_to: str | None = None,
) -> dict[str, Any]:
    """Send a best-effort threaded reply through Resend."""
    headers = {}
    if message_id:
        headers["In-Reply-To"] = message_id
        headers["References"] = message_id
    result = send_resend_email(
        email=to_email,
        name="",
        subject=subject or "Re: Your Message",
        body=message,
        headers=headers or None,
        api_key=api_key,
        from_email=from_email,
        reply_to=reply_to,
    )
    return {
        "success": result.ok,
        "message_id": result.message_id,
        "thread_id": message_id or result.message_id,
        "method": "resend_reply" if message_id else "resend_new_message",
        "error": result.error,
    }


def verify_resend_webhook_signature(
    raw_body: bytes,
    headers: dict[str, str],
    secret: str | None = None,
) -> bool:
    """Verify Resend/Svix webhook signature when RESEND_WEBHOOK_SECRET is set."""
    resolved_secret = secret if secret is not None else settings.resend_webhook_secret
    if not resolved_secret:
        return True

    svix_id = headers.get("svix-id") or headers.get("Svix-Id")
    svix_timestamp = headers.get("svix-timestamp") or headers.get("Svix-Timestamp")
    svix_signature = headers.get("svix-signature") or headers.get("Svix-Signature")
    if not (svix_id and svix_timestamp and svix_signature):
        return False

    try:
        timestamp = int(svix_timestamp)
    except ValueError:
        return False
    if abs(time.time() - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        return False

    try:
        secret_part = resolved_secret.split("_", 1)[1] if resolved_secret.startswith("whsec_") else resolved_secret
        secret_bytes = base64.b64decode(secret_part)
    except Exception:
        logger.warning("Invalid RESEND_WEBHOOK_SECRET format")
        return False

    signed_content = f"{svix_id}.{svix_timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode("utf-8")

    for signature in svix_signature.split(" "):
        if "," in signature:
            version, value = signature.split(",", 1)
            if version == "v1" and hmac.compare_digest(value, expected):
                return True
    return False


def fetch_resend_received_email(email_id: str, api_key: str | None = None) -> dict[str, Any]:
    """Fetch a received email body from Resend after an email.received webhook."""
    resolved_api_key = api_key or settings.resend_api_key
    if not resolved_api_key:
        raise RuntimeError("RESEND_API_KEY is not set.")
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{RESEND_API_BASE}/emails/receiving/{email_id}",
            headers={"Authorization": f"Bearer {resolved_api_key}"},
            params={"html_format": "cid"},
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Resend received email fetch failed: {_resend_error(response)}")
    data = response.json()
    return data.get("data") if isinstance(data.get("data"), dict) else data


def normalize_resend_received_email(
    event_payload: dict[str, Any],
    *,
    api_key: str | None = None,
    organization_id: int | None = None,
    mailbox_id: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return an app event id and AgentMail-like message payload for the monitor."""
    event_type = event_payload.get("type") or event_payload.get("event_type") or "email.received"
    data = event_payload.get("data") or {}
    email_id = data.get("email_id") or data.get("id")
    event_id = event_payload.get("id") or email_id or f"resend:{event_type}"
    if event_type != "email.received":
        return str(event_id), {"labels": ["ignored"], "subject": event_type}
    if not email_id:
        raise ValueError("Resend email.received webhook missing data.email_id")

    email_data = fetch_resend_received_email(str(email_id), api_key=api_key)
    headers = _headers_to_dict(email_data.get("headers") or {})
    message = {
        "id": email_data.get("id") or email_id,
        "message_id": email_data.get("message_id") or headers.get("message-id") or email_id,
        "thread_id": headers.get("references") or headers.get("in-reply-to") or email_data.get("message_id") or email_id,
        "from": email_data.get("from") or headers.get("from") or data.get("from") or "",
        "to": email_data.get("to") or data.get("to") or [],
        "subject": email_data.get("subject") or data.get("subject") or "",
        "text": email_data.get("text") or "",
        "html": email_data.get("html") or "",
        "extracted_text": email_data.get("text") or _html_to_text(email_data.get("html") or ""),
        "created_at": email_data.get("created_at") or data.get("created_at"),
        "headers": headers,
        "attachments": email_data.get("attachments") or [],
        "labels": ["received"],
        "provider": "resend",
    }
    if organization_id is not None:
        message["organization_id"] = organization_id
    if mailbox_id is not None:
        message["mailbox_id"] = mailbox_id
    return str(event_id), message


def _map_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for attachment in attachments:
        filename = attachment.get("filename") or "attachment"
        if attachment.get("url"):
            mapped.append({"filename": filename, "path": attachment["url"]})
            continue
        content = attachment.get("content_base64") or attachment.get("content")
        if content:
            mapped.append({"filename": filename, "content": content})
    return mapped


def _headers_to_dict(headers: Any) -> dict[str, str]:
    if isinstance(headers, dict):
        return {str(k).lower(): str(v) for k, v in headers.items()}
    if isinstance(headers, list):
        mapped = {}
        for item in headers:
            if isinstance(item, dict):
                name = item.get("name") or item.get("key")
                value = item.get("value")
                if name and value is not None:
                    mapped[str(name).lower()] = str(value)
        return mapped
    return {}


def _resend_error(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        return response.text
    message = data.get("message") or data.get("error") or data
    return str(message)


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    import re

    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
