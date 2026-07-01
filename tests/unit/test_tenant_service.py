import sqlite3
import asyncio
from urllib.parse import parse_qs, urlparse

import pytest

from services import tenant_service
from services import llm_credential_service
from services import mailbox_oauth_service


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
    monkeypatch.setattr(llm_credential_service, "get_conn", lambda: _connect(db_path))
    monkeypatch.setattr(mailbox_oauth_service, "get_conn", lambda: _connect(db_path))
    monkeypatch.setattr(tenant_service.settings, "platform_owner_emails", "owner@example.com")
    monkeypatch.setattr(tenant_service.settings, "mailbox_encryption_key", None)
    monkeypatch.setattr(llm_credential_service.settings, "organization_llm_keys_enabled", True)
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


def test_system_owner_platform_access_does_not_grant_workflow_membership(tenant_db):
    platform_ctx = tenant_service.require_org_member_role(_claims(), 1, tenant_service.WORKFLOW_ROLES)
    assert platform_ctx["system_owner"] is True

    org = tenant_service.create_organization(
        "Tenant Ops",
        "tenant-ops",
        "admin@tenant-ops.test",
        _claims(),
    )

    platform_ctx = tenant_service.require_org_role(_claims(), org["id"], tenant_service.WORKFLOW_ROLES)
    assert platform_ctx["system_owner"] is True

    with pytest.raises(PermissionError, match="tenant member access required"):
        tenant_service.require_org_member_role(_claims(), org["id"], tenant_service.WORKFLOW_ROLES)

    admin_claims = _claims(email="admin@tenant-ops.test", sub="invited:admin@tenant-ops.test")
    member_ctx = tenant_service.require_org_member_role(admin_claims, org["id"], tenant_service.WORKFLOW_ROLES)
    assert member_ctx["membership"]["role"] == "org_admin"


def test_system_owner_capabilities_exclude_tenant_workflows():
    capabilities = tenant_service.role_capabilities("system_owner")
    platform_capabilities = tenant_service.role_capabilities("system_owner", platform_organization=True)

    assert capabilities["can_manage_subscription_plans"] is True
    assert capabilities["can_run_outreach"] is False
    assert capabilities["can_review_drafts"] is False
    assert platform_capabilities["can_run_outreach"] is True
    assert platform_capabilities["can_review_drafts"] is True


def test_non_owner_cannot_create_org(tenant_db):
    with pytest.raises(PermissionError):
        tenant_service.create_organization(
            "Blocked",
            None,
            None,
            _claims(email="user@example.com", sub="user_regular"),
        )


def test_system_owner_can_create_plan_and_select_it_for_org(tenant_db):
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
    with pytest.raises(PermissionError):
        tenant_service.select_organization_plan(org["id"], plan["id"], admin_claims)

    subscription = tenant_service.select_organization_plan(org["id"], plan["id"], _claims())

    assert subscription["status"] == "TRIALING"
    assert subscription["effective_status"] == "TRIALING"
    assert subscription["is_active"] is True
    assert subscription["plan"]["slug"] == "growth"
    assert tenant_service.organization_has_active_subscription(org["id"]) is True

    organizations = tenant_service.list_organizations(admin_claims)
    assert organizations[0]["subscription"]["plan"]["name"] == "Growth"


def test_byok_plan_allows_org_admin_to_store_write_only_llm_credential(tenant_db):
    org = tenant_service.create_organization(
        "BYOK Buyer",
        "byok-buyer",
        "admin@byok.test",
        _claims(),
    )
    plan = tenant_service.create_subscription_plan(
        {
            "name": "BYOK Growth",
            "slug": "byok-growth",
            "trial_days": 14,
            "allow_byok": True,
            "byok_provider_mode": "organization_first",
            "max_llm_credentials": 2,
            "active": True,
        },
        _claims(),
    )
    admin_claims = _claims(email="admin@byok.test", sub="invited:admin@byok.test")
    tenant_service.select_organization_plan(org["id"], plan["id"], _claims())

    credential = llm_credential_service.create_credential(
        org["id"],
        {
            "provider": "gemini",
            "label": "Gemini primary",
            "api_key": "tenant-secret-key",
            "default_model": "gemini-2.5-flash",
        },
        admin_claims,
    )

    assert credential["provider"] == "gemini"
    assert credential["api_key_fingerprint"]["present"] is True
    assert "api_key_secret" not in credential
    assert "api_key" not in credential

    listed = llm_credential_service.list_credentials(org["id"], admin_claims)
    assert listed["policy"]["enabled"] is True
    assert listed["policy"]["provider_mode"] == "organization_first"
    assert listed["credentials"][0]["api_key_fingerprint"]["sha12"] == credential["api_key_fingerprint"]["sha12"]


