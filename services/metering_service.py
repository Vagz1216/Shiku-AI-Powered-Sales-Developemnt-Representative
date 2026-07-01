"""Customer-facing usage metering and internal cost-allocation helpers."""

from __future__ import annotations

import datetime
import json
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from config.logging import get_request_id
from services import tenant_service
from utils.db_connection import dict_from_row, get_conn


_current_user_id: ContextVar[int | None] = ContextVar("usage_user_id", default=None)
_current_organization_id: ContextVar[int | None] = ContextVar("usage_organization_id", default=None)
_current_ai_action_id: ContextVar[int | None] = ContextVar("ai_usage_action_id", default=None)


AGENT_ACTION_CREDITS = {
    "DrafterAgent": ("draft_generated", 5),
    "ReviewerAgent": ("draft_reviewed", 1),
    "LlamaGuardAgent": ("safety_checked", 1),
    "IntentExtractor": ("reply_classified", 1),
    "EmailIntentExtractor": ("reply_classified", 1),
    "EmailResponseAgent": ("reply_generated", 3),
    "EmailResponseEvaluator": ("reply_reviewed", 1),
    "EmailSenderAgent": ("reply_action_executed", 2),
    "MeetingDetailsAgent": ("meeting_assist", 2),
    "CalendarAgent": ("meeting_assist", 2),
}

ROUTING_MODE_CREDIT_MULTIPLIERS = {
    "cost_optimized": 1,
    "balanced": 2,
    "quality_first": 4,
}


def set_current_user_id(user_id: int | None):
    return _current_user_id.set(int(user_id) if user_id else None)


def get_current_user_id() -> int | None:
    return _current_user_id.get()


def reset_current_user_id(token) -> None:
    _current_user_id.reset(token)


def set_current_organization_id(organization_id: int | None):
    return _current_organization_id.set(int(organization_id) if organization_id else None)


def get_current_organization_id() -> int | None:
    return _current_organization_id.get()


def reset_current_organization_id(token) -> None:
    _current_organization_id.reset(token)


def set_current_ai_action_id(action_id: int | None):
    return _current_ai_action_id.set(int(action_id) if action_id else None)


def get_current_ai_action_id() -> int | None:
    return _current_ai_action_id.get()


def reset_current_ai_action_id(token) -> None:
    _current_ai_action_id.reset(token)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0)


def _dt(value: Any) -> datetime.datetime | None:
    return tenant_service.parse_iso(value)


def _db_time(value: datetime.datetime) -> str:
    return value.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")


