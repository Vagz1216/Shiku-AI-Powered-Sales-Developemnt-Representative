"""SMTP/IMAP transport for organization-owned mailbox connections."""

from __future__ import annotations

import base64
import datetime
import imaplib
import logging
import smtplib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, make_msgid, parsedate_to_datetime
from typing import Any

from config import settings
from schema import SendEmailResult
from services.resend_email import send_resend_email, send_resend_reply
from services.tenant_service import decrypt_secret
from utils.db_connection import dict_from_row, get_conn

logger = logging.getLogger(__name__)


def validate_mailbox_config(mailbox_id: int | None = None) -> str | None:
    try:
        _resolve_mailbox(mailbox_id)
        return None
    except Exception as exc:
        return str(exc)


def send_mailbox_email(
    email: str,
    name: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
    mailbox_id: int | None = None,
    organization_id: int | None = None,
) -> SendEmailResult:
    """Send email using the default connected SMTP/IMAP mailbox."""
    try:
        mailbox = _resolve_mailbox(mailbox_id, organization_id=organization_id)
        if error := _mailbox_daily_limit_error(mailbox):
            return SendEmailResult(ok=False, error=error)
        if mailbox["provider"] == "resend":
            return send_resend_email(
                email=email,
                name=name,
                subject=subject,
                body=body,
                html_body=html_body,
                attachments=attachments,
                headers=headers,
                api_key=decrypt_secret(mailbox.get("resend_api_key_secret")),
                from_email=mailbox.get("resend_from_email") or mailbox.get("email_address"),
                reply_to=mailbox.get("resend_reply_to"),
            )
        message_id = _send_via_smtp(
            mailbox,
            to_email=email,
            to_name=name,
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=attachments,
            headers=headers,
        )
        return SendEmailResult(ok=True, message_id=message_id, thread_id=headers.get("References") if headers else message_id)
    except Exception as exc:
        logger.error("Mailbox send failed: %s", exc)
        return SendEmailResult(ok=False, error=f"Mailbox send failed: {exc}")


def send_mailbox_reply(
    to_email: str,
    message: str,
    message_id: str | None = None,
    subject: str | None = None,
    mailbox_id: int | None = None,
    organization_id: int | None = None,
) -> dict[str, Any]:
    mailbox = _resolve_mailbox(mailbox_id, organization_id=organization_id)
    if mailbox["provider"] == "resend":
        return send_resend_reply(
            to_email=to_email,
            message=message,
            message_id=message_id,
            subject=subject,
            api_key=decrypt_secret(mailbox.get("resend_api_key_secret")),
            from_email=mailbox.get("resend_from_email") or mailbox.get("email_address"),
            reply_to=mailbox.get("resend_reply_to"),
        )
    headers = {}
    if message_id:
        headers["In-Reply-To"] = message_id
        headers["References"] = message_id
    result = send_mailbox_email(
        email=to_email,
        name="",
        subject=subject or "Re: Your Message",
        body=message,
        headers=headers or None,
        organization_id=organization_id,
        mailbox_id=mailbox_id,
    )
    return {
        "success": result.ok,
        "message_id": result.message_id,
        "thread_id": message_id or result.message_id,
        "method": "mailbox_reply" if message_id else "mailbox_new_message",
        "error": result.error,
    }