def test_org_admin_can_test_llm_credential_and_persist_success(tenant_db, monkeypatch):
    org = tenant_service.create_organization(
        "Validator",
        "validator",
        "admin@validator.test",
        _claims(),
    )
    plan = tenant_service.create_subscription_plan(
        {
            "name": "Validator Plan",
            "slug": "validator-plan",
            "trial_days": 14,
            "allow_byok": True,
            "byok_provider_mode": "organization_first",
            "max_llm_credentials": 2,
            "active": True,
        },
        _claims(),
    )
    admin_claims = _claims(email="admin@validator.test", sub="invited:admin@validator.test")
    tenant_service.select_organization_plan(org["id"], plan["id"], _claims())
    credential = llm_credential_service.create_credential(
        org["id"],
        {
            "provider": "gemini",
            "api_key": "tenant-secret-key",
        },
        admin_claims,
    )

    async def _fake_test(provider, model, api_key, fields):
        assert provider == "gemini"
        assert model == "gemini-2.5-flash"
        assert api_key == "tenant-secret-key"
        assert fields["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
        return {"message": "Credential test succeeded via gemini model gemini-2.5-flash.", "latency_ms": 123.4, "sample": "OK"}

    monkeypatch.setattr(llm_credential_service, "_run_provider_test", _fake_test)

    result = asyncio.run(llm_credential_service.test_credential(org["id"], credential["id"], admin_claims))

    assert result["status"] == "passed"
    assert result["latency_ms"] == 123.4
    assert result["credential"]["last_error"] is None
    assert result["credential"]["last_tested_at"] is not None


def test_org_admin_can_test_llm_credential_and_persist_failure(tenant_db, monkeypatch):
    org = tenant_service.create_organization(
        "Broken Validator",
        "broken-validator",
        "admin@broken-validator.test",
        _claims(),
    )
    plan = tenant_service.create_subscription_plan(
        {
            "name": "Broken Validator Plan",
            "slug": "broken-validator-plan",
            "trial_days": 14,
            "allow_byok": True,
            "byok_provider_mode": "organization_first",
            "max_llm_credentials": 2,
            "active": True,
        },
        _claims(),
    )
    admin_claims = _claims(email="admin@broken-validator.test", sub="invited:admin@broken-validator.test")
    tenant_service.select_organization_plan(org["id"], plan["id"], _claims())
    credential = llm_credential_service.create_credential(
        org["id"],
        {
            "provider": "openai",
            "api_key": "tenant-openai-key",
        },
        admin_claims,
    )

    async def _fake_test(provider, model, api_key, fields):
        raise RuntimeError("insufficient_quota")

    monkeypatch.setattr(llm_credential_service, "_run_provider_test", _fake_test)

    result = asyncio.run(llm_credential_service.test_credential(org["id"], credential["id"], admin_claims))

    assert result["status"] == "failed"
    assert "quota/billing" in result["message"]
    assert result["credential"]["last_tested_at"] is not None
    assert "quota/billing" in result["credential"]["last_error"]


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
        tenant_service.select_organization_plan(org["id"], plan["id"], _claims())


def test_system_owner_can_mark_subscription_past_due(tenant_db):
    org = tenant_service.create_organization(
        "Manual Billing",
        "manual-billing",
        "admin@billing.test",
        _claims(),
    )
    plan = tenant_service.create_subscription_plan(
        {
            "name": "KES Growth",
            "slug": "kes-growth",
            "monthly_price_cents": 1490000,
            "currency_code": "KES",
            "market_code": "KE",
            "trial_days": 0,
            "active": True,
        },
        _claims(),
    )
    tenant_service.select_organization_plan(org["id"], plan["id"], _claims())
    subscription = tenant_service.update_organization_subscription(
        org["id"],
        {"status": "PAST_DUE"},
        _claims(),
    )

    assert subscription["status"] == "PAST_DUE"
    assert subscription["is_active"] is False
    assert subscription["plan"]["currency_code"] == "KES"
    assert subscription["plan"]["market_code"] == "KE"
    with pytest.raises(PermissionError):
        tenant_service.require_active_subscription(org["id"])


def test_plan_default_routing_wins_when_campaign_mode_is_unset(tenant_db):
    org = tenant_service.create_organization(
        "Routing Buyer",
        "routing-buyer",
        "admin@routing.test",
        _claims(),
    )
    plan = tenant_service.create_subscription_plan(
        {
            "name": "Growth",
            "slug": "growth-routing",
            "trial_days": 0,
            "allowed_llm_routing_modes": ["cost_optimized", "balanced", "quality_first"],
            "default_llm_routing_mode": "balanced",
            "active": True,
        },
        _claims(),
    )
    tenant_service.select_organization_plan(org["id"], plan["id"], _claims())
    tenant_service.update_organization_subscription(org["id"], {"status": "ACTIVE"}, _claims())

    policy = tenant_service.resolve_allowed_llm_routing_mode(
        org["id"],
        None,
        fallback_mode="quality_first",
    )

    assert policy["requested_mode"] is None
    assert policy["default_mode"] == "balanced"
    assert policy["resolved_mode"] == "balanced"
    assert policy["downgraded"] is False


def test_starter_plan_restricts_requested_quality_mode_to_cost_optimized(tenant_db):
    org = tenant_service.create_organization(
        "Starter Buyer",
        "starter-buyer",
        "admin@starter.test",
        _claims(),
    )
    plan = tenant_service.create_subscription_plan(
        {
            "name": "Starter",
            "slug": "starter-local",
            "trial_days": 0,
            "allowed_llm_routing_modes": ["cost_optimized"],
            "default_llm_routing_mode": "cost_optimized",
            "trial_allowed_llm_routing_modes": ["cost_optimized"],
            "active": True,
        },
        _claims(),
    )
    tenant_service.select_organization_plan(org["id"], plan["id"], _claims())
    tenant_service.update_organization_subscription(org["id"], {"status": "ACTIVE"}, _claims())

    policy = tenant_service.resolve_allowed_llm_routing_mode(
        org["id"],
        "quality_first",
        fallback_mode="quality_first",
    )

    assert policy["allowed_modes"] == ["cost_optimized"]
    assert policy["resolved_mode"] == "cost_optimized"
    assert policy["downgraded"] is True


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
        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout

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


def test_mailbox_test_rejects_smtp_587_with_implicit_ssl(tenant_db):
    org = tenant_service.create_organization(
        "Market Hacks",
        "market-hacks-smtp-mode",
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
            "smtp_port": 587,
            "smtp_use_ssl": True,
            "smtp_username": "info@markethacks.co.ke",
            "smtp_password": "secret",
            "imap_host": "mail.markethacks.co.ke",
            "imap_port": 993,
            "imap_username": "info@markethacks.co.ke",
            "imap_password": "secret",
        },
        admin_claims,
    )

    class FakeImap:
        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port

        def login(self, username, password):
            return None

        def select(self, mailbox, readonly=True):
            return None

        def logout(self):
            return None

    result = tenant_service.test_mailbox(org["id"], mailbox["id"], admin_claims, imap_factory=FakeImap)

    assert result["success"] is False
    assert "SMTP port 587 uses STARTTLS" in result["error"]


