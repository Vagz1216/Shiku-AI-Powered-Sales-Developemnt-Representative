"""OAuth mailbox connection and provider API helpers."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import logging
import secrets
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any
from urllib.parse import urlencode

import httpx

from config import settings
from schema import SendEmailResult
from services import tenant_service
from utils.db_connection import dict_from_row, get_conn

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

MICROSOFT_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
MICROSOFT_SCOPES = ["offline_access", "openid", "profile", "email", "Mail.Send", "Mail.ReadWrite", "User.Read"]


def provider_oauth_configured(provider: str) -> bool:
    if provider == "gmail":
        return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)
    if provider == "microsoft":
        return bool(settings.microsoft_oauth_client_id and settings.microsoft_oauth_client_secret)
    return False


def build_authorization_url(
    *,
    organization_id: int,
    provider: str,
    data: dict[str, Any],
    actor_claims: dict[str, Any],
    redirect_uri: str,
) -> dict[str, Any]:
    if provider not in tenant_service.OAUTH_MAILBOX_PROVIDERS:
        raise ValueError(f"{provider} does not use OAuth")
    tenant_service._ensure_mailbox_provider_available(provider)
    actor_ctx = tenant_service.require_org_role(actor_claims, organization_id, tenant_service.ADMIN_ROLES)
    state = _sign_state(
        {
            "provider": provider,
            "organization_id": organization_id,
            "actor_user_id": actor_ctx["user"]["id"],
            "display_name": data.get("display_name"),
            "daily_limit": int(data.get("daily_limit") or 100),
            "nonce": secrets.token_urlsafe(16),
            "exp": int(datetime.datetime.now(datetime.UTC).timestamp()) + 900,
        }
    )
    if provider == "gmail":
        params = {
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    else:
        params = {
            "client_id": settings.microsoft_oauth_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": " ".join(MICROSOFT_SCOPES),
            "state": state,
        }
        auth_url = f"{_microsoft_authorize_url()}?{urlencode(params)}"
    return {"authorization_url": auth_url, "provider": provider}


def complete_authorization(
    *,
    provider: str,
    code: str,
    state: str,
    redirect_uri: str,
) -> dict[str, Any]:
    payload = _verify_state(state)
    if payload["provider"] != provider:
        raise ValueError("OAuth provider mismatch")
    if provider == "gmail":
        token_data = _exchange_google_code(code, redirect_uri)
        account = _fetch_google_account(token_data["access_token"])
    elif provider == "microsoft":
        token_data = _exchange_microsoft_code(code, redirect_uri)
        account = _fetch_microsoft_account(token_data["access_token"])
    else:
        raise ValueError(f"{provider} does not use OAuth")

    email_address = tenant_service.normalize_email(account["email"])
    expires_at = _token_expires_at(token_data)
    mailbox = _upsert_oauth_mailbox(
        organization_id=int(payload["organization_id"]),
        actor_user_id=int(payload["actor_user_id"]),
        provider=provider,
        display_name=payload.get("display_name") or account.get("name") or email_address,
        email_address=email_address,
        daily_limit=int(payload.get("daily_limit") or 100),
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at,
        scopes=token_data.get("scope") or "",
        external_account_id=account.get("id") or email_address,
    )
    return mailbox


def send_oauth_email(
    mailbox: dict[str, Any],
    *,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> SendEmailResult:
    access_token = get_valid_access_token(mailbox)
    message, message_id = _build_message(
        mailbox,
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body=body,
        html_body=html_body,
        attachments=attachments,
        headers=headers,
    )
    if mailbox["provider"] == "gmail":
        raw = _base64url(message.as_bytes())
        payload = {"raw": raw}
        if _google_thread_id(headers):
            payload["threadId"] = _google_thread_id(headers)
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{GOOGLE_GMAIL_BASE}/messages/send",
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(_http_error(response))
        data = response.json()
        return SendEmailResult(ok=True, message_id=data.get("id") or message_id, thread_id=data.get("threadId") or message_id)

    if mailbox["provider"] == "microsoft":
        payload = _microsoft_message_payload(
            mailbox,
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=attachments,
            headers=headers,
        )
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{MICROSOFT_GRAPH_BASE}/me/sendMail",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"message": payload, "saveToSentItems": True},
            )
        if response.status_code >= 400:
            raise RuntimeError(_http_error(response))
        return SendEmailResult(ok=True, message_id=message_id, thread_id=headers.get("References") if headers else message_id)

    raise ValueError(f"{mailbox['provider']} does not support OAuth sending")


def fetch_unread_messages(mailbox: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    access_token = get_valid_access_token(mailbox)
    if mailbox["provider"] == "gmail":
        with httpx.Client(timeout=30) as client:
            list_response = client.get(
                f"{GOOGLE_GMAIL_BASE}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"q": "is:unread", "maxResults": max(1, min(limit, 25))},
            )
            if list_response.status_code >= 400:
                raise RuntimeError(_http_error(list_response))
            messages = list_response.json().get("messages") or []
            results = []
            for item in messages[:limit]:
                message_id = item.get("id")
                if not message_id:
                    continue
                message_response = client.get(
                    f"{GOOGLE_GMAIL_BASE}/messages/{message_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"format": "raw"},
                )
                if message_response.status_code >= 400:
                    raise RuntimeError(_http_error(message_response))
                data = message_response.json()
                raw = _base64url_decode(data.get("raw") or "")
                results.append({"provider_message_id": message_id, "thread_id": data.get("threadId"), "raw": raw})
            return results

    if mailbox["provider"] == "microsoft":
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{MICROSOFT_GRAPH_BASE}/me/mailFolders/inbox/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "$filter": "isRead eq false",
                    "$orderby": "receivedDateTime desc",
                    "$top": max(1, min(limit, 25)),
                    "$select": "id,conversationId,internetMessageId,subject,from,toRecipients,receivedDateTime,body,internetMessageHeaders",
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(_http_error(response))
        return [
            {"provider_message_id": item.get("id"), "thread_id": item.get("conversationId"), "message": item}
            for item in response.json().get("value", [])
            if item.get("id")
        ]

    raise ValueError(f"{mailbox['provider']} does not support OAuth sync")


def mark_message_seen(mailbox: dict[str, Any], provider_message_id: str) -> None:
    access_token = get_valid_access_token(mailbox)
    if mailbox["provider"] == "gmail":
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{GOOGLE_GMAIL_BASE}/messages/{provider_message_id}/modify",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"removeLabelIds": ["UNREAD"]},
            )
    elif mailbox["provider"] == "microsoft":
        with httpx.Client(timeout=30) as client:
            response = client.patch(
                f"{MICROSOFT_GRAPH_BASE}/me/messages/{provider_message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"isRead": True},
            )
    else:
        raise ValueError(f"{mailbox['provider']} does not support OAuth sync")
    if response.status_code >= 400:
        raise RuntimeError(_http_error(response))


def get_valid_access_token(mailbox: dict[str, Any]) -> str:
    access_token = tenant_service.decrypt_secret(mailbox.get("oauth_access_token_secret"))
    refresh_token = tenant_service.decrypt_secret(mailbox.get("oauth_refresh_token_secret"))
    if not refresh_token:
        raise ValueError("OAuth refresh token is missing; reconnect this mailbox")
    if access_token and not _token_expired(mailbox.get("oauth_token_expires_at")):
        return access_token
    token_data = _refresh_token(mailbox["provider"], refresh_token)
    expires_at = _token_expires_at(token_data)
    access_token = token_data["access_token"]
    _update_oauth_tokens(
        int(mailbox["id"]),
        access_token=access_token,
        refresh_token=token_data.get("refresh_token") or refresh_token,
        expires_at=expires_at,
        scopes=token_data.get("scope") or mailbox.get("oauth_scopes"),
    )
    mailbox["oauth_access_token_secret"] = tenant_service.encrypt_secret(access_token)
    mailbox["oauth_token_expires_at"] = expires_at
    return access_token


def _exchange_google_code(code: str, redirect_uri: str) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(_http_error(response))
    return response.json()


def _exchange_microsoft_code(code: str, redirect_uri: str) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            _microsoft_token_url(),
            data={
                "client_id": settings.microsoft_oauth_client_id,
                "client_secret": settings.microsoft_oauth_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(_http_error(response))
    return response.json()


def _refresh_token(provider: str, refresh_token: str) -> dict[str, Any]:
    if provider == "gmail":
        url = GOOGLE_TOKEN_URL
        data = {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    elif provider == "microsoft":
        url = _microsoft_token_url()
        data = {
            "client_id": settings.microsoft_oauth_client_id,
            "client_secret": settings.microsoft_oauth_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(MICROSOFT_SCOPES),
        }
    else:
        raise ValueError(f"{provider} does not support OAuth")
    with httpx.Client(timeout=30) as client:
        response = client.post(url, data=data)
    if response.status_code >= 400:
        raise RuntimeError(_http_error(response))
    return response.json()


def _fetch_google_account(access_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code >= 400:
        raise RuntimeError(_http_error(response))
    data = response.json()
    return {"email": data.get("email"), "name": data.get("name"), "id": data.get("id")}


def _fetch_microsoft_account(access_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{MICROSOFT_GRAPH_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$select": "id,displayName,mail,userPrincipalName"},
        )
    if response.status_code >= 400:
        raise RuntimeError(_http_error(response))
    data = response.json()
    return {
        "email": data.get("mail") or data.get("userPrincipalName"),
        "name": data.get("displayName"),
        "id": data.get("id"),
    }


def _upsert_oauth_mailbox(
    *,
    organization_id: int,
    actor_user_id: int,
    provider: str,
    display_name: str,
    email_address: str,
    daily_limit: int,
    access_token: str,
    refresh_token: str | None,
    expires_at: str,
    scopes: str,
    external_account_id: str,
) -> dict[str, Any]:
    if not refresh_token:
        raise ValueError("OAuth provider did not return a refresh token. Reconnect and approve offline access.")
    now = tenant_service.now_iso()
    with get_conn() as conn:
        with conn:
            existing = dict_from_row(
                conn.execute(
                    "SELECT id FROM mailbox_connections WHERE organization_id = ? AND email_address = ?",
                    (organization_id, email_address),
                ).fetchone()
            )
            values = (
                provider,
                display_name,
                email_address,
                tenant_service.encrypt_secret(access_token),
                tenant_service.encrypt_secret(refresh_token),
                expires_at,
                scopes,
                external_account_id,
                daily_limit,
                now,
            )
            if existing:
                mailbox_id = int(existing["id"])
                conn.execute(
                    "UPDATE mailbox_connections SET provider = ?, display_name = ?, email_address = ?, status = 'CONNECTED', "
                    "smtp_host = NULL, smtp_port = NULL, smtp_username = NULL, smtp_password_secret = NULL, "
                    "imap_host = NULL, imap_port = NULL, imap_username = NULL, imap_password_secret = NULL, "
                    "resend_domain = NULL, resend_from_email = NULL, resend_reply_to = NULL, "
                    "resend_api_key_secret = NULL, resend_webhook_secret_secret = NULL, "
                    "oauth_access_token_secret = ?, oauth_refresh_token_secret = ?, oauth_token_expires_at = ?, "
                    "oauth_scopes = ?, oauth_external_account_id = ?, daily_limit = ?, last_error = NULL, updated_at = ? "
                    "WHERE organization_id = ? AND id = ?",
                    values + (organization_id, mailbox_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO mailbox_connections "
                    "(organization_id, provider, display_name, email_address, status, "
                    "oauth_access_token_secret, oauth_refresh_token_secret, oauth_token_expires_at, "
                    "oauth_scopes, oauth_external_account_id, daily_limit, updated_at) "
                    "VALUES (?, ?, ?, ?, 'CONNECTED', ?, ?, ?, ?, ?, ?, ?)",
                    (organization_id,) + values,
                )
                mailbox_id = cur.lastrowid
            conn.execute(
                "INSERT INTO events (type, payload, metadata) VALUES (?, ?, ?)",
                (
                    "mailbox_oauth_connected",
                    json.dumps({"organization_id": organization_id, "mailbox_id": mailbox_id, "provider": provider}),
                    json.dumps({"actor_user_id": actor_user_id}),
                ),
            )
    return tenant_service.get_mailbox(organization_id, mailbox_id)


def _update_oauth_tokens(mailbox_id: int, *, access_token: str, refresh_token: str, expires_at: str, scopes: str | None) -> None:
    with get_conn() as conn:
        with conn:
            conn.execute(
                "UPDATE mailbox_connections SET oauth_access_token_secret = ?, oauth_refresh_token_secret = ?, "
                "oauth_token_expires_at = ?, oauth_scopes = COALESCE(?, oauth_scopes), updated_at = ? WHERE id = ?",
                (
                    tenant_service.encrypt_secret(access_token),
                    tenant_service.encrypt_secret(refresh_token),
                    expires_at,
                    scopes,
                    tenant_service.now_iso(),
                    mailbox_id,
                ),
            )


def _sign_state(payload: dict[str, Any]) -> str:
    raw = _base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_state_secret(), raw.encode("ascii"), hashlib.sha256).digest()
    return f"{raw}.{_base64url(signature)}"


def _verify_state(state: str) -> dict[str, Any]:
    try:
        raw, signature = state.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid OAuth state") from exc
    expected = _base64url(hmac.new(_state_secret(), raw.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid OAuth state signature")
    payload = json.loads(_base64url_decode(raw).decode("utf-8"))
    if int(payload.get("exp") or 0) < int(datetime.datetime.now(datetime.UTC).timestamp()):
        raise ValueError("OAuth state expired")
    return payload


def _state_secret() -> bytes:
    secret = (
        settings.mailbox_oauth_state_secret
        or settings.clerk_secret_key
        or settings.mailbox_encryption_key
        or "local-dev-mailbox-oauth-state-secret"
    )
    return secret.encode("utf-8")


def _token_expires_at(token_data: dict[str, Any]) -> str:
    expires_in = int(token_data.get("expires_in") or 3600)
    expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=max(60, expires_in - 60))
    return expires_at.isoformat().replace("+00:00", "Z")


def _token_expired(value: Any) -> bool:
    parsed = tenant_service.parse_iso(value)
    if not parsed:
        return True
    return parsed <= datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=60)


def _build_message(
    mailbox: dict[str, Any],
    *,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    html_body: str | None,
    attachments: list[dict[str, Any]] | None,
    headers: dict[str, str] | None,
) -> tuple[EmailMessage, str]:
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
    return msg, message_id


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


def _microsoft_message_payload(
    mailbox: dict[str, Any],
    *,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    html_body: str | None,
    attachments: list[dict[str, Any]] | None,
    headers: dict[str, str] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "HTML" if html_body else "Text", "content": html_body or body},
        "toRecipients": [{"emailAddress": {"address": to_email, "name": to_name or to_email}}],
    }
    if headers:
        payload["internetMessageHeaders"] = [{"name": key, "value": value} for key, value in headers.items() if value]
    graph_attachments = []
    for attachment in attachments or []:
        content = attachment.get("content_base64") or attachment.get("content")
        if not content:
            continue
        if isinstance(content, str) and content.startswith("data:") and "," in content:
            content = content.split(",", 1)[1]
        graph_attachments.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": attachment.get("filename") or "attachment",
                "contentType": attachment.get("content_type") or "application/octet-stream",
                "contentBytes": content,
            }
        )
    if graph_attachments:
        payload["attachments"] = graph_attachments
    return payload


def _google_thread_id(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    value = headers.get("X-Gmail-Thread-ID")
    return value or None


def _microsoft_authorize_url() -> str:
    return f"https://login.microsoftonline.com/{settings.microsoft_oauth_tenant}/oauth2/v2.0/authorize"


def _microsoft_token_url() -> str:
    return f"https://login.microsoftonline.com/{settings.microsoft_oauth_tenant}/oauth2/v2.0/token"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _http_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = response.text
    return f"{response.status_code}: {payload}"