async def sync_unread_mailbox(
    organization_id: int,
    mailbox_id: int,
    *,
    limit: int = 10,
    mark_seen: bool = True,
    callback=None,
) -> dict[str, Any]:
    """Fetch unread IMAP messages and pass them into the existing email monitor."""
    from email_monitor.monitor import email_monitor

    mailbox = _resolve_mailbox(mailbox_id=mailbox_id, organization_id=organization_id, provider="smtp_imap")
    client = _imap_client(mailbox)
    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        client.login(mailbox["imap_username"], decrypt_secret(mailbox["imap_password_secret"]))
        client.select("INBOX")
        status, data = client.uid("SEARCH", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("IMAP search failed")
        uids = (data[0] or b"").split()[:limit]
        for uid in uids:
            uid_text = uid.decode("ascii", errors="ignore")
            try:
                fetch_status, fetched = client.uid("FETCH", uid, "(BODY.PEEK[])")
                if fetch_status != "OK" or not fetched:
                    raise RuntimeError("IMAP fetch failed")
                raw_message = _extract_fetch_bytes(fetched)
                message_payload = _normalize_imap_message(raw_message, mailbox, uid_text)
                sender_email = _extract_email_address(message_payload["from"])
                route = _route_inbound_sender(sender_email, organization_id)
                if not route["process"]:
                    skipped.append(
                        {
                            "uid": uid_text,
                            "from": message_payload["from"],
                            "subject": message_payload["subject"],
                            "reason": route["reason"],
                        }
                    )
                    continue

                message_payload["campaign_id"] = route["campaign_id"]
                result = await email_monitor.process_incoming_email(message_payload, callback=callback)
                processed.append(
                    {
                        "uid": uid_text,
                        "from": message_payload["from"],
                        "subject": message_payload["subject"],
                        "action": result.action_taken,
                        "success": result.success,
                        "error": result.error,
                    }
                )
                if mark_seen:
                    client.uid("STORE", uid, "+FLAGS", r"(\Seen)")
            except Exception as exc:
                logger.exception("Failed to process IMAP message uid=%s", uid_text)
                errors.append({"uid": uid_text, "error": str(exc)})
    finally:
        try:
            client.logout()
        except Exception:
            pass

    _update_mailbox_sync_state(mailbox_id, None if not errors else f"{len(errors)} sync error(s)")
    return {
        "mailbox_id": mailbox_id,
        "checked": len(processed) + len(skipped) + len(errors),
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }


def _resolve_mailbox(
    mailbox_id: int | None = None,
    organization_id: int | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    resolved_id = mailbox_id or settings.default_mailbox_id
    params: list[Any] = []
    where = ["status = 'CONNECTED'"]
    if provider:
        where.append("provider = ?")
        params.append(provider)
    else:
        where.append("provider IN ('smtp_imap', 'resend')")
    if resolved_id:
        where.append("id = ?")
        params.append(resolved_id)
    if organization_id:
        where.append("organization_id = ?")
        params.append(organization_id)
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT * FROM mailbox_connections WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 1",
            tuple(params),
        ).fetchone()
        mailbox = dict_from_row(row)
    if not mailbox:
        raise ValueError("No connected SMTP/IMAP mailbox found. Connect and test a mailbox first.")
    return mailbox


def _mailbox_daily_limit_error(mailbox: dict[str, Any]) -> str | None:
    limit = int(mailbox.get("daily_limit") or 0)
    organization_id = mailbox.get("organization_id")
    if not limit or not organization_id:
        return None
    today = datetime.date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS sent_count FROM email_messages "
            "WHERE organization_id = ? AND direction = 'outbound' "
            "AND UPPER(status) = 'SENT' AND substr(created_at, 1, 10) = ?",
            (organization_id, today),
        ).fetchone()
        data = dict_from_row(row) or {}
    if int(data.get("sent_count") or 0) >= limit:
        return f"Mailbox daily limit reached ({limit}). Try again tomorrow."
    return None


def _send_via_smtp(
    mailbox: dict[str, Any],
    *,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    html_body: str | None,
    attachments: list[dict[str, Any]] | None,
    headers: dict[str, str] | None,
) -> str:
    host = mailbox["smtp_host"]
    port = int(mailbox["smtp_port"] or (465 if mailbox["smtp_use_ssl"] else 587))
    username = mailbox["smtp_username"]
    password = decrypt_secret(mailbox["smtp_password_secret"])
    if not (host and username and password):
        raise ValueError("Mailbox SMTP host, username, and password are required")

    from_email = mailbox["email_address"]
    display_name = mailbox.get("display_name") or from_email
    domain = from_email.split("@", 1)[1] if "@" in from_email else None
    message_id = make_msgid(domain=domain)

    msg = EmailMessage()
    msg["From"] = formataddr((display_name, from_email))
    msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    for key, value in (headers or {}).items():
        if value:
            msg[key] = value
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    for attachment in attachments or []:
        _attach_payload(msg, attachment)

    smtp_cls = smtplib.SMTP_SSL if mailbox["smtp_use_ssl"] else smtplib.SMTP
    client = smtp_cls(host, port, timeout=30)
    try:
        if not mailbox["smtp_use_ssl"]:
            client.starttls()
        client.login(username, password)
        client.send_message(msg)
    finally:
        try:
            client.quit()
        except Exception:
            pass
    return message_id


def _attach_payload(msg: EmailMessage, attachment: dict[str, Any]) -> None:
    content = attachment.get("content_base64") or attachment.get("content")
    if not content:
        return
    if isinstance(content, str) and content.startswith("data:") and "," in content:
        content = content.split(",", 1)[1]
    raw = base64.b64decode(content)
    content_type = attachment.get("content_type") or "application/octet-stream"
    maintype, _, subtype = content_type.partition("/")
    msg.add_attachment(
        raw,
        maintype=maintype or "application",
        subtype=subtype or "octet-stream",
        filename=attachment.get("filename") or "attachment",
    )


