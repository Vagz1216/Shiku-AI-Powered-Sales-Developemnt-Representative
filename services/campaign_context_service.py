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

from utils.db_connection import dict_from_row, sql_bool_true, using_postgres

logger = logging.getLogger(__name__)

SUMMARY_LIMIT = 320
_SIGNOFF_WORDS = {
    "best",
    "best regards",
    "regards",
    "thanks",
    "thank you",
    "sincerely",
    "cheers",
}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_email_text(text: str | None) -> str:
    cleaned = text or ""
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"Reply with one token:.*$", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"([.!?])(?=[A-Z])", r"\1 ", cleaned)
    cleaned = re.sub(r",(?=[A-Z])", ", ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _is_context_noise(sentence: str) -> bool:
    normalized = sentence.strip(" .,!?:;").lower()
    if not normalized:
        return True
    if normalized in _SIGNOFF_WORDS:
        return True
    if len(normalized.split()) <= 3 and normalized.startswith(("hi ", "hello ", "dear ")):
        return True
    return False


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip(" \n\t") for part in parts if part.strip(" \n\t")]


def _compact_to_limit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    sentences = _sentences(text)
    kept: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*kept, sentence]).strip()
        if len(candidate) > limit:
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    truncated = text[:limit]
    boundary = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"), truncated.rfind(";"))
    if boundary >= int(limit * 0.55):
        return truncated[: boundary + 1].strip()
    return truncated.rstrip(" ,;:")


def summarize_text(text: str | None, limit: int = SUMMARY_LIMIT) -> str:
    """Create complete review context from email text without an LLM call.

    The review UI should not show a raw cut-off email fragment. For longer
    messages, keep the core opening context and the latest ask/CTA so reviewers
    can understand what happened without reading the full thread.
    """
    cleaned = _normalize_email_text(text)
    if len(cleaned) <= limit:
        return cleaned

    meaningful = [sentence for sentence in _sentences(cleaned) if not _is_context_noise(sentence)]
    if not meaningful:
        return _compact_to_limit(cleaned, limit)

    cta = next(
        (
            sentence
            for sentence in reversed(meaningful)
            if "?" in sentence
            or re.search(r"\b(book|schedule|demo|call|reply|respond|available|open to|would you)\b", sentence, re.IGNORECASE)
        ),
        None,
    )
    core = meaningful[:2]
    if cta and cta not in core:
        core.append(f"Next step: {cta}")
    summary = " ".join(core)
    if cta and len(summary) > limit:
        prioritized = " ".join([meaningful[0], f"Next step: {cta}"])
        if len(prioritized) <= limit:
            return prioritized
        cta_only = f"Next step: {cta}"
        if len(cta_only) <= limit:
            return cta_only
    return _compact_to_limit(summary, limit)


def build_draft_generation_summary(
    *,
    source: str,
    lead_name: str | None = None,
    campaign_name: str | None = None,
    emails_sent: int | None = None,
    touch_count: int | None = None,
    inbound_summary: str | None = None,
    last_outbound_summary: str | None = None,
    last_inbound_summary: str | None = None,
    intent: str | None = None,
    limit: int = SUMMARY_LIMIT,
) -> str:
    """Explain, in reviewer-facing language, what context produced a draft."""
    lead = (lead_name or "this lead").strip()
    campaign = (campaign_name or "this campaign").strip()
    parts: list[str] = []

    if source == "inbound_response":
        parts.append(f"Generated because {lead} replied in {campaign}.")
        if inbound_summary:
            parts.append(f"Latest reply: {inbound_summary}")
    else:
        stage = "follow-up" if (emails_sent or 0) > 0 or (touch_count or 0) > 0 else "cold outreach"
        parts.append(f"Generated as {stage} for {lead} in {campaign}.")
        if last_outbound_summary:
            parts.append(f"Previous outbound: {last_outbound_summary}")

    if last_inbound_summary and last_inbound_summary != inbound_summary:
        parts.append(f"Conversation memory: {last_inbound_summary}")
    if intent:
        parts.append(f"Detected intent: {str(intent).replace('_', ' ')}.")

    return _compact_to_limit(" ".join(part for part in parts if part), limit)


def _table_exists(conn) -> bool:
    try:
        if using_postgres():
            row = conn.execute(
                "SELECT to_regclass(?) AS table_name",
                ("public.campaign_lead_contexts",),
            ).fetchone()
            if not row:
                return False
            if isinstance(row, dict):
                return row.get("table_name") is not None
            return row["table_name"] is not None

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='campaign_lead_contexts'"
        ).fetchone()
        return row is not None
    except Exception:
        # If existence detection fails, let the caller's read/write attempt log a
        # non-critical context miss rather than dropping campaign processing.
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
