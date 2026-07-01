"""Draft approval and deletion business logic."""

from __future__ import annotations

import datetime
import base64
import json
import os
from typing import Any, Dict
from uuid import uuid4

from config import settings
from tools.send_email import send_plain_email
from utils.db_connection import get_conn
from utils.quick_replies import (
    clean_quick_reply_text,
    has_quick_reply_block,
    plain_text_to_basic_html,
    quick_replies_html_for_outreach,
    strip_quick_reply_block,
)
from services import campaign_context_service, outbound_event_service

MAX_DRAFT_ATTACHMENTS = 5
MAX_DRAFT_ATTACHMENT_BYTES = 5 * 1024 * 1024


def _new_approval_id(draft_id: int, actor_id: str) -> str:
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"approval:{draft_id}:{actor_id}:{stamp}:{uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _future_iso(seconds: int) -> str:
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)
    return future.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_schedule_at(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _schedule_iso(value: str | None) -> str | None:
    parsed = _parse_schedule_at(value)
    if not parsed:
        return None
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_future_schedule(value: str | None) -> bool:
    parsed = _parse_schedule_at(value)
    if not parsed:
        return False
    return parsed > datetime.datetime.now(datetime.UTC)


def _schedule_was_requested(value: str | None) -> bool:
    return bool((value or "").strip())


def _is_safety_system_unavailable(error: str | None) -> bool:
    return "Safety check system unavailable" in (error or "")


def _is_safety_content_block(error: str | None) -> bool:
    return (error or "").startswith("Safety check failed:") and not _is_safety_system_unavailable(error)


def _log_draft_event(
    conn,
    event_type: str,
    draft_id: int,
    actor_id: str,
    approval_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {"draft_id": draft_id, "actor_id": actor_id}
    if approval_id:
        payload["approval_id"] = approval_id
    if extra:
        payload.update(extra)
    organization_id = None
    try:
        row = conn.execute("SELECT organization_id FROM email_messages WHERE id = ?", (draft_id,)).fetchone()
        organization_id = row["organization_id"] if row else None
    except Exception:
        organization_id = None
    conn.execute(
        "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
        (organization_id, event_type, json.dumps(payload, sort_keys=True), None),
    )


def _pending_draft_exists(conn, draft_id: int, organization_id: int | None = None) -> bool:
    org_sql = " AND organization_id = ?" if organization_id is not None else ""
    params: tuple[Any, ...] = (draft_id, organization_id) if organization_id is not None else (draft_id,)
    row = conn.execute(
        "SELECT id FROM email_messages "
        f"WHERE id = ? AND UPPER(status) = 'DRAFT' AND approved = 0 AND direction = 'outbound'{org_sql}",
        params,
    ).fetchone()
    return row is not None


def _attachment_row(row, include_content: bool = False) -> dict[str, Any]:
    attachment = {
        "id": row["id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "size_bytes": row["size_bytes"],
        "source": row["source"],
        "created_at": row["created_at"] if "created_at" in row.keys() else None,
        "has_content": bool(row["content_base64"]),
    }
    if include_content:
        attachment["content_base64"] = row["content_base64"]
    return attachment


def list_attachments_for_messages(conn, message_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Return non-content attachment metadata keyed by message id."""
    if not message_ids:
        return {}
    placeholders = ",".join("?" for _ in message_ids)
    rows = conn.execute(
        "SELECT id, email_message_id, filename, content_type, content_base64, size_bytes, source, created_at "
        f"FROM email_attachments WHERE email_message_id IN ({placeholders}) ORDER BY id ASC",
        tuple(message_ids),
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {message_id: [] for message_id in message_ids}
    for row in rows:
        grouped.setdefault(row["email_message_id"], []).append(_attachment_row(row))
    return grouped


def get_draft_attachments(conn, draft_id: int, include_content: bool = False) -> list[dict[str, Any]]:
    """Return attachment metadata, optionally including base64 content."""
    rows = conn.execute(
        "SELECT id, filename, content_type, content_base64, size_bytes, source, created_at "
        "FROM email_attachments WHERE email_message_id = ? ORDER BY id ASC",
        (draft_id,),
    ).fetchall()
    return [_attachment_row(row, include_content=include_content) for row in rows]


def _safe_filename(filename: str) -> str:
    safe = os.path.basename((filename or "").strip()).replace("\x00", "")
    return safe[:255] or "attachment"


def _decode_attachment_content(content_base64: str) -> tuple[str, int]:
    content = (content_base64 or "").strip()
    if content.startswith("data:") and "," in content:
        content = content.split(",", 1)[1]
    try:
        raw = base64.b64decode(content, validate=True)
    except Exception as exc:
        raise ValueError("Attachment content must be valid base64.") from exc
    if len(raw) > MAX_DRAFT_ATTACHMENT_BYTES:
        raise ValueError(
            f"Attachment exceeds {MAX_DRAFT_ATTACHMENT_BYTES // (1024 * 1024)}MB limit."
        )
    return base64.b64encode(raw).decode("ascii"), len(raw)


def update_draft_content(
    draft_id: int,
    subject: str,
    body: str,
    actor_id: str,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Update the editable subject/body for a pending draft."""
    if not actor_id:
        return {"draft_id": draft_id, "status": "permission_denied", "error": "actor_id is required"}
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject or not body:
        return {"draft_id": draft_id, "status": "validation_error", "error": "subject and body are required"}

    with get_conn() as conn:
        if not _pending_draft_exists(conn, draft_id, organization_id):
            return {"draft_id": draft_id, "status": "not_found"}
        with conn:
            conn.execute(
                "UPDATE email_messages SET subject = ?, body = ? WHERE id = ?",
                (subject, body, draft_id),
            )
            _log_draft_event(conn, "draft_updated", draft_id, actor_id)
        attachments = get_draft_attachments(conn, draft_id)
    return {
        "draft_id": draft_id,
        "status": "updated",
        "subject": subject,
        "body": body,
        "attachments": attachments,
    }


def add_draft_attachments(
    draft_id: int,
    attachments: list[dict[str, Any]],
    actor_id: str,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Attach user-provided files to a pending draft."""
    if not actor_id:
        return {"draft_id": draft_id, "status": "permission_denied", "error": "actor_id is required"}
    if not attachments:
        return {"draft_id": draft_id, "status": "validation_error", "error": "attachments cannot be empty"}

    with get_conn() as conn:
        if not _pending_draft_exists(conn, draft_id, organization_id):
            return {"draft_id": draft_id, "status": "not_found"}

        existing_count = conn.execute(
            "SELECT COUNT(*) AS count FROM email_attachments WHERE email_message_id = ?",
            (draft_id,),
        ).fetchone()["count"]
        if existing_count + len(attachments) > MAX_DRAFT_ATTACHMENTS:
            return {
                "draft_id": draft_id,
                "status": "validation_error",
                "error": f"Drafts can have at most {MAX_DRAFT_ATTACHMENTS} attachments",
            }

        inserted_ids: list[int] = []
        with conn:
            for attachment in attachments:
                filename = _safe_filename(str(attachment.get("filename") or "attachment"))
                content_base64, size_bytes = _decode_attachment_content(
                    str(attachment.get("content_base64") or "")
                )
                content_type = (attachment.get("content_type") or None)
                cur = conn.execute(
                    "INSERT INTO email_attachments "
                    "(email_message_id, filename, content_type, content_base64, size_bytes, source) "
                    "VALUES (?, ?, ?, ?, ?, 'user_upload')",
                    (draft_id, filename, content_type, content_base64, size_bytes),
                )
                if cur.lastrowid is not None:
                    inserted_ids.append(cur.lastrowid)
            _log_draft_event(
                conn,
                "draft_attachments_added",
                draft_id,
                actor_id,
                extra={"attachment_count": len(attachments)},
            )
        all_attachments = get_draft_attachments(conn, draft_id)
    return {
        "draft_id": draft_id,
        "status": "attachments_added",
        "attachment_ids": inserted_ids,
        "attachments": all_attachments,
    }


def delete_draft_attachment(
    draft_id: int,
    attachment_id: int,
    actor_id: str,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Remove one attachment from a pending draft."""
    if not actor_id:
        return {"draft_id": draft_id, "status": "permission_denied", "error": "actor_id is required"}
    with get_conn() as conn:
        if not _pending_draft_exists(conn, draft_id, organization_id):
            return {"draft_id": draft_id, "status": "not_found"}
        row = conn.execute(
            "SELECT id FROM email_attachments WHERE id = ? AND email_message_id = ?",
            (attachment_id, draft_id),
        ).fetchone()
        if not row:
            return {"draft_id": draft_id, "status": "attachment_not_found"}
        with conn:
            conn.execute("DELETE FROM email_attachments WHERE id = ?", (attachment_id,))
            _log_draft_event(
                conn,
                "draft_attachment_deleted",
                draft_id,
                actor_id,
                extra={"attachment_id": attachment_id},
            )
        attachments = get_draft_attachments(conn, draft_id)
    return {"draft_id": draft_id, "status": "attachment_deleted", "attachments": attachments}


async def process_single_draft_approval(
    conn,
    draft_id: int,
    approved: bool,
    actor_id: str,
    scheduled_send_at: str | None = None,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Approve/reject one draft and return structured status."""
    cur = conn.execute(
        "SELECT e.id, e.organization_id, e.lead_id, e.subject, e.body, e.status, e.campaign_id, e.sequence_step_id, "
        "l.name as lead_name, l.email as lead_email "
        "FROM email_messages e "
        "JOIN leads l ON e.lead_id = l.id "
        "WHERE e.id = ? AND UPPER(e.status) = 'DRAFT' AND e.approved = 0 "
        + ("AND e.organization_id = ?" if organization_id is not None else ""),
        (draft_id, organization_id) if organization_id is not None else (draft_id,),
    )
    draft = cur.fetchone()
    if not draft:
        return {"draft_id": draft_id, "status": "not_found"}

    draft = dict(draft)
    draft["body"] = clean_quick_reply_text(draft["body"])
    approval_id = _new_approval_id(draft_id, actor_id)
    if approved:
        try:
            normalized_schedule = _schedule_iso(scheduled_send_at)
        except ValueError as exc:
            return {
                "draft_id": draft_id,
                "status": "validation_error",
                "error": f"Invalid scheduled send time: {exc}",
            }
        if _schedule_was_requested(scheduled_send_at):
            if not normalized_schedule:
                return {
                    "draft_id": draft_id,
                    "status": "validation_error",
                    "error": "Scheduled send time is required.",
                }
            if not _is_future_schedule(normalized_schedule):
                return {
                    "draft_id": draft_id,
                    "status": "validation_error",
                    "error": "Scheduled send time must be in the future.",
                }
            conn.execute(
                "UPDATE email_messages SET approved = 1, status = 'SCHEDULED', "
                "approved_by = ?, approved_at = ?, scheduled_send_at = ?, "
                "send_attempts = 0, last_error = NULL WHERE id = ?",
                (actor_id, _now_iso(), normalized_schedule, draft_id),
            )
            _log_draft_event(
                conn,
                "draft_approved_scheduled",
                draft_id,
                actor_id,
                approval_id,
                {"scheduled_send_at": normalized_schedule},
            )
            await outbound_event_service.emit_event(
                "draft_approved_scheduled",
                {"draft_id": draft_id, "scheduled_send_at": normalized_schedule, "lead_email": draft["lead_email"]},
            )
            return {
                "draft_id": draft_id,
                "status": "approved_scheduled",
                "approval_id": approval_id,
                "scheduled_send_at": normalized_schedule,
            }
        return await send_approved_draft(conn, draft_id, actor_id, approval_id=approval_id, organization_id=organization_id)

    conn.execute(
        "UPDATE email_messages SET approved = -1, status = 'REJECTED', approved_by = ?, approved_at = ? WHERE id = ?",
        (actor_id, _now_iso(), draft_id),
    )
    _log_draft_event(conn, "draft_rejected", draft_id, actor_id, approval_id)
    await outbound_event_service.emit_event(
        "draft_rejected",
        {"draft_id": draft_id, "lead_email": draft["lead_email"]},
    )
    return {"draft_id": draft_id, "status": "rejected", "approval_id": approval_id}


async def send_approved_draft(
    conn,
    draft_id: int,
    actor_id: str,
    approval_id: str | None = None,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Send an approved draft immediately and update message/audit state."""
    cur = conn.execute(
        "SELECT e.id, e.organization_id, e.lead_id, e.subject, e.body, e.status, e.campaign_id, e.sequence_step_id, "
        "l.name as lead_name, l.email as lead_email "
        "FROM email_messages e "
        "JOIN leads l ON e.lead_id = l.id "
        "WHERE e.id = ? AND e.direction = 'outbound' "
        "AND (UPPER(e.status) IN ('DRAFT','SCHEDULED') OR e.status IS NULL) "
        "AND e.approved IN (0, 1) "
        + ("AND e.organization_id = ?" if organization_id is not None else ""),
        (draft_id, organization_id) if organization_id is not None else (draft_id,),
    )
    draft = cur.fetchone()
    if not draft:
        return {"draft_id": draft_id, "status": "not_found"}

    draft = dict(draft)
    draft["body"] = clean_quick_reply_text(draft["body"] or "")
    approval_id = approval_id or _new_approval_id(draft_id, actor_id)

    attachments = get_draft_attachments(conn, draft_id, include_content=True)
    is_reply_draft = (draft["subject"] or "").strip().lower().startswith("re:")
    if is_reply_draft:
        body_with_qr = strip_quick_reply_block(draft["body"])
        html_body = plain_text_to_basic_html(body_with_qr)
    elif has_quick_reply_block(draft["body"]):
        body_with_qr = draft["body"]
        html_body = plain_text_to_basic_html(draft["body"])
    else:
        body_with_qr = draft["body"]
        html_body = plain_text_to_basic_html(draft["body"]) + quick_replies_html_for_outreach(
            draft["subject"],
            lead_email=draft["lead_email"],
            campaign_id=draft["campaign_id"],
            organization_id=draft["organization_id"],
        )

    conn.execute(
        "UPDATE email_messages SET send_attempts = send_attempts + 1, last_error = NULL WHERE id = ?",
        (draft_id,),
    )
    if hasattr(conn, "commit"):
        conn.commit()
    send_res = await send_plain_email(
        email=draft["lead_email"],
        name=draft["lead_name"],
        subject=draft["subject"],
        body=body_with_qr,
        html_body=html_body,
        attachments=[
            {
                "filename": attachment["filename"],
                "content_type": attachment["content_type"],
                "content_base64": attachment["content_base64"],
            }
            for attachment in attachments
            if attachment.get("content_base64")
        ],
        bypass_human_approval=True,
        organization_id=draft["organization_id"],
    )
    if send_res.ok:
        now = _now_iso()
        conn.execute(
            "UPDATE email_messages SET approved = 1, status = 'SENT', approved_by = COALESCE(approved_by, ?), "
            "approved_at = COALESCE(approved_at, ?), sent_at = ?, scheduled_send_at = NULL, "
            "external_message_id = ?, external_thread_id = ? WHERE id = ?",
            (actor_id, now, now, send_res.message_id, send_res.thread_id, draft_id),
        )
        campaign_context_service.record_outbound(
            conn,
            organization_id=draft["organization_id"],
            campaign_id=draft["campaign_id"],
            lead_id=draft["lead_id"],
            subject=draft["subject"],
            body=body_with_qr,
        )
        _log_draft_event(
            conn,
            "draft_approved_sent",
            draft_id,
            actor_id,
            approval_id,
            {
                "message_id": send_res.message_id,
                "thread_id": send_res.thread_id,
                "attachment_count": len(attachments),
            },
        )
        await outbound_event_service.emit_event(
            "email_sent",
            {
                "draft_id": draft_id,
                "lead_id": draft["lead_id"],
                "lead_email": draft["lead_email"],
                "campaign_id": draft["campaign_id"],
                "subject": draft["subject"],
                "message_id": send_res.message_id,
                "thread_id": send_res.thread_id,
            },
        )
        if draft.get("lead_id") and draft.get("campaign_id") and draft.get("sequence_step_id"):
            try:
                from services import lead_service

                lead_service.update_lead_touch(draft["lead_id"], draft["campaign_id"])
            except Exception:
                pass
        return {
            "draft_id": draft_id,
            "status": "approved_sent",
            "approval_id": approval_id,
            "message_id": send_res.message_id,
        }

    send_attempts_row = conn.execute("SELECT send_attempts FROM email_messages WHERE id = ?", (draft_id,)).fetchone()
    send_attempts = int(send_attempts_row["send_attempts"] or 0) if send_attempts_row else 0
    is_scheduled = (draft.get("status") or "").upper() == "SCHEDULED"
    if is_scheduled and _is_safety_content_block(send_res.error):
        conn.execute(
            "UPDATE email_messages SET last_error = ?, status = 'FAILED' WHERE id = ?",
            (send_res.error, draft_id),
        )
    elif is_scheduled and send_attempts >= settings.scheduled_sender_max_attempts:
        conn.execute(
            "UPDATE email_messages SET last_error = ?, status = 'DRAFT', approved = 0, approved_by = NULL, approved_at = NULL, scheduled_send_at = NULL WHERE id = ?",
            (
                f"Automatic send paused after {send_attempts} attempt(s): {send_res.error}. Review provider configuration, then approve again.",
                draft_id,
            ),
        )
    elif is_scheduled:
        conn.execute(
            "UPDATE email_messages SET last_error = ?, scheduled_send_at = ? WHERE id = ?",
            (send_res.error, _future_iso(settings.scheduled_sender_retry_delay_seconds), draft_id),
        )
    else:
        conn.execute("UPDATE email_messages SET last_error = ? WHERE id = ?", (send_res.error, draft_id))
    _log_draft_event(
        conn,
        "draft_approval_send_failed",
        draft_id,
        actor_id,
        approval_id,
        {"error": send_res.error},
    )
    return {
        "draft_id": draft_id,
        "status": "send_failed",
        "approval_id": approval_id,
        "error": send_res.error,
    }


async def send_due_scheduled_drafts(
    limit: int = 50,
    actor_id: str = "scheduler",
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Send approved scheduled drafts whose scheduled_send_at has arrived."""
    now = _now_iso()
    results: list[Dict[str, Any]] = []
    with get_conn() as conn:
        org_sql = "AND organization_id = ? " if organization_id is not None else ""
        max_attempts = settings.scheduled_sender_max_attempts
        pause_params: tuple[Any, ...] = (
            (
                f"Automatic send paused after {max_attempts} attempt(s). Review provider configuration, then approve again.",
                max_attempts,
                organization_id,
            )
            if organization_id is not None
            else (
                f"Automatic send paused after {max_attempts} attempt(s). Review provider configuration, then approve again.",
                max_attempts,
            )
        )
        conn.execute(
            "UPDATE email_messages SET status = 'DRAFT', approved = 0, approved_by = NULL, approved_at = NULL, "
            "scheduled_send_at = NULL, last_error = COALESCE(last_error, ?) "
            "WHERE direction = 'outbound' AND UPPER(status) = 'SCHEDULED' AND approved = 1 "
            "AND send_attempts >= ? "
            f"{org_sql}",
            pause_params,
        )
        params: tuple[Any, ...] = (
            (now, max_attempts, organization_id, max(1, min(limit, 200)))
            if organization_id is not None
            else (now, max_attempts, max(1, min(limit, 200)))
        )
        rows = conn.execute(
            "SELECT id FROM email_messages "
            "WHERE direction = 'outbound' AND UPPER(status) = 'SCHEDULED' AND approved = 1 "
            "AND scheduled_send_at IS NOT NULL AND scheduled_send_at <= ? "
            "AND send_attempts < ? "
            f"{org_sql}"
            "ORDER BY scheduled_send_at ASC LIMIT ?",
            params,
        ).fetchall()
        for row in rows:
            draft_id = row["id"]
            results.append(await send_approved_draft(conn, draft_id, actor_id, organization_id=organization_id))

    return {
        "status": "success",
        "processed": len(results),
        "sent": sum(1 for item in results if item.get("status") == "approved_sent"),
        "failed": sum(1 for item in results if item.get("status") == "send_failed"),
        "results": results,
    }


def update_scheduled_draft(
    draft_id: int,
    subject: str,
    body: str,
    scheduled_send_at: str,
    actor_id: str,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Edit an approved scheduled email before it is sent."""
    if not actor_id:
        return {"draft_id": draft_id, "status": "permission_denied", "error": "actor_id is required"}
    subject = (subject or "").strip()
    body = (body or "").strip()
    scheduled_at = _schedule_iso(scheduled_send_at)
    if not subject or not body or not scheduled_at:
        return {
            "draft_id": draft_id,
            "status": "validation_error",
            "error": "subject, body, and scheduled_send_at are required",
        }

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM email_messages "
            "WHERE id = ? AND direction = 'outbound' AND UPPER(status) = 'SCHEDULED' AND approved = 1 "
            + ("AND organization_id = ?" if organization_id is not None else ""),
            (draft_id, organization_id) if organization_id is not None else (draft_id,),
        ).fetchone()
        if not row:
            return {"draft_id": draft_id, "status": "not_found"}
        with conn:
            conn.execute(
                "UPDATE email_messages SET subject = ?, body = ?, scheduled_send_at = ?, last_error = NULL WHERE id = ?",
                (subject, body, scheduled_at, draft_id),
            )
            _log_draft_event(
                conn,
                "scheduled_draft_updated",
                draft_id,
                actor_id,
                extra={"scheduled_send_at": scheduled_at},
            )
    return {
        "draft_id": draft_id,
        "status": "updated",
        "subject": subject,
        "body": body,
        "scheduled_send_at": scheduled_at,
    }


def return_scheduled_draft_to_review(draft_id: int, actor_id: str, organization_id: int | None = None) -> Dict[str, Any]:
    """Move a scheduled email back to pending draft review."""
    if not actor_id:
        return {"draft_id": draft_id, "status": "permission_denied", "error": "actor_id is required"}
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM email_messages "
            "WHERE id = ? AND direction = 'outbound' AND UPPER(status) = 'SCHEDULED' AND approved = 1 "
            + ("AND organization_id = ?" if organization_id is not None else ""),
            (draft_id, organization_id) if organization_id is not None else (draft_id,),
        ).fetchone()
        if not row:
            return {"draft_id": draft_id, "status": "not_found"}
        with conn:
            conn.execute(
                "UPDATE email_messages SET status = 'DRAFT', approved = 0, approved_by = NULL, approved_at = NULL, "
                "scheduled_send_at = NULL, last_error = NULL WHERE id = ?",
                (draft_id,),
            )
            _log_draft_event(conn, "scheduled_draft_returned_to_review", draft_id, actor_id)
    return {"draft_id": draft_id, "status": "returned_to_review"}


async def approve_draft(
    draft_id: int,
    approved: bool,
    actor_id: str,
    scheduled_send_at: str | None = None,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Approve or reject a pending draft using the authenticated actor as approval artifact."""
    if not actor_id:
        return {"draft_id": draft_id, "status": "permission_denied", "error": "actor_id is required"}
    with get_conn() as conn:
        return await process_single_draft_approval(conn, draft_id, approved, actor_id, scheduled_send_at, organization_id)


async def batch_approve_drafts(
    draft_ids: list[int],
    approved: bool,
    actor_id: str,
    scheduled_send_at: str | None = None,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Approve or reject many drafts in one call."""
    if not actor_id:
        return {"status": "permission_denied", "error": "actor_id is required"}
    ids = sorted(set(draft_ids))
    if not ids:
        return {"status": "validation_error", "error": "draft_ids cannot be empty"}

    results: list[Dict[str, Any]] = []
    with get_conn() as conn:
        for draft_id in ids:
            results.append(await process_single_draft_approval(conn, draft_id, approved, actor_id, scheduled_send_at, organization_id))

    summary = {
        "requested": len(ids),
        "approved_sent": sum(1 for r in results if r["status"] == "approved_sent"),
        "approved_scheduled": sum(1 for r in results if r["status"] == "approved_scheduled"),
        "rejected": sum(1 for r in results if r["status"] == "rejected"),
        "not_found": sum(1 for r in results if r["status"] == "not_found"),
        "send_failed": sum(1 for r in results if r["status"] == "send_failed"),
    }
    return {"status": "success", "summary": summary, "results": results}


def stop_future_attempts_for_draft(conn, lead_id: int, campaign_id: int) -> None:
    """Mark campaign lead as fully attempted so outreach won't generate another draft."""
    conn.execute(
        "UPDATE campaign_leads "
        "SET emails_sent = COALESCE((SELECT max_emails_per_lead FROM campaigns WHERE id = ?), emails_sent) "
        "WHERE campaign_id = ? AND lead_id = ?",
        (campaign_id, campaign_id, lead_id),
    )


def process_single_draft_delete(
    conn,
    draft_id: int,
    stop_future_attempts: bool,
    actor_id: str,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Delete one pending draft and optionally stop future attempts for that lead/campaign."""
    cur = conn.execute(
        "SELECT id, lead_id, campaign_id FROM email_messages "
        "WHERE id = ? AND UPPER(status) = 'DRAFT' AND approved = 0 AND direction = 'outbound' "
        + ("AND organization_id = ?" if organization_id is not None else ""),
        (draft_id, organization_id) if organization_id is not None else (draft_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"draft_id": draft_id, "status": "not_found"}

    lead_id = row["lead_id"]
    campaign_id = row["campaign_id"]
    conn.execute("DELETE FROM email_messages WHERE id = ?", (draft_id,))
    if stop_future_attempts and lead_id and campaign_id:
        stop_future_attempts_for_draft(conn, lead_id, campaign_id)
    _log_draft_event(
        conn,
        "draft_deleted",
        draft_id,
        actor_id,
        extra={"stop_future_attempts": stop_future_attempts},
    )
    return {"draft_id": draft_id, "status": "deleted", "stop_future_attempts": stop_future_attempts}


def delete_draft(draft_id: int, stop_future_attempts: bool, actor_id: str, organization_id: int | None = None) -> Dict[str, Any]:
    """Delete one pending draft."""
    if not actor_id:
        return {"draft_id": draft_id, "status": "permission_denied", "error": "actor_id is required"}
    with get_conn() as conn:
        return process_single_draft_delete(conn, draft_id, stop_future_attempts, actor_id, organization_id)


def batch_delete_drafts(
    draft_ids: list[int],
    stop_future_attempts: bool,
    actor_id: str,
    organization_id: int | None = None,
) -> Dict[str, Any]:
    """Delete many pending drafts."""
    if not actor_id:
        return {"status": "permission_denied", "error": "actor_id is required"}
    ids = sorted(set(draft_ids))
    if not ids:
        return {"status": "validation_error", "error": "draft_ids cannot be empty"}

    results: list[Dict[str, Any]] = []
    with get_conn() as conn:
        for draft_id in ids:
            results.append(process_single_draft_delete(conn, draft_id, stop_future_attempts, actor_id, organization_id))

    summary = {
        "requested": len(ids),
        "deleted": sum(1 for r in results if r["status"] == "deleted"),
        "not_found": sum(1 for r in results if r["status"] == "not_found"),
    }
    return {"status": "success", "summary": summary, "results": results}