def _imap_client(mailbox: dict[str, Any]):
    host = mailbox["imap_host"]
    port = int(mailbox["imap_port"] or (993 if mailbox["imap_use_ssl"] else 143))
    if mailbox["imap_use_ssl"]:
        return imaplib.IMAP4_SSL(host, port)
    return imaplib.IMAP4(host, port)


def _extract_fetch_bytes(fetched: list[Any]) -> bytes:
    for item in fetched:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    raise RuntimeError("IMAP fetch response did not contain message bytes")


def _normalize_imap_message(raw_message: bytes, mailbox: dict[str, Any], uid: str) -> dict[str, Any]:
    parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
    text, html, attachments = _extract_message_parts(parsed)
    subject = str(parsed.get("subject") or "")
    from_value = str(parsed.get("from") or "")
    message_id = str(parsed.get("message-id") or f"imap:{mailbox['id']}:{uid}")
    references = str(parsed.get("references") or parsed.get("in-reply-to") or message_id)
    created_at = _format_message_date(str(parsed.get("date") or ""))
    return {
        "id": f"imap:{mailbox['id']}:{uid}",
        "message_id": message_id,
        "thread_id": references,
        "from": from_value,
        "to": [mailbox["email_address"]],
        "subject": subject,
        "text": text,
        "html": html,
        "extracted_text": text or _html_to_text(html),
        "created_at": created_at,
        "headers": {
            "message-id": message_id,
            "references": references,
            "in-reply-to": str(parsed.get("in-reply-to") or ""),
        },
        "attachments": attachments,
        "labels": ["received"],
        "provider": "smtp_imap",
    }


def _extract_message_parts(parsed) -> tuple[str, str, list[dict[str, Any]]]:
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    for part in parsed.walk() if parsed.is_multipart() else [parsed]:
        content_disposition = part.get_content_disposition()
        content_type = part.get_content_type()
        filename = part.get_filename()
        if content_disposition == "attachment" or filename:
            payload = part.get_payload(decode=True) or b""
            extracted_text = ""
            if content_type.startswith("text/"):
                try:
                    extracted_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    extracted_text = ""
            attachments.append(
                {
                    "filename": filename or "attachment",
                    "content_type": content_type,
                    "size_bytes": len(payload),
                    "extracted_text": extracted_text,
                }
            )
            continue
        if content_type == "text/plain":
            text_parts.append(part.get_content())
        elif content_type == "text/html":
            html_parts.append(part.get_content())
    return "\n\n".join(text_parts).strip(), "\n\n".join(html_parts).strip(), attachments


def _format_message_date(date_header: str) -> str | None:
    if not date_header:
        return None
    try:
        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)
        return dt.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    import re

    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _update_mailbox_sync_state(mailbox_id: int, error: str | None) -> None:
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
    with get_conn() as conn:
        with conn:
            conn.execute(
                "UPDATE mailbox_connections SET last_sync_at = ?, last_error = ?, updated_at = ? WHERE id = ?",
                (now, error, now, mailbox_id),
            )


def _extract_email_address(value: str) -> str:
    from email.utils import parseaddr

    _name, email = parseaddr(value or "")
    return (email or value or "").strip().lower()


def _route_inbound_sender(sender_email: str, organization_id: int | None = None) -> dict[str, Any]:
    if not sender_email or "@" not in sender_email:
        return {"process": False, "reason": "invalid sender email", "campaign_id": None}

    with get_conn() as conn:
        lead = dict_from_row(
            conn.execute(
                "SELECT id, email_opt_out FROM leads WHERE lower(email) = lower(?) "
                + ("AND organization_id = ?" if organization_id is not None else ""),
                (sender_email, organization_id) if organization_id is not None else (sender_email,),
            ).fetchone()
        )
        if not lead:
            return {"process": False, "reason": "sender is not a known lead", "campaign_id": None}
        if lead.get("email_opt_out"):
            return {"process": False, "reason": "lead is opted out", "campaign_id": None}
        campaign = dict_from_row(
            conn.execute(
                "SELECT c.id FROM campaign_leads cl "
                "JOIN campaigns c ON c.id = cl.campaign_id "
                "WHERE cl.lead_id = ? AND c.status = 'ACTIVE' "
                + ("AND c.organization_id = ? " if organization_id is not None else "")
                + "ORDER BY c.id DESC LIMIT 1",
                (lead["id"], organization_id) if organization_id is not None else (lead["id"],),
            ).fetchone()
        )
        if not campaign:
            return {"process": False, "reason": "known lead has no active campaign", "campaign_id": None}
        return {"process": True, "reason": "known campaign lead", "campaign_id": campaign["id"]}
