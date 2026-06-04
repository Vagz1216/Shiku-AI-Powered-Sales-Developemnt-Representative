import sqlite3

import pytest

from services import metering_service, tenant_service, usage_service


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def metering_db(tmp_path, monkeypatch):
    db_path = tmp_path / "metering.sqlite3"
    with _connect(db_path) as conn:
        with open("db/schema.sql", "r", encoding="utf-8") as f:
            conn.executescript(f.read())

    monkeypatch.setattr(tenant_service, "get_conn", lambda: _connect(db_path))
    monkeypatch.setattr(metering_service, "get_conn", lambda: _connect(db_path))
    monkeypatch.setattr(usage_service, "get_conn", lambda: _connect(db_path))
    monkeypatch.setattr(tenant_service.settings, "platform_owner_emails", "owner@example.com")
    monkeypatch.setattr(tenant_service.settings, "mailbox_encryption_key", None)
    return db_path


def _claims(email="owner@example.com", sub="user_owner"):
    return {"sub": sub, "email": email, "name": "Owner"}


def test_customer_usage_summary_counts_actions_platform_events_and_cost(metering_db):
    org = tenant_service.create_organization("Usage Org", "usage-org", "admin@usage.test", _claims())
    plan = tenant_service.create_subscription_plan(
        {
            "name": "Growth",
            "slug": "growth",
            "trial_days": 0,
            "max_monthly_ai_credits": 100,
            "max_monthly_emails": 1000,
            "overage_allowed": True,
            "overage_price_cents_per_ai_credit": 2,
            "active": True,
        },
        _claims(),
    )
    tenant_service.select_organization_plan(
        org["id"],
        plan["id"],
        _claims(email="admin@usage.test", sub="invited:admin@usage.test"),
    )

    action = metering_service.record_ai_usage_action(
        organization_id=org["id"],
        action_type="draft_generated",
        credits_used=5,
    )
    metering_service.record_platform_usage_event(
        organization_id=org["id"],
        event_type="email_sent",
        quantity=2,
    )
    usage_service.record_llm_usage(
        organization_id=org["id"],
        ai_usage_action_id=action["id"],
        request_id="req_test",
        agent_name="DrafterAgent",
        provider="OpenAI",
        model="gpt-4o-mini",
        usage=usage_service.TokenUsage(input_tokens=1000, output_tokens=500, total_tokens=1500),
        latency_ms=123,
        fallback_triggered=False,
        attempt_count=1,
        tool_call_count=0,
    )

    summary = metering_service.get_customer_usage_summary(org["id"])

    assert summary["ai"]["credits_used"] == 5
    assert summary["ai"]["included_credits"] == 100
    assert summary["ai"]["remaining_credits"] == 95
    assert summary["by_action"][0]["action_type"] == "draft_generated"
    assert summary["platform_by_event"][0]["event_type"] == "email_sent"
    assert summary["platform_by_event"][0]["quantity"] == 2
    assert summary["internal_cost"]["estimated_cost_usd"] == 0.00045

    unit_economics = metering_service.get_action_unit_economics(org["id"])
    draft_row = unit_economics["by_action"][0]
    assert draft_row["action_type"] == "draft_generated"
    assert draft_row["avg_cost_per_action_usd"] == 0.00045
    assert draft_row["cost_per_credit_usd"] == 0.00009


def test_ai_usage_action_context_links_current_action(metering_db):
    org = tenant_service.create_organization("Context Org", "context-org", "admin@context.test", _claims())
    plan = tenant_service.create_subscription_plan(
        {"name": "Starter", "slug": "starter", "trial_days": 0, "active": True},
        _claims(),
    )
    tenant_service.select_organization_plan(
        org["id"],
        plan["id"],
        _claims(email="admin@context.test", sub="invited:admin@context.test"),
    )

    with metering_service.ai_usage_action_context(
        organization_id=org["id"],
        action_type="outreach_email_generation",
        credits_used=6,
    ) as action:
        assert metering_service.get_current_ai_action_id() == action["id"]

    assert metering_service.get_current_ai_action_id() is None