def test_org_admin_can_update_mailbox_without_replacing_blank_secrets(tenant_db):
    org = tenant_service.create_organization(
        "Market Hacks",
        "market-hacks-update",
        "admin@markethacks.co.ke",
        _claims(),
    )
    admin_claims = _claims(email="admin@markethacks.co.ke", sub="invited:admin@markethacks.co.ke")
    mailbox = tenant_service.create_mailbox(
        org["id"],
        {
            "provider": "smtp_imap",
            "display_name": "Old Name",
            "email_address": "info@markethacks.co.ke",
            "smtp_host": "mail.markethacks.co.ke",
            "smtp_port": 465,
            "smtp_username": "info@markethacks.co.ke",
            "smtp_password": "old-secret",
            "imap_host": "mail.markethacks.co.ke",
            "imap_port": 993,
            "imap_username": "info@markethacks.co.ke",
            "imap_password": "old-secret",
        },
        admin_claims,
    )

    updated = tenant_service.update_mailbox(
        org["id"],
        mailbox["id"],
        {
            "provider": "smtp_imap",
            "display_name": "New Name",
            "email_address": "info@markethacks.co.ke",
            "smtp_host": "mail.markethacks.co.ke",
            "smtp_port": 465,
            "smtp_use_ssl": True,
            "smtp_username": "info@markethacks.co.ke",
            "smtp_password": "",
            "imap_host": "mail.markethacks.co.ke",
            "imap_port": 993,
            "imap_use_ssl": True,
            "imap_username": "info@markethacks.co.ke",
            "imap_password": "",
            "daily_limit": 250,
        },
        admin_claims,
    )

    assert updated["display_name"] == "New Name"
    assert updated["daily_limit"] == 250
    assert updated["status"] == "PENDING"
    assert updated["has_smtp_password"] is True
    assert updated["has_imap_password"] is True

    with _connect(tenant_db) as conn:
        row = conn.execute("SELECT smtp_password_secret, imap_password_secret FROM mailbox_connections WHERE id = ?", (mailbox["id"],)).fetchone()
    assert tenant_service.decrypt_secret(row["smtp_password_secret"]) == "old-secret"
    assert tenant_service.decrypt_secret(row["imap_password_secret"]) == "old-secret"


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


