"""Per-lead campaign conversation context.

The goal is not to replace full thread history. It is a cheap durable memory
that lets deterministic follow-ups and dashboards understand what recently
happened without re-reading every email or spending LLM tokens.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

from utils.db_connection import dict_from_row, sql_bool_true

logger = logging.getLogger(__name__)

SUMMARY_LIMIT = 320


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def summarize_text(text: str | None, limit: int = SUMMARY_LIMIT) -> str:
    """Create a compact deterministic summary from email text.

    This intentionally avoids an LLM call. It keeps the first meaningful
    sentence-ish chunk and strips whitespace/quick-reply noise.
    """
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    cleaned = re.sub(r"Reply with one token:.*$", "", cleaned, flags=re.IGNORECASE).strip()
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[:limit]
    boundary = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"), truncated.rfind(";"))
    if boundary >= int(limit * 0.55):
        return truncated[: boundary + 1].strip()
    return truncated.rstrip(" ,;:") + "..."


def _table_exists(conn) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_lead_contexts'"
        ).fetchone()
        return row is not None
    except Exception:
        # Aurora/Postgres does not have sqlite_master. If the table is missing,
        # the write below will fail and be logged as a non-critical context miss.
        return True


def get_context(conn, campaign_id: int | None, lead_id: int | None) -> dict[str, Any]:
    if not campaign_id or not lead_id:
        return {}
    if not _table_exists(conn):
        return {}
    try:
        row = conn.execute(
            "SELECT last_outbound_subject, last_outbound_summary, last_inbound_subject, "
            "last_inbound_summary, latest_intent, updated_at "
            "FROM campaign_lead_contexts WHERE campaign_id = ? AND lead_id = ?",
            (campaign_id, lead_id),
        ).fetchone()
        return dict_from_row(row) or {}
    except Exception as exc:
        logger.debug("Could not read campaign context for campaign=%s lead=%s: %s", campaign_id, lead_id, exc)
        return {}


def format_context_for_followup(context: dict[str, Any]) -> str:
    parts: list[str] = []
    if context.get("last_outbound_summary"):
        parts.append(f"Last outbound: {context['last_outbound_summary']}")
    if context.get("last_inbound_summary"):
        parts.append(f"Last inbound: {context['last_inbound_summary']}")
    if context.get("latest_intent"):
        parts.append(f"Latest intent: {context['latest_intent']}")
    return " | ".join(parts)


def record_outbound(
    conn,
    *,
    organization_id: int | None,
    campaign_id: int | None,
    lead_id: int | None,
    subject: str | None,
    body: str | None,
) -> None:
    """Remember the latest outbound campaign message for this lead."""
    if not campaign_id or not lead_id:
        return
    summary = summarize_text(body)
    if not summary:
        return
    if not _table_exists(conn):
        return
    try:
        conn.execute(
            "INSERT INTO campaign_lead_contexts "
            "(organization_id, campaign_id, lead_id, last_outbound_subject, last_outbound_summary, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, lead_id) DO UPDATE SET "
            "organization_id = excluded.organization_id, "
            "last_outbound_subject = excluded.last_outbound_subject, "
            "last_outbound_summary = excluded.last_outbound_summary, "
            "updated_at = excluded.updated_at",
            (organization_id or 1, campaign_id, lead_id, subject, summary, _now_iso()),
        )
    except Exception as exc:
        logger.debug("Could not record outbound campaign context: %s", exc)


def record_inbound(
    conn,
    *,
    organization_id: int | None,
    campaign_id: int | None,
    lead_id: int | None,
    subject: str | None,
    body: str | None,
    intent: str | None,
) -> None:
    """Remember latest inbound context and update campaign stop flags."""
    if not campaign_id or not lead_id:
        return

    normalized_intent = (intent or "").strip().lower()
    try:
        if normalized_intent not in {"bounce", "spam"}:
            conn.execute(
                f"UPDATE campaign_leads SET responded = {sql_bool_true()} WHERE campaign_id = ? AND lead_id = ?",
                (campaign_id, lead_id),
            )
        if normalized_intent == "meeting_confirmation":
            conn.execute(
                f"UPDATE campaign_leads SET meeting_booked = {sql_bool_true()} WHERE campaign_id = ? AND lead_id = ?",
                (campaign_id, lead_id),
            )
    except Exception as exc:
        logger.debug("Could not update campaign response flags: %s", exc)

    summary = summarize_text(body)
    if not summary or not _table_exists(conn):
        return
    try:
        conn.execute(
            "INSERT INTO campaign_lead_contexts "
            "(organization_id, campaign_id, lead_id, last_inbound_subject, last_inbound_summary, latest_intent, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, lead_id) DO UPDATE SET "
            "organization_id = excluded.organization_id, "
            "last_inbound_subject = excluded.last_inbound_subject, "
            "last_inbound_summary = excluded.last_inbound_summary, "
            "latest_intent = excluded.latest_intent, "
            "updated_at = excluded.updated_at",
            (organization_id or 1, campaign_id, lead_id, subject, summary, normalized_intent or None, _now_iso()),
        )
    except Exception as exc:
        logger.debug("Could not record inbound campaign context: %s", exc)