def _fallback_period() -> tuple[str, str]:
    now = _now()
    start = now.replace(day=1, hour=0, minute=0, second=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return _db_time(start), _db_time(end)


def resolve_billing_period(organization_id: int) -> dict[str, Any]:
    """Return a stable billing-period snapshot shape for metering rows."""
    subscription = tenant_service.get_organization_subscription(organization_id)
    plan = subscription.get("plan") or {}
    start = _dt(subscription.get("current_period_started_at"))
    end = _dt(subscription.get("current_period_ends_at"))
    if not start or not end:
        period_start, period_end = _fallback_period()
    else:
        period_start, period_end = _db_time(start), _db_time(end)
    return {
        "subscription_id": subscription.get("id"),
        "plan_id": plan.get("id"),
        "period_start": period_start,
        "period_end": period_end,
        "included_ai_credits": plan.get("max_monthly_ai_credits"),
        "included_emails": plan.get("max_monthly_emails"),
        "included_users": plan.get("max_users"),
        "included_leads": plan.get("max_leads"),
        "overage_allowed": bool(plan.get("overage_allowed")),
        "overage_price_cents_per_ai_credit": plan.get("overage_price_cents_per_ai_credit"),
    }


def ensure_billing_period_snapshot(organization_id: int) -> dict[str, Any]:
    period = resolve_billing_period(organization_id)
    with get_conn() as conn:
        with conn:
            existing = conn.execute(
                "SELECT id FROM organization_billing_periods "
                "WHERE organization_id = ? AND period_start = ? AND period_end = ?",
                (organization_id, period["period_start"], period["period_end"]),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE organization_billing_periods SET subscription_id = ?, plan_id = ?, "
                    "included_ai_credits = ?, included_emails = ?, included_users = ?, included_leads = ?, "
                    "overage_allowed = ?, overage_price_cents_per_ai_credit = ?, updated_at = ? "
                    "WHERE organization_id = ? AND period_start = ? AND period_end = ?",
                    (
                        period["subscription_id"],
                        period["plan_id"],
                        period["included_ai_credits"],
                        period["included_emails"],
                        period["included_users"],
                        period["included_leads"],
                        int(period["overage_allowed"]),
                        period["overage_price_cents_per_ai_credit"],
                        _db_time(_now()),
                        organization_id,
                        period["period_start"],
                        period["period_end"],
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO organization_billing_periods ("
                    "organization_id, subscription_id, plan_id, period_start, period_end, "
                    "included_ai_credits, included_emails, included_users, included_leads, "
                    "overage_allowed, overage_price_cents_per_ai_credit, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        organization_id,
                        period["subscription_id"],
                        period["plan_id"],
                        period["period_start"],
                        period["period_end"],
                        period["included_ai_credits"],
                        period["included_emails"],
                        period["included_users"],
                        period["included_leads"],
                        int(period["overage_allowed"]),
                        period["overage_price_cents_per_ai_credit"],
                        _db_time(_now()),
                    ),
                )
    return period


def action_defaults_for_agent(agent_name: str) -> tuple[str, int]:
    return AGENT_ACTION_CREDITS.get(agent_name, ("llm_agent_call", 1))


def credits_for_routing_mode(base_credits: int, routing_mode: str | None) -> int:
    multiplier = ROUTING_MODE_CREDIT_MULTIPLIERS.get(str(routing_mode or "").strip(), 1)
    return max(int(base_credits), 0) * multiplier


def record_ai_usage_action(
    *,
    organization_id: int,
    action_type: str,
    user_id: int | None = None,
    quantity: int = 1,
    credits_used: int | None = None,
    source_object_type: str | None = None,
    source_object_id: str | int | None = None,
    status: str = "success",
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    period = ensure_billing_period_snapshot(organization_id)
    resolved_user_id = user_id if user_id is not None else get_current_user_id()
    resolved_credits = max(int(credits_used if credits_used is not None else quantity), 0)
    metadata_json = json.dumps(metadata or {}, sort_keys=True) if metadata else None
    source_id = str(source_object_id) if source_object_id is not None else None

    with get_conn() as conn:
        if idempotency_key:
            existing = conn.execute(
                "SELECT * FROM ai_usage_actions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return dict_from_row(existing) or {}
        with conn:
            cur = conn.execute(
                "INSERT INTO ai_usage_actions ("
                "organization_id, user_id, request_id, action_type, quantity, credits_used, "
                "billing_period_start, billing_period_end, source_object_type, source_object_id, "
                "status, idempotency_key, metadata"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    organization_id,
                    resolved_user_id,
                    request_id or get_request_id(),
                    action_type,
                    max(int(quantity), 1),
                    resolved_credits,
                    period["period_start"],
                    period["period_end"],
                    source_object_type,
                    source_id,
                    status,
                    idempotency_key,
                    metadata_json,
                ),
            )
            action_id = cur.lastrowid
        row = conn.execute("SELECT * FROM ai_usage_actions WHERE id = ?", (action_id,)).fetchone()
    return dict_from_row(row) or {"id": action_id}


def update_ai_usage_action(
    action_id: int | None,
    *,
    action_type: str | None = None,
    credits_used: int | None = None,
    status: str | None = None,
    metadata_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not action_id:
        return {}
    with get_conn() as conn:
        existing = dict_from_row(
            conn.execute("SELECT * FROM ai_usage_actions WHERE id = ?", (action_id,)).fetchone()
        )
        if not existing:
            return {}
        fields: dict[str, Any] = {}
        if action_type is not None:
            fields["action_type"] = action_type
        if credits_used is not None:
            fields["credits_used"] = max(int(credits_used), 0)
        if status is not None:
            fields["status"] = status
        if metadata_patch:
            try:
                current_metadata = json.loads(existing.get("metadata") or "{}")
            except json.JSONDecodeError:
                current_metadata = {}
            merged = deepcopy(current_metadata)
            merged.update(metadata_patch)
            fields["metadata"] = json.dumps(merged, sort_keys=True)
        if fields:
            assignments = ", ".join(f"{field} = ?" for field in fields)
            params = [*fields.values(), action_id]
            with conn:
                conn.execute(f"UPDATE ai_usage_actions SET {assignments} WHERE id = ?", tuple(params))
        row = conn.execute("SELECT * FROM ai_usage_actions WHERE id = ?", (action_id,)).fetchone()
    return dict_from_row(row) or {}


@contextmanager
def ai_usage_action_context(
    *,
    organization_id: int,
    action_type: str,
    user_id: int | None = None,
    quantity: int = 1,
    credits_used: int | None = None,
    source_object_type: str | None = None,
    source_object_id: str | int | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
):
    action = record_ai_usage_action(
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        action_type=action_type,
        quantity=quantity,
        credits_used=credits_used,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )
    token = set_current_ai_action_id(int(action["id"]) if action.get("id") else None)
    try:
        yield action
    except Exception as exc:
        update_ai_usage_action(
            action.get("id"),
            status="error",
            metadata_patch={"error": str(exc)},
        )
        raise
    finally:
        reset_current_ai_action_id(token)


def record_platform_usage_event(
    *,
    event_type: str,
    organization_id: int | None = None,
    user_id: int | None = None,
    quantity: int = 1,
    source_object_type: str | None = None,
    source_object_id: str | int | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_user_id = user_id if user_id is not None else get_current_user_id()
    metadata_json = json.dumps(metadata or {}, sort_keys=True) if metadata else None
    source_id = str(source_object_id) if source_object_id is not None else None
    with get_conn() as conn:
        if idempotency_key:
            existing = conn.execute(
                "SELECT * FROM platform_usage_events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return dict_from_row(existing) or {}
        with conn:
            cur = conn.execute(
                "INSERT INTO platform_usage_events ("
                "organization_id, user_id, event_type, quantity, source_object_type, "
                "source_object_id, idempotency_key, metadata"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    organization_id,
                    resolved_user_id,
                    event_type,
                    max(int(quantity), 1),
                    source_object_type,
                    source_id,
                    idempotency_key,
                    metadata_json,
                ),
            )
            event_id = cur.lastrowid
        row = conn.execute("SELECT * FROM platform_usage_events WHERE id = ?", (event_id,)).fetchone()
    return dict_from_row(row) or {"id": event_id}


def add_platform_cost_allocation(
    *,
    period_start: str,
    period_end: str,
    category: str,
    total_cost_usd: float,
    provider: str | None = None,
    allocation_method: str = "manual",
    notes: str | None = None,
) -> dict[str, Any]:
    with get_conn() as conn:
        with conn:
            cur = conn.execute(
                "INSERT INTO platform_cost_allocations ("
                "period_start, period_end, category, provider, total_cost_usd, allocation_method, notes"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    period_start,
                    period_end,
                    category,
                    provider,
                    float(total_cost_usd),
                    allocation_method,
                    notes,
                ),
            )
            allocation_id = cur.lastrowid
        row = conn.execute("SELECT * FROM platform_cost_allocations WHERE id = ?", (allocation_id,)).fetchone()
    return dict_from_row(row) or {"id": allocation_id}


def get_customer_usage_summary(organization_id: int) -> dict[str, Any]:
    period = ensure_billing_period_snapshot(organization_id)
    params = (organization_id, period["period_start"], period["period_end"])
    with get_conn() as conn:
        ai_total = dict_from_row(
            conn.execute(
                "SELECT COUNT(*) AS action_count, COALESCE(SUM(quantity), 0) AS quantity, "
                "COALESCE(SUM(credits_used), 0) AS credits_used "
                "FROM ai_usage_actions "
                "WHERE organization_id = ? AND billing_period_start = ? AND billing_period_end = ? "
                "AND status = 'success'",
                params,
            ).fetchone()
        ) or {}
        by_action = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT action_type, COUNT(*) AS action_count, COALESCE(SUM(quantity), 0) AS quantity, "
                "COALESCE(SUM(credits_used), 0) AS credits_used "
                "FROM ai_usage_actions "
                "WHERE organization_id = ? AND billing_period_start = ? AND billing_period_end = ? "
                "AND status = 'success' GROUP BY action_type ORDER BY credits_used DESC, action_count DESC",
                params,
            ).fetchall()
        ]
        platform_by_event = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT event_type, COUNT(*) AS event_count, COALESCE(SUM(quantity), 0) AS quantity "
                "FROM platform_usage_events "
                "WHERE organization_id = ? AND created_at >= ? AND created_at < ? "
                "GROUP BY event_type ORDER BY quantity DESC, event_count DESC",
                params,
            ).fetchall()
        ]
        llm_cost = dict_from_row(
            conn.execute(
                "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd, "
                "COALESCE(SUM(total_tokens), 0) AS total_tokens, COUNT(*) AS call_count "
                "FROM llm_usage_events WHERE organization_id = ? AND created_at >= ? AND created_at < ?",
                params,
            ).fetchone()
        ) or {}
    included = period.get("included_ai_credits")
    used = int(ai_total.get("credits_used") or 0)
    remaining = None if included is None else max(int(included) - used, 0)
    return {
        "period": period,
        "ai": {
            **ai_total,
            "included_credits": included,
            "remaining_credits": remaining,
            "overage_credits": 0 if included is None else max(used - int(included), 0),
        },
        "by_action": by_action,
        "platform_by_event": platform_by_event,
        "internal_cost": llm_cost,
    }


