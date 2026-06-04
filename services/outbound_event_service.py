"""Outbound integration webhooks for external systems."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
from typing import Any
from urllib.parse import urlparse

from utils.db_connection import get_conn, dict_from_row

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_allowed_target_url(target_url: str) -> bool:
    parsed = urlparse(target_url)
    if parsed.scheme not in {"https", "http"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    blocked = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    return host not in blocked and not host.endswith(".local")


def _event_matches(subscription: dict[str, Any], event_type: str) -> bool:
    configured = str(subscription.get("event_types") or "all")
    event_types = {item.strip() for item in configured.split(",") if item.strip()}
    return not event_types or "all" in event_types or event_type in event_types


def list_webhooks() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, target_url, event_types, active, created_at, updated_at "
            "FROM outbound_webhooks ORDER BY id DESC"
        ).fetchall()
    return [dict_from_row(row) for row in rows]


def create_webhook(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name") or "").strip()
    target_url = str(data.get("target_url") or "").strip()
    event_types = ",".join(data.get("event_types") or ["all"])
    secret = str(data.get("secret") or "").strip() or None
    active = 1 if data.get("active", True) else 0
    if not name:
        raise ValueError("name is required")
    if not is_allowed_target_url(target_url):
        raise ValueError("target_url must be an external http(s) URL")

    with get_conn() as conn:
        with conn:
            cur = conn.execute(
                "INSERT INTO outbound_webhooks (name, target_url, event_types, secret, active) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, target_url, event_types, secret, active),
            )
            webhook_id = cur.lastrowid
        row = conn.execute(
            "SELECT id, name, target_url, event_types, active, created_at, updated_at "
            "FROM outbound_webhooks WHERE id = ?",
            (webhook_id,),
        ).fetchone()
    return dict_from_row(row) or {}


def delete_webhook(webhook_id: int) -> bool:
    with get_conn() as conn:
        with conn:
            cur = conn.execute("DELETE FROM outbound_webhooks WHERE id = ?", (webhook_id,))
            return cur.rowcount > 0


def recent_deliveries(limit: int = 100) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, webhook_id, event_type, status, response_status, error, delivered_at, created_at "
            "FROM webhook_deliveries ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [dict_from_row(row) for row in rows]


async def emit_event(event_type: str, payload: dict[str, Any]) -> None:
    """Persist and deliver an integration event to active webhook subscriptions."""
    try:
        with get_conn() as conn:
            subscriptions = [
                dict_from_row(row)
                for row in conn.execute(
                    "SELECT id, name, target_url, event_types, secret FROM outbound_webhooks WHERE active = 1"
                ).fetchall()
            ]
            matched = [sub for sub in subscriptions if sub and _event_matches(sub, event_type)]
            if not matched:
                return

            envelope = {
                "event_type": event_type,
                "occurred_at": _now_iso(),
                "payload": payload,
            }
            body = json.dumps(envelope, sort_keys=True)
            delivery_ids: list[tuple[int, dict[str, Any]]] = []
            with conn:
                for subscription in matched:
                    cur = conn.execute(
                        "INSERT INTO webhook_deliveries (webhook_id, event_type, payload) VALUES (?, ?, ?)",
                        (subscription["id"], event_type, body),
                    )
                    delivery_ids.append((cur.lastrowid, subscription))

        if not delivery_ids:
            return

        import httpx

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            for delivery_id, subscription in delivery_ids:
                headers = {"Content-Type": "application/json", "User-Agent": "shiku-sdr-webhook/1.0"}
                if subscription.get("secret"):
                    signature = hmac.new(
                        str(subscription["secret"]).encode("utf-8"),
                        body.encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest()
                    headers["X-Shiku-Signature"] = f"sha256={signature}"
                try:
                    response = await client.post(subscription["target_url"], content=body, headers=headers)
                    status = "DELIVERED" if 200 <= response.status_code < 300 else "FAILED"
                    error = None if status == "DELIVERED" else response.text[:500]
                    with get_conn() as conn:
                        with conn:
                            conn.execute(
                                "UPDATE webhook_deliveries SET status = ?, response_status = ?, error = ?, delivered_at = ? "
                                "WHERE id = ?",
                                (status, response.status_code, error, _now_iso(), delivery_id),
                            )
                except Exception as exc:
                    with get_conn() as conn:
                        with conn:
                            conn.execute(
                                "UPDATE webhook_deliveries SET status = 'FAILED', error = ?, delivered_at = ? WHERE id = ?",
                                (str(exc), _now_iso(), delivery_id),
                            )
    except Exception as exc:
        logger.warning("Failed to emit outbound event %s: %s", event_type, exc)
