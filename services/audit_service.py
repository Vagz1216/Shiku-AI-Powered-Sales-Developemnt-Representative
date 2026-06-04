"""Read-only compliance and audit views."""

from __future__ import annotations

import json
from typing import Any

from config import settings
from utils.db_connection import dict_from_row, get_conn


def _parse_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def list_events(
    limit: int = 100,
    event_type: str | None = None,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    filters: list[str] = []
    if event_type:
        filters.append("type = ?")
        params.append(event_type)
    if organization_id is not None:
        filters.append("organization_id = ?")
        params.append(organization_id)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(max(1, min(limit, 500)))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, organization_id, type, payload, metadata, created_at FROM events "
            f"{where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    events = []
    for row in rows:
        event = dict_from_row(row) or {}
        event["payload"] = _parse_json(event.get("payload"))
        event["metadata"] = _parse_json(event.get("metadata"))
        events.append(event)
    return events


def list_log_streams() -> list[dict[str, Any]]:
    """Return a compliance-oriented map of available operational streams."""
    return [
        {
            "name": "Application JSON Logs",
            "storage": settings.log_file,
            "access": "system_owner / infrastructure operator",
            "contains": [
                "request_id",
                "timestamp",
                "level",
                "component",
                "route lifecycle",
                "errors and exceptions",
                "provider fallback messages",
            ],
            "notes": "Rotating JSON file locally; in AWS/App Runner this should be shipped to CloudWatch.",
        },
        {
            "name": "Audit Events",
            "storage": "events table",
            "access": "system_owner in app",
            "contains": [
                "lead imports and updates",
                "draft approvals/rejections/deletes",
                "scheduled-send edits",
                "organization and mailbox admin actions",
                "follow-up draft generation",
            ],
            "notes": "Database-backed business audit trail exposed on this page.",
        },
        {
            "name": "Webhook Monitor Stream",
            "storage": "in-memory SSE while the app is running",
            "access": "authenticated users",
            "contains": [
                "incoming webhook received",
                "skip/deduplication reasons",
                "email monitor processing status",
                "short event IDs",
            ],
            "notes": "Live operational visibility only; durable outcomes should also be written to events/messages.",
        },
        {
            "name": "Outbound Webhook Deliveries",
            "storage": "webhook_deliveries table",
            "access": "system_owner via outbound webhook endpoints",
            "contains": [
                "target webhook ID",
                "event type",
                "delivery status",
                "HTTP response code",
                "delivery error",
            ],
            "notes": "Useful for CRM/Zapier/Make delivery troubleshooting.",
        },
        {
            "name": "LLM Usage Ledger",
            "storage": "llm_usage_events table",
            "access": "authenticated users through Usage page",
            "contains": [
                "agent name",
                "provider and model",
                "token counts",
                "estimated cost",
                "latency",
                "fallback attempts",
            ],
            "notes": "Cost and observability ledger; it should not contain raw prompt bodies.",
        },
    ]


def role_access_matrix() -> list[dict[str, Any]]:
    return [
        {
            "role": "system_owner",
            "scope": "Platform-wide",
            "can_access": [
                "audit events",
                "organization administration",
                "mailbox administration",
                "usage summary",
                "outbound webhook setup and deliveries",
            ],
        },
        {
            "role": "org_admin",
            "scope": "Their organization",
            "can_access": [
                "organization user management",
                "mailbox administration",
                "organization timezone",
                "campaign/lead/draft workflows",
            ],
        },
        {
            "role": "sales_manager",
            "scope": "Their organization",
            "can_access": [
                "staff/mailbox visibility",
                "campaign/lead/draft workflows",
                "usage summary",
            ],
        },
        {
            "role": "sales_user",
            "scope": "Their organization",
            "can_access": [
                "campaign/lead/draft workflows where app routes allow",
            ],
        },
        {
            "role": "viewer",
            "scope": "Their organization",
            "can_access": [
                "read-only organizational views where app routes allow",
            ],
        },
    ]
