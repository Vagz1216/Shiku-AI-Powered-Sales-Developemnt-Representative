import base64
import hashlib
import hmac
import json
import time

import httpx

from services import resend_email


def test_send_resend_email_posts_expected_payload(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return httpx.Response(200, json={"id": "email_123"})

    monkeypatch.setattr(resend_email.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(
        resend_email.settings,
        "resend_from_email",
        "Market Hacks <sdr@outreach.markethacks.co.ke>",
    )
    monkeypatch.setattr(resend_email.settings, "resend_reply_to", "sdr@outreach.markethacks.co.ke")
    monkeypatch.setattr(resend_email.httpx, "Client", FakeClient)

    result = resend_email.send_resend_email(
        email="lead@example.com",
        name="Lead Person",
        subject="Hello",
        body="Plain text",
        html_body="<p>Plain text</p>",
    )

    assert result.ok is True
    assert result.message_id == "email_123"
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_test"
    assert captured["json"]["from"] == "Market Hacks <sdr@outreach.markethacks.co.ke>"
    assert captured["json"]["to"] == ["Lead Person <lead@example.com>"]
    assert captured["json"]["reply_to"] == "sdr@outreach.markethacks.co.ke"


def test_send_resend_email_can_use_tenant_credentials(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, headers, json):
            captured["headers"] = headers
            captured["json"] = json
            return httpx.Response(200, json={"id": "email_tenant"})

    monkeypatch.setattr(resend_email.settings, "resend_api_key", "")
    monkeypatch.setattr(resend_email.settings, "resend_from_email", "")
    monkeypatch.setattr(resend_email.settings, "resend_reply_to", "")
    monkeypatch.setattr(resend_email.httpx, "Client", FakeClient)

    result = resend_email.send_resend_email(
        email="lead@example.com",
        name="Lead Person",
        subject="Hello",
        body="Plain text",
        api_key="re_tenant",
        from_email="Tenant <sdr@tenant.test>",
        reply_to="reply@tenant.test",
    )

    assert result.ok is True
    assert result.message_id == "email_tenant"
    assert captured["headers"]["Authorization"] == "Bearer re_tenant"
    assert captured["json"]["from"] == "Tenant <sdr@tenant.test>"
    assert captured["json"]["reply_to"] == "reply@tenant.test"


def test_verify_resend_webhook_signature_accepts_valid_svix_signature(monkeypatch):
    secret_bytes = b"test-secret"
    secret = "whsec_" + base64.b64encode(secret_bytes).decode()
    raw_body = json.dumps({"type": "email.received"}).encode()
    svix_id = "msg_123"
    svix_timestamp = str(int(time.time()))
    signed = f"{svix_id}.{svix_timestamp}.{raw_body.decode()}".encode()
    signature = base64.b64encode(hmac.new(secret_bytes, signed, hashlib.sha256).digest()).decode()

    monkeypatch.setattr(resend_email.settings, "resend_webhook_secret", secret)

    assert resend_email.verify_resend_webhook_signature(
        raw_body,
        {
            "svix-id": svix_id,
            "svix-timestamp": svix_timestamp,
            "svix-signature": f"v1,{signature}",
        },
    )


def test_normalize_resend_received_email_fetches_full_message(monkeypatch):
    monkeypatch.setattr(
        resend_email,
        "fetch_resend_received_email",
        lambda email_id, api_key=None: {
            "id": email_id,
            "message_id": "<message@example.com>",
            "from": "Buyer <buyer@example.com>",
            "to": ["sdr@outreach.markethacks.co.ke"],
            "subject": "Re: Hello",
            "text": "Tell me more",
            "headers": {"in-reply-to": "<outbound@example.com>"},
            "attachments": [],
        },
    )

    event_id, message = resend_email.normalize_resend_received_email(
        {"id": "evt_123", "type": "email.received", "data": {"email_id": "email_123"}}
    )

    assert event_id == "evt_123"
    assert message["provider"] == "resend"
    assert message["from"] == "Buyer <buyer@example.com>"
    assert message["subject"] == "Re: Hello"
    assert message["extracted_text"] == "Tell me more"
    assert message["labels"] == ["received"]