def test_mailbox_provider_definitions_include_planned_oauth_providers():
    providers = {
        provider["provider"]: provider
        for provider in tenant_service.list_mailbox_provider_definitions()
    }

    assert providers["smtp_imap"]["status"] == "available"
    assert providers["smtp_imap"]["supports_reply_sync"] is True
    assert providers["resend"]["supports_webhooks"] is True
    assert providers["gmail"]["connection_type"] == "oauth"
    assert providers["gmail"]["status"] == "available"
    assert providers["microsoft"]["connection_type"] == "oauth"
    assert providers["microsoft"]["supports_sending"] is False


def test_planned_oauth_mailboxes_cannot_be_created_until_oauth_is_enabled(tenant_db):
    org = tenant_service.create_organization(
        "OAuth Tenant",
        "oauth-tenant",
        "admin@oauth.test",
        _claims(),
    )
    admin_claims = _claims(email="admin@oauth.test", sub="invited:admin@oauth.test")

    with pytest.raises(ValueError, match="must be connected with OAuth"):
        tenant_service.create_mailbox(
            org["id"],
            {
                "provider": "gmail",
                "display_name": "Gmail",
                "email_address": "admin@oauth.test",
            },
            admin_claims,
        )


def test_google_oauth_callback_creates_connected_mailbox(tenant_db, monkeypatch):
    org = tenant_service.create_organization(
        "OAuth Tenant Connected",
        "oauth-tenant-connected",
        "admin@oauth-connected.test",
        _claims(),
    )
    admin_claims = _claims(email="admin@oauth-connected.test", sub="invited:admin@oauth-connected.test")
    monkeypatch.setattr(tenant_service.settings, "google_oauth_client_id", "google-client")
    monkeypatch.setattr(tenant_service.settings, "google_oauth_client_secret", "google-secret")
    monkeypatch.setattr(mailbox_oauth_service.settings, "google_oauth_client_id", "google-client")
    monkeypatch.setattr(mailbox_oauth_service.settings, "google_oauth_client_secret", "google-secret")
    monkeypatch.setattr(mailbox_oauth_service.settings, "mailbox_oauth_state_secret", "state-secret")
    monkeypatch.setattr(
        mailbox_oauth_service,
        "_exchange_google_code",
        lambda code, redirect_uri: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "scope": "openid email https://www.googleapis.com/auth/gmail.send",
        },
    )
    monkeypatch.setattr(
        mailbox_oauth_service,
        "_fetch_google_account",
        lambda access_token: {"email": "connected@oauth.test", "name": "Connected User", "id": "google-user-id"},
    )

    started = mailbox_oauth_service.build_authorization_url(
        organization_id=org["id"],
        provider="gmail",
        data={"display_name": "Connected Gmail", "daily_limit": 123},
        actor_claims=admin_claims,
        redirect_uri="http://localhost:8000/api/mailboxes/oauth/gmail/callback",
    )
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
    mailbox = mailbox_oauth_service.complete_authorization(
        provider="gmail",
        code="oauth-code",
        state=state,
        redirect_uri="http://localhost:8000/api/mailboxes/oauth/gmail/callback",
    )

    assert mailbox["provider"] == "gmail"
    assert mailbox["status"] == "CONNECTED"
    assert mailbox["email_address"] == "connected@oauth.test"
    assert mailbox["daily_limit"] == 123
    assert mailbox["has_oauth_refresh_token"] is True
    assert "oauth_refresh_token_secret" not in mailbox
