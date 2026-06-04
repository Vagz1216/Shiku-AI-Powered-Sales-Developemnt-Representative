import sqlite3

import pytest

from services import tenant_service


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def tenant_db(tmp_path, monkeypatch):
    db_path = tmp_path / "tenant.sqlite3"
    with _connect(db_path) as conn:
        with open("db/schema.sql", "r", encoding="utf-8") as f:
            conn.executescript(f.read())

    monkeypatch.setattr(tenant_service, "get_conn", lambda: _connect(db_path))
    monkeypatch.setattr(tenant_service.settings, "platform_owner_emails", "owner@example.com")
    monkeypatch.setattr(tenant_service.settings, "mailbox_encryption_key", None)
    return db_path


def _claims(email="owner@example.com", sub="user_owner"):
    return {"sub": sub, "email": email, "name": "Owner"}


def test_normalize_timezone_accepts_nairobi_typo():
    assert tenant_service.normalize_timezone("Africa/NIAROBI") == "Africa/Nairobi"


def test_system_owner_can_create_org_and_admin(tenant_db):
    org = tenant_service.create_organization(
        "Acme Ltd",
        None,
        "admin@acme.test",
        _claims(),
    )

    assert org["slug"] == "acme-ltd"

    users = tenant_service.list_organization_users(org["id"], _claims())
    assert users[0]["email"] == "admin@acme.test"
    assert users[0]["role"] == "org_admin"


def test_non_owner_cannot_create_org(tenant_db):
    with pytest.raises(PermissionError):
        tenant_service.create_organization(
            "Blocked",
            None,
            None,
            _claims(email="user@example.com", sub="user_regular"),
        )


def test_system_owner_can_create_plan_and_org_admin_can_select_it(tenant_db):
    org = tenant_service.create_organization(
        "Plan Buyer",
        "plan-buyer",
        "admin@buyer.test",
        _claims(),
    )
    plan = tenant_service.create_subscription_plan(
        {
            "name": "Growth",
            "slug": "growth",
            "description": "Growth plan",
            "monthly_price_cents": 4900,
            "trial_days": 7,
            "max_users": 10,
            "active": True,
        },
        _claims(),
    )

    admin_claims = _claims(email="admin@buyer.test", sub="invited:admin@buyer.test")
    subscription = tenant_service.select_organization_plan(org["id"], plan["id"], admin_claims)

    assert subscription["status"] == "TRIALING"
    assert subscription["effective_status"] == "TRIALING"
    assert subscription["is_active"] is True
    assert subscription["plan"]["slug"] == "growth"
    assert tenant_service.organization_has_active_subscription(org["id"]) is True

    organizations = tenant_service.list_organizations(admin_claims)
    assert organizations[0]["subscription"]["plan"]["name"] == "Growth"


def test_workflow_requires_active_subscription(tenant_db):
    org = tenant_service.create_organization(
        "Blocked Workflow",
        "blocked-workflow",
        "admin@blocked.test",
        _claims(),
    )

    with pytest.raises(PermissionError):
        tenant_service.require_active_subscription(org["id"])

    plan = tenant_service.create_subscription_plan(
        {
            "name": "Archived",
            "slug": "archived",
            "trial_days": 14,
            "active": False,
        },
        _claims(),
    )
    admin_claims = _claims(email="admin@blocked.test", sub="invited:admin@blocked.test")

    with pytest.raises(ValueError):
        tenant_service.select_organization_plan(org["id"], plan["id"], admin_claims)


def test_org_admin_can_create_and_test_smtp_imap_mailbox(tenant_db):
    org = tenant_service.create_organization(
        "Market Hacks",
        "market-hacks",
        "admin@markethacks.co.ke",
        _claims(),
    )
    admin_claims = _claims(email="admin@markethacks.co.ke", sub="invited:admin@markethacks.co.ke")
    mailbox = tenant_service.create_mailbox(
        org["id"],
        {
            "provider": "smtp_imap",
            "display_name": "Market Hacks",
            "email_address": "info@markethacks.co.ke",
            "smtp_host": "mail.markethacks.co.ke",
            "smtp_port": 465,
            "smtp_username": "info@markethacks.co.ke",
            "smtp_password": "secret",
            "imap_host": "mail.markethacks.co.ke",
            "imap_port": 993,
            "imap_username": "info@markethacks.co.ke",
            "imap_password": "secret",
        },
        admin_claims,
    )

    assert mailbox["email_address"] == "info@markethacks.co.ke"
    assert mailbox["has_smtp_password"] is True
    assert "smtp_password_secret" not in mailbox

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port

        def login(self, username, password):
            assert username == "info@markethacks.co.ke"
            assert password == "secret"

        def noop(self):
            return "250", "OK"

        def quit(self):
            return None

    class FakeImap:
        def __init__(self, host, port):
            self.host = host
            self.port = port

        def login(self, username, password):
            assert username == "info@markethacks.co.ke"
            assert password == "secret"

        def select(self, mailbox, readonly=True):
            assert mailbox == "INBOX"
            assert readonly is True

        def logout(self):
            return None

    result = tenant_service.test_mailbox(
        org["id"],
        mailbox["id"],
        admin_claims,
        smtp_factory=FakeSmtp,
        imap_factory=FakeImap,
    )

    assert result == {"success": True, "status": "CONNECTED"}


def test_org_admin_can_create_and_test_resend_mailbox(tenant_db):
    org = tenant_service.create_organization(
        "Resend Tenant",
        "resend-tenant",
        "admin@resend.test",
        _claims(),
    )
    admin_claims = _claims(email="admin@resend.test", sub="invited:admin@resend.test")
    mailbox = tenant_service.create_mailbox(
        org["id"],
        {
            "provider": "resend",
            "display_name": "Resend Tenant",
            "email_address": "sdr@outreach.resend.test",
            "resend_domain": "outreach.resend.test",
            "resend_from_email": "Resend Tenant <sdr@outreach.resend.test>",
            "resend_reply_to": "sdr@outreach.resend.test",
            "resend_api_key": "re_tenant",
            "resend_webhook_secret": "whsec_tenant",
        },
        admin_claims,
    )

    assert mailbox["provider"] == "resend"
    assert mailbox["has_resend_api_key"] is True
    assert mailbox["has_resend_webhook_secret"] is True
    assert "resend_api_key_secret" not in mailbox

    result = tenant_service.test_mailbox(org["id"], mailbox["id"], admin_claims)

    assert result["success"] is True
    assert result["status"] == "CONNECTED"