def get_owner_margin_summary(organization_id: int | None = None) -> dict[str, Any]:
    where = "WHERE organization_id = ?" if organization_id is not None else ""
    params: tuple[Any, ...] = (organization_id,) if organization_id is not None else ()
    with get_conn() as conn:
        ai = dict_from_row(
            conn.execute(
                "SELECT COUNT(*) AS action_count, COALESCE(SUM(credits_used), 0) AS credits_used "
                f"FROM ai_usage_actions {where}",
                params,
            ).fetchone()
        ) or {}
        llm = dict_from_row(
            conn.execute(
                "SELECT COUNT(*) AS call_count, COALESCE(SUM(total_tokens), 0) AS total_tokens, "
                "COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd "
                f"FROM llm_usage_events {where}",
                params,
            ).fetchone()
        ) or {}
        by_org = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT l.organization_id, COUNT(*) AS llm_calls, COALESCE(SUM(l.total_tokens), 0) AS total_tokens, "
                "COALESCE(SUM(l.estimated_cost_usd), 0) AS estimated_cost_usd, "
                "COALESCE((SELECT SUM(a.credits_used) FROM ai_usage_actions a "
                "WHERE a.organization_id = l.organization_id AND a.status = 'success'), 0) AS linked_credits "
                "FROM llm_usage_events l "
                "GROUP BY l.organization_id ORDER BY estimated_cost_usd DESC"
            ).fetchall()
        ] if organization_id is None else []
    return {"ai": ai, "llm": llm, "by_org": by_org}


def get_action_unit_economics(organization_id: int | None = None) -> dict[str, Any]:
    """Aggregate product actions with linked LLM cost for pricing/margin modeling."""
    where = "WHERE a.organization_id = ?" if organization_id is not None else ""
    params: tuple[Any, ...] = (organization_id,) if organization_id is not None else ()
    with get_conn() as conn:
        rows = [
            dict_from_row(row) or {}
            for row in conn.execute(
                "SELECT a.id, a.organization_id, a.action_type, a.credits_used, "
                "COALESCE(SUM(l.estimated_cost_usd), 0) AS estimated_cost_usd, "
                "COALESCE(SUM(l.total_tokens), 0) AS total_tokens, COUNT(l.id) AS llm_calls "
                "FROM ai_usage_actions a "
                "LEFT JOIN llm_usage_events l ON l.ai_usage_action_id = a.id "
                f"{where} "
                "GROUP BY a.id, a.organization_id, a.action_type, a.credits_used",
                params,
            ).fetchall()
        ]

    by_action: dict[str, dict[str, Any]] = {}
    for row in rows:
        action_type = str(row.get("action_type") or "unknown")
        bucket = by_action.setdefault(
            action_type,
            {
                "action_type": action_type,
                "action_count": 0,
                "credits_used": 0,
                "estimated_cost_usd": 0.0,
                "total_tokens": 0,
                "llm_calls": 0,
            },
        )
        bucket["action_count"] += 1
        bucket["credits_used"] += int(row.get("credits_used") or 0)
        bucket["estimated_cost_usd"] += float(row.get("estimated_cost_usd") or 0)
        bucket["total_tokens"] += int(row.get("total_tokens") or 0)
        bucket["llm_calls"] += int(row.get("llm_calls") or 0)

    results = []
    for bucket in by_action.values():
        action_count = max(bucket["action_count"], 1)
        credits = max(bucket["credits_used"], 1)
        bucket["avg_cost_per_action_usd"] = round(bucket["estimated_cost_usd"] / action_count, 8)
        bucket["avg_tokens_per_action"] = round(bucket["total_tokens"] / action_count, 2)
        bucket["avg_llm_calls_per_action"] = round(bucket["llm_calls"] / action_count, 2)
        bucket["cost_per_credit_usd"] = round(bucket["estimated_cost_usd"] / credits, 8)
        bucket["estimated_cost_usd"] = round(bucket["estimated_cost_usd"], 8)
        results.append(bucket)

    results.sort(key=lambda item: (item["estimated_cost_usd"], item["action_count"]), reverse=True)
    return {"by_action": results}
