"""Senior Marketing Orchestrator that coordinates database-driven outreach campaigns."""

import datetime
import logging
import json
from contextlib import nullcontext
from typing import Dict, Any, Optional, Callable, Awaitable

import urllib.parse
from config.logging import setup_logging
from config.settings import settings
from agents import trace, gen_trace_id
from langfuse import observe

from tools.campaign_tools import fetch_campaign_info
from tools.content_tools import create_linkedin_connection_note, create_whatsapp_message
from tools.send_email import send_plain_email
from outreach.workers import run_drafter_agent, run_reviewer_agent
from services import campaign_context_service, lead_service, metering_service, platform_settings_service, tenant_service
from utils.db_connection import dict_from_row, get_conn
from utils.quick_replies import (
    quick_replies_for_outreach,
    quick_replies_html_for_outreach,
    plain_text_to_basic_html,
)
from utils.langfuse_metadata import trace_metadata as _trace_metadata, update_current_span_metadata

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Type for SSE callback
SSECallback = Callable[[str, str], Awaitable[None]]

ACTIVE_INITIAL_OUTREACH_STATUSES = ("DRAFT", "SCHEDULED", "SENT", "GENERATING")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ineligible(reason: str, *, code: str, skip_step: bool = False, step: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"eligible": False, "reason": reason, "code": code, "skip_step": skip_step, "step": step}


def _clean_phone_number(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _channel_prerequisite_error(channel: str, lead: dict[str, Any]) -> str | None:
    normalized = (channel or "email").strip().lower()
    if normalized == "whatsapp":
        phone = _clean_phone_number(lead.get("phone_number"))
        if len(phone) < 8:
            return "WhatsApp step cannot be sent because this lead has no valid phone number."
    elif normalized == "linkedin":
        linkedin_url = str(lead.get("linkedin_url") or "").strip()
        if not linkedin_url:
            return "LinkedIn step cannot be sent because this lead has no LinkedIn URL."
    elif normalized == "email":
        email = str(lead.get("email") or "").strip()
        if "@" not in email:
            return "Email step cannot be sent because this lead has no valid email address."
    return None


def _find_next_sequence_step(conn, organization_id: int, campaign_id: int, lead_id: int) -> dict[str, Any] | None:
    # 1. Check global opt-out (the only truly global halt signal — legal/preference)
    lead_row = conn.execute(
        "SELECT email, phone_number, linkedin_url, email_opt_out FROM leads WHERE id = ?",
        (lead_id,),
    ).fetchone()
    if not lead_row:
        return _ineligible("Lead was not found.", code="lead_not_found")
    lead = dict_from_row(lead_row) or {}
    if lead.get("email_opt_out"):
        return _ineligible("Lead is globally opted out.", code="opted_out")

    # 1b. Check campaign-scoped halt signals — isolated per (campaign_id, lead_id)
    cl_row = conn.execute(
        "SELECT responded, meeting_booked, emails_sent FROM campaign_leads WHERE campaign_id = ? AND lead_id = ?",
        (campaign_id, lead_id),
    ).fetchone()
    cl = dict_from_row(cl_row) if cl_row else {}
    campaign_touch_count = int(cl.get("emails_sent") or 0)
    if cl:
        if cl.get("meeting_booked"):
            return _ineligible("Meeting already booked for this campaign lead.", code="meeting_booked")
        if cl.get("responded"):
            return _ineligible("Lead already responded in this campaign.", code="responded")

    # 2. Get all active touches for this campaign/lead
    touches = [dict_from_row(r) for r in conn.execute(
        "SELECT em.id, em.status, em.channel, em.created_at, em.sent_at, em.sequence_step_id, "
        "step.step_number AS message_step_number, "
        "(SELECT MIN(seq.step_number) FROM campaign_sequences seq "
        " WHERE seq.campaign_id = em.campaign_id "
        " AND LOWER(COALESCE(seq.channel, 'email')) = LOWER(COALESCE(em.channel, 'email'))) "
        "AS inferred_channel_step_number "
        "FROM email_messages em "
        "LEFT JOIN campaign_sequence_steps step ON step.id = em.sequence_step_id "
        "WHERE em.organization_id = ? AND em.campaign_id = ? AND em.lead_id = ? AND em.direction = 'outbound' "
        "AND em.status NOT IN ('FAILED', 'REJECTED') "
        "ORDER BY em.created_at ASC",
        (organization_id, campaign_id, lead_id)
    ).fetchall()]

    if touches:
        last_touch = touches[-1]
        # If the last touch is not sent yet, we can't move to the next step
        if last_touch.get("status", "").upper() != "SENT":
            status = last_touch.get("status", "pending")
            step = last_touch.get("message_step_number") or "unknown"
            return _ineligible(
                f"Step {step} already has a {status} outreach item. Review or resolve that draft before creating another.",
                code="pending_touch",
            )
        
        # sequence_step_id stores the campaign_sequence_steps row id, not the
        # step number. Older omnichannel drafts may not have it, so infer from
        # the configured channel order before falling back to sent touch count.
        sent_touches = [touch for touch in touches if touch.get("status", "").upper() == "SENT"]
        current_step = (
            last_touch.get("message_step_number")
            or campaign_touch_count
            or last_touch.get("inferred_channel_step_number")
            or len(sent_touches)
        )
        next_step_num = current_step + 1
        
        # Check if enough time has passed
        last_time_str = last_touch.get("sent_at") or last_touch.get("created_at")
        try:
            last_time = datetime.datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
        except:
            last_time = datetime.datetime.now(datetime.UTC)
    else:
        next_step_num = campaign_touch_count + 1 if campaign_touch_count > 0 else 1
        last_time = None

    # 3. Fetch next step definition from campaign_sequences
    seq_row = conn.execute(
        "SELECT seq.step_number, seq.channel, seq.delay_days, seq.prompt_context, step.id AS sequence_step_id "
        "FROM campaign_sequences seq "
        "LEFT JOIN campaign_sequence_steps step ON step.campaign_id = seq.campaign_id AND step.step_number = seq.step_number "
        "WHERE seq.campaign_id = ? AND seq.step_number = ?",
        (campaign_id, next_step_num)
    ).fetchone()

    if not seq_row:
        # Fallback for Step 1 if no sequences are defined (backward compatibility)
        if next_step_num == 1:
            seq = {"step_number": 1, "channel": "email", "delay_days": 0}
            error = _channel_prerequisite_error("email", lead)
            if error:
                return _ineligible(error, code="missing_channel_data", skip_step=True, step=seq)
            return seq
        return _ineligible(f"Sequence exhausted after step {next_step_num - 1}.", code="sequence_exhausted")

    seq = dict_from_row(seq_row)
    channel_error = _channel_prerequisite_error(str(seq.get("channel") or "email"), lead)
    if channel_error:
        return _ineligible(
            f"Step {seq.get('step_number')} skipped: {channel_error}",
            code="missing_channel_data",
            skip_step=True,
            step=seq,
        )
    
    # 4. Check delay
    if last_time and seq.get("delay_days", 0) > 0:
        days_passed = (datetime.datetime.now(datetime.UTC) - last_time).days
        if days_passed < seq["delay_days"]:
            due_at = last_time + datetime.timedelta(days=int(seq["delay_days"]))
            return _ineligible(
                f"Step {seq.get('step_number')} is waiting for the delay window. Due at {due_at.replace(microsecond=0).isoformat()}.",
                code="delay_not_passed",
            )

    return seq


def _record_skipped_sequence_step(
    conn,
    *,
    organization_id: int,
    campaign_id: int,
    lead_id: int,
    lead_email: str | None,
    step: dict[str, Any],
    reason: str,
) -> None:
    channel = str(step.get("channel") or "email").lower()
    step_number = int(step.get("step_number") or 0)
    subject = f"Skipped {channel} outreach"
    body = f"Skipped step {step_number} for {lead_email or 'lead'}: {reason}"
    created_at = _now_iso()
    try:
        conn.execute(
            "INSERT INTO email_messages "
            "(organization_id, lead_id, campaign_id, direction, subject, body, status, processed, approved, created_at, sequence_step_id, channel, last_error, review_rationale) "
            "VALUES (?, ?, ?, 'outbound', ?, ?, 'FAILED', 1, 0, ?, ?, ?, ?, ?)",
            (
                organization_id,
                lead_id,
                campaign_id,
                subject,
                body,
                created_at,
                step.get("sequence_step_id"),
                channel,
                reason[:1000],
                json.dumps(
                    {
                        "failure_category": "data_missing",
                        "failure_action": "Update the lead data if you want to retry this channel. The campaign advanced to the next sequence step.",
                        "failure_severity": "warning",
                        "step_skipped": True,
                        "step_number": step_number,
                        "channel": channel,
                    }
                ),
            ),
        )
    except Exception:
        conn.execute(
            "INSERT INTO email_messages "
            "(organization_id, lead_id, campaign_id, direction, subject, body, status, processed, approved, created_at, sequence_step_id, channel) "
            "VALUES (?, ?, ?, 'outbound', ?, ?, 'FAILED', 1, 0, ?, ?, ?)",
            (
                organization_id,
                lead_id,
                campaign_id,
                subject,
                body,
                created_at,
                step.get("sequence_step_id"),
                channel,
            ),
        )
    conn.execute(
        "UPDATE campaign_leads SET emails_sent = CASE WHEN emails_sent < ? THEN ? ELSE emails_sent END WHERE campaign_id = ? AND lead_id = ?",
        (step_number, step_number, campaign_id, lead_id),
    )
    try:
        conn.execute(
            "INSERT INTO events (organization_id, type, payload, metadata) VALUES (?, ?, ?, ?)",
            (
                organization_id,
                "campaign_sequence_step_skipped",
                json.dumps(
                    {
                        "campaign_id": campaign_id,
                        "lead_id": lead_id,
                        "step_number": step_number,
                        "channel": channel,
                        "reason": reason,
                    }
                ),
                None,
            ),
        )
    except Exception as exc:
        logger.debug("Could not record skipped sequence event: %s", exc)


def _skip_summary(skipped_steps: list[dict[str, Any]]) -> str:
    if not skipped_steps:
        return ""
    return " ".join(
        f"Skipped step {item.get('step_number')} {item.get('channel')}: {item.get('reason')}"
        for item in skipped_steps
    )


def _claim_next_outreach_touch(
    *,
    organization_id: int,
    campaign_id: int,
    lead_id: int | None,
    lead_email: str | None,
) -> dict[str, Any]:
    """Reserve the next campaign sequence touch before LLM generation to prevent duplicate sends."""
    if not lead_id:
        return {"claimed": False, "error": "lead_id is required"}
    try:
        with get_conn() as conn:
            with conn:
                skipped_steps: list[dict[str, Any]] = []
                next_step: dict[str, Any] | None = None
                for _attempt in range(5):
                    candidate = _find_next_sequence_step(conn, organization_id, campaign_id, lead_id)
                    if not candidate:
                        return {"claimed": False, "error": "No eligible sequence step found."}
                    if candidate.get("eligible", True):
                        next_step = candidate
                        break
                    if candidate.get("skip_step") and candidate.get("step"):
                        step = candidate["step"]
                        reason = str(candidate.get("reason") or "Step skipped because required channel data is missing.")
                        _record_skipped_sequence_step(
                            conn,
                            organization_id=organization_id,
                            campaign_id=campaign_id,
                            lead_id=lead_id,
                            lead_email=lead_email,
                            step=step,
                            reason=reason,
                        )
                        skipped_steps.append(
                            {
                                "step_number": step.get("step_number"),
                                "channel": step.get("channel"),
                                "reason": reason,
                            }
                        )
                        continue
                    return {"claimed": False, "error": candidate.get("reason") or "No eligible sequence step found.", "code": candidate.get("code")}
                if not next_step:
                    return {"claimed": False, "error": "No eligible sequence step found after skipping unavailable channel steps."}
                
                cur = conn.execute(
                    "INSERT INTO email_messages "
                    "(organization_id, lead_id, campaign_id, direction, subject, body, status, processed, approved, created_at, sequence_step_id, channel) "
                    "VALUES (?, ?, ?, 'outbound', ?, ?, 'GENERATING', 1, 0, ?, ?, ?)",
                    (
                        organization_id,
                        lead_id,
                        campaign_id,
                        f"Generating {next_step['channel']} outreach",
                        f"Reserved step {next_step['step_number']} generation for {lead_email or 'lead'}.",
                        _now_iso(),
                        next_step.get("sequence_step_id"),
                        next_step["channel"],
                    ),
                )
                return {"claimed": True, "message_id": cur.lastrowid, "step": next_step, "skipped_steps": skipped_steps}
    except Exception as exc:
        return {"claimed": False, "error": str(exc)}


def _complete_initial_outreach_touch(
    conn,
    *,
    message_id: int,
    subject: str,
    body: str,
    status: str,
    approved: int,
    selected_draft_type: str | None,
    review_rationale: str | None,
    external_message_id: str | None = None,
    external_thread_id: str | None = None,
    channel: str = "email",
    deep_link_url: str | None = None,
) -> None:
    conn.execute(
        "UPDATE email_messages SET subject = ?, body = ?, status = ?, approved = ?, "
        "selected_draft_type = ?, review_rationale = ?, external_message_id = ?, external_thread_id = ?, "
        "sent_at = CASE WHEN ? = 'SENT' THEN ? ELSE sent_at END, last_error = NULL, "
        "channel = ?, deep_link_url = ? "
        "WHERE id = ?",
        (
            subject,
            body,
            status,
            approved,
            selected_draft_type,
            review_rationale,
            external_message_id,
            external_thread_id,
            status,
            _now_iso(),
            channel,
            deep_link_url,
            message_id,
        ),
    )


def _fail_initial_outreach_touch(message_id: int | None, error: str) -> None:
    if not message_id:
        return
    try:
        with get_conn() as conn:
            with conn:
                conn.execute(
                    "UPDATE email_messages SET status = 'FAILED', last_error = ?, review_rationale = ? WHERE id = ? AND status = 'GENERATING'",
                    (
                        error[:1000],
                        json.dumps(
                            {
                                "failure_category": "technical_error",
                                "failure_action": "Retry the outreach after checking the provider, AI, or server error. The campaign did not advance to the next sequence step.",
                                "failure_severity": "error",
                                "step_skipped": False,
                            }
                        ),
                        message_id,
                    ),
                )
    except Exception as exc:
        logger.debug("Could not mark outreach generation claim as failed: %s", exc)


class OutreachOrchestrator:
    """Orchestrates complete database-driven outreach campaigns using Worker Agents."""
    
    @observe()
    async def execute_campaign(
        self, 
        campaign_name: Optional[str] = None,
        organization_id: int | None = None,
        callback: Optional[SSECallback] = None
    ) -> Dict[str, Any]:
        """Execute a complete database-driven outreach campaign via Worker Agents."""
        msg = f"Starting Orchestrator for campaign. Target: {campaign_name or 'Random'}"
        logger.info(msg)
        if callback: await callback("info", msg)
        trace_id = gen_trace_id()
        
        try:
            with trace(
                workflow_name="Outreach Campaign Orchestrator Pipeline",
                trace_id=trace_id,
                metadata=_trace_metadata({
                    "campaign": campaign_name or "random_active",
                    "organization_id": organization_id,
                }),
            ):
                # 1. Get Campaign
                msg = "Fetching campaign details..."
                logger.info(msg)
                if callback: await callback("info", msg)
                
                campaign = fetch_campaign_info(campaign_name=campaign_name, organization_id=organization_id)
                if not campaign:
                    err_msg = "No active campaign found"
                    if callback: await callback("error", err_msg)
                    return {"success": False, "error": err_msg}
                explicit_campaign_org_id = getattr(campaign, "organization_id", None)
                campaign_org_id = explicit_campaign_org_id or organization_id or 1
                campaign_routing_mode = getattr(campaign, "llm_routing_mode", None)
                has_tenant_context = explicit_campaign_org_id is not None or organization_id is not None
                tenant_metadata: dict[str, Any] = {
                    "organization_id": campaign_org_id,
                    "campaign_id": campaign.id,
                    "campaign_name": campaign.name,
                }
                try:
                    if explicit_campaign_org_id or organization_id:
                        organization = tenant_service.get_organization(campaign_org_id)
                        subscription = tenant_service.get_organization_subscription(campaign_org_id)
                        plan = subscription.get("plan") or {}
                        tenant_metadata.update(
                            {
                                "organization_name": organization.get("name"),
                                "organization_slug": organization.get("slug"),
                                "subscription_status": subscription.get("effective_status") or subscription.get("status"),
                                "plan_id": plan.get("id"),
                                "plan_name": plan.get("name"),
                                "plan_slug": plan.get("slug"),
                            }
                        )
                except Exception as exc:
                    logger.debug("Could not enrich campaign trace with tenant metadata: %s", exc)
                update_current_span_metadata(tenant_metadata)

                approval_msg = (
                    "Approval mode: auto-send enabled for this campaign; human draft approval will be skipped."
                    if campaign.auto_approve_drafts
                    else "Approval mode: human review required; emails will be saved in Draft Approvals."
                )
                logger.info(approval_msg)
                if callback:
                    await callback("info", approval_msg)
                
                # 2. Get campaign-scoped eligible leads
                requested_max = campaign.max_leads_per_campaign or settings.max_leads_per_campaign
                batch_size = max(1, min(requested_max, settings.max_leads_per_campaign))
                candidate_limit = max(batch_size, min(batch_size * 4, 500))
                msg = f"Fetching candidates for up to {batch_size} eligible lead touch(es) for campaign: {campaign.name}..."
                logger.info(msg)
                if callback: await callback("info", msg)
                
                lead_res = lead_service.get_leads(
                    campaign_id=campaign.id,
                    max_leads=candidate_limit,
                    order_by=campaign.lead_selection_order,
                    organization_id=campaign_org_id,
                )
                if not lead_res.get("success"):
                    err_msg = f"Failed to get eligible leads: {lead_res.get('error')}"
                    if callback: await callback("error", err_msg)
                    return {"success": False, "error": err_msg}
                leads = lead_res.get("data") or []
                if not leads:
                    msg = f"No eligible leads found for campaign '{campaign.name}'."
                    logger.info(msg)
                    if callback: await callback("warning", msg)
                    return {"success": True, "message": msg, "processed": 0, "sent": 0, "drafted": 0, "failed": 0}
                
                camp_info = {
                    "name": campaign.name,
                    "value_proposition": campaign.value_proposition,
                    "cta": campaign.cta,
                    "tone": settings.tone,
                    "sender_name": settings.outreach_sender_name,
                    "sender_company": settings.outreach_sender_company,
                    "organization_id": campaign_org_id,
                    "organization_name": tenant_metadata.get("organization_name"),
                    "organization_slug": tenant_metadata.get("organization_slug"),
                    "plan_name": tenant_metadata.get("plan_name"),
                    "plan_slug": tenant_metadata.get("plan_slug"),
                    "llm_routing_mode": campaign_routing_mode,
                }
                sent_count = 0
                draft_count = 0
                failed_count = 0
                skipped_count = 0
                processed = 0
                claimed_count = 0
                run_records: list[Dict[str, Any]] = []

                for index, lead_data in enumerate(leads, start=1):
                    if claimed_count >= batch_size:
                        break
                    lead_info = {
                        "name": lead_data.get("name", "Valued Contact"),
                        "email": lead_data.get("email"),
                        "phone_number": lead_data.get("phone_number"),
                        "linkedin_url": lead_data.get("linkedin_url"),
                        "company": lead_data.get("company", "Your Company"),
                        "industry": lead_data.get("industry", "Business"),
                        "pain_points": lead_data.get("pain_points", "Operational challenges"),
                        "job_title": lead_data.get("job_title"),
                        "seniority": lead_data.get("seniority"),
                        "location": lead_data.get("location"),
                        "company_size": lead_data.get("company_size"),
                        "company_website": lead_data.get("company_website"),
                        "company_description": lead_data.get("company_description"),
                        "recent_activity": lead_data.get("recent_activity"),
                        "enrichment_source": lead_data.get("enrichment_source"),
                        "icp_score": lead_data.get("icp_score"),
                        "icp_rationale": lead_data.get("icp_rationale"),
                        "touch_count": lead_data.get("touch_count", 0),
                        "emails_sent": lead_data.get("emails_sent", 0),
                        "responded": lead_data.get("responded", 0),
                    }

                    progress_msg = f"[{index}/{len(leads)}] Processing lead: {lead_info['name']} <{lead_info['email']}>"
                    logger.info(progress_msg)
                    if callback:
                        await callback("info", progress_msg)

                    claim_message_id: int | None = None
                    try:
                        claim = _claim_next_outreach_touch(
                            organization_id=campaign_org_id,
                            campaign_id=campaign.id,
                            lead_id=lead_data.get("id"),
                            lead_email=lead_info["email"],
                        )
                        if not claim.get("claimed"):
                            skipped_count += 1
                            reason = claim.get("error") or "could not reserve campaign sequence step"
                            run_records.append({
                                "lead_email": lead_info["email"],
                                "lead_name": lead_info["name"],
                                "status": "skipped",
                                "reason": reason,
                            })
                            if callback:
                                await callback("warning", f"Skipped {lead_info['email']}: {reason}")
                            continue
                        
                        claim_message_id = claim.get("message_id")
                        claimed_count += 1
                        current_step_info = claim.get("step") or {"step_number": 1, "channel": "email"}
                        target_channel = current_step_info.get("channel", "email")
                        step_context = current_step_info.get("prompt_context", "")
                        skipped_step_note = _skip_summary(claim.get("skipped_steps") or [])
                        if skipped_step_note and callback:
                            await callback("warning", f"{lead_info['email']}: {skipped_step_note}")

                        requested_routing_mode = campaign_routing_mode
                        if has_tenant_context:
                            routing_policy = tenant_service.resolve_allowed_llm_routing_mode(
                                campaign_org_id,
                                requested_routing_mode,
                                fallback_mode=platform_settings_service.get_llm_routing_mode(),
                            )
                        else:
                            routing_policy = {
                                "resolved_mode": requested_routing_mode,
                                "default_mode": requested_routing_mode,
                            }
                        effective_routing_mode = str(routing_policy.get("resolved_mode") or requested_routing_mode or "balanced")
                        workflow_credits = metering_service.credits_for_routing_mode(6, effective_routing_mode)
                        usage_context = (
                            metering_service.ai_usage_action_context(
                                organization_id=campaign_org_id,
                                action_type="outreach_email_generation",
                                credits_used=workflow_credits,
                                source_object_type="lead",
                                source_object_id=lead_data.get("id"),
                                metadata={
                                    "campaign_id": campaign.id,
                                    "campaign_name": campaign.name,
                                    "lead_email": lead_info["email"],
                                    "auto_approve_drafts": bool(campaign.auto_approve_drafts),
                                    "requested_routing_mode": requested_routing_mode,
                                    "default_routing_mode": routing_policy.get("default_mode"),
                                    "routing_mode": effective_routing_mode,
                                    "base_credits": 6,
                                    "credits_used": workflow_credits,
                                },
                            )
                            if has_tenant_context
                            else nullcontext({"id": None})
                        )
                        with usage_context as usage_action:
                            with platform_settings_service.llm_routing_mode_context(campaign_routing_mode):
                                deep_link_url = None
                                
                                # Use step_context if provided to guide the drafter
                                if step_context:
                                    camp_info["sequence_prompt_context"] = step_context
                                
                                if target_channel == "linkedin":
                                    draft = await create_linkedin_connection_note(
                                        camp_info["name"], 
                                        camp_info["value_proposition"], 
                                        lead_info,
                                        context=step_context
                                    )
                                    deep_link_url = lead_info.get("linkedin_url")
                                    # Create mock review result for compatibility
                                    from outreach.workers import ReviewResponse
                                    review_result = ReviewResponse(
                                        rationale="LinkedIn connection note selected based on touch count strategy.",
                                        selected_draft_type="linkedin",
                                        subject=draft.subject,
                                        body=draft.body,
                                        channel="linkedin",
                                        deep_link_url=deep_link_url or ""
                                    )
                                elif target_channel == "whatsapp":
                                    draft = await create_whatsapp_message(
                                        campaign_name=camp_info["name"],
                                        value_proposition=camp_info["value_proposition"],
                                        lead_info=lead_info,
                                        step_number=int(current_step_info.get("step_number") or 1),
                                        context=step_context,
                                    )
                                    raw_number = lead_info.get("phone_number") or ""
                                    clean_number = str(raw_number).replace("+", "").replace("-", "").replace(" ", "").strip()
                                    if clean_number and clean_number.lower() != "none":
                                        encoded_text = urllib.parse.quote(draft.body)
                                        deep_link_url = f"https://wa.me/{clean_number}?text={encoded_text}"
                                    else:
                                        deep_link_url = None
                                        if callback:
                                            await callback("warning", f"WhatsApp draft created for {lead_info['email']} but no phone number is on file. Add a phone number to the lead to enable the wa.me link.")
                                    # Create mock review result for compatibility
                                    from outreach.workers import ReviewResponse
                                    review_result = ReviewResponse(
                                        rationale="WhatsApp message selected based on touch count strategy.",
                                        selected_draft_type="whatsapp",
                                        subject=draft.subject,
                                        body=draft.body,
                                        channel="whatsapp",
                                        deep_link_url=deep_link_url or ""
                                    )
                                else:
                                    drafts = await run_drafter_agent(camp_info, lead_info)
                                    review_result = await run_reviewer_agent(camp_info, lead_info, drafts)

                            if campaign.auto_approve_drafts and target_channel == "email":
                                html_body = plain_text_to_basic_html(review_result.body) + quick_replies_html_for_outreach(
                                    review_result.subject,
                                    lead_email=lead_info["email"],
                                    campaign_id=campaign.id,
                                    organization_id=campaign_org_id,
                                )
                                send_res = await send_plain_email(
                                    email=lead_info["email"],
                                    name=lead_info["name"],
                                    subject=review_result.subject,
                                    body=review_result.body,
                                    html_body=html_body,
                                    bypass_human_approval=True,
                                    organization_id=campaign_org_id,
                                )
                                if send_res.ok:
                                    metering_service.update_ai_usage_action(
                                        usage_action.get("id"),
                                        action_type="outreach_email_sent",
                                        metadata_patch={
                                            "selected_draft_type": review_result.selected_draft_type,
                                            "subject": review_result.subject,
                                            "message_id": send_res.message_id,
                                        },
                                    )
                                    if has_tenant_context:
                                        metering_service.record_platform_usage_event(
                                            organization_id=campaign_org_id,
                                            event_type="email_sent",
                                            source_object_type="lead",
                                            source_object_id=lead_data.get("id"),
                                            metadata={"campaign_id": campaign.id, "channel": "outreach"},
                                        )
                                else:
                                    metering_service.update_ai_usage_action(
                                        usage_action.get("id"),
                                        action_type="outreach_email_send_failed",
                                        status="error",
                                        metadata_patch={"error": send_res.error},
                                    )
                                if send_res.ok:
                                    try:
                                        with get_conn() as conn:
                                            _complete_initial_outreach_touch(
                                                conn,
                                                message_id=claim_message_id,
                                                subject=review_result.subject,
                                                body=review_result.body,
                                                status="SENT",
                                                approved=1,
                                                selected_draft_type=review_result.selected_draft_type,
                                                review_rationale=getattr(review_result, "rationale", None),
                                                external_message_id=send_res.message_id,
                                                external_thread_id=send_res.thread_id,
                                            )
                                            campaign_context_service.record_outbound(
                                                conn,
                                                organization_id=campaign_org_id,
                                                campaign_id=campaign.id,
                                                lead_id=lead_data.get("id"),
                                                subject=review_result.subject,
                                                body=review_result.body,
                                            )
                                    except Exception as e:
                                        logger.error(f"Failed to log sent email to database: {e}")

                                    lead_id = lead_data.get("id")
                                    if lead_id:
                                        lead_service.update_lead_touch(lead_id, campaign.id)
                                        # Prevent downgrading warm/qualified/meeting states back to CONTACTED
                                        if (lead_data.get("status") or "").upper() in {"NEW", "COLD", ""}:
                                            lead_service.update_lead_status(lead_id, "CONTACTED")

                                    sent_count += 1
                                    processed += 1
                                    run_records.append({
                                        "lead_email": lead_info["email"],
                                        "lead_name": lead_info["name"],
                                        "status": "sent",
                                        "subject": review_result.subject,
                                        "selected_draft_type": review_result.selected_draft_type,
                                        "skipped_steps": claim.get("skipped_steps") or [],
                                    })
                                    if callback:
                                        await callback("success", f"Auto-approved and sent '{review_result.selected_draft_type}' draft to {lead_info['email']}")
                                else:
                                    _fail_initial_outreach_touch(claim_message_id, send_res.error or "Email delivery failed")
                                    failed_count += 1
                                    run_records.append({
                                        "lead_email": lead_info["email"],
                                        "lead_name": lead_info["name"],
                                        "status": "failed",
                                        "error": send_res.error,
                                    })
                                    if callback:
                                        await callback("error", f"Email delivery failed for {lead_info['email']}: {send_res.error}")
                            else:
                                draft_log_data = {
                                    "organization_id": campaign_org_id,
                                    "campaign_id": campaign.id,
                                    "lead_id": lead_data.get("id"),
                                    "lead_email": lead_info["email"],
                                    "status": "DRAFT",
                                    "approved": 0,
                                    "direction": "outbound",
                                    "auto_approve_drafts": False,
                                }
                                try:
                                    logger.info(
                                        "Attempting to save draft for human approval",
                                        extra={
                                            "kind": "draft_save_attempt",
                                            "component": "outreach",
                                            "data": draft_log_data,
                                        },
                                    )
                                    with get_conn() as conn:
                                        _complete_initial_outreach_touch(
                                            conn,
                                            message_id=claim_message_id,
                                            subject=review_result.subject,
                                            body=review_result.body,
                                            status="DRAFT",
                                            approved=0,
                                            selected_draft_type=review_result.selected_draft_type,
                                            review_rationale=getattr(review_result, "rationale", None),
                                            channel=getattr(review_result, "channel", "email") or "email",
                                            deep_link_url=getattr(review_result, "deep_link_url", None) or None,
                                        )
                                        draft_id = claim_message_id
                                        draft_log_data["draft_id"] = draft_id
                                        logger.info(
                                            "Draft saved for human approval",
                                            extra={
                                                "kind": "draft_created",
                                                "component": "outreach",
                                                "data": draft_log_data,
                                            },
                                        )
                                        campaign_context_service.record_outbound(
                                            conn,
                                            organization_id=campaign_org_id,
                                            campaign_id=campaign.id,
                                            lead_id=lead_data.get("id"),
                                            subject=review_result.subject,
                                            body=review_result.body,
                                        )
                                    metering_service.update_ai_usage_action(
                                        usage_action.get("id"),
                                        action_type="outreach_draft_created",
                                        metadata_patch={
                                            "draft_id": draft_id,
                                            "selected_draft_type": review_result.selected_draft_type,
                                            "subject": review_result.subject,
                                        },
                                    )
                                    if has_tenant_context:
                                        metering_service.record_platform_usage_event(
                                            organization_id=campaign_org_id,
                                            event_type="draft_created",
                                            source_object_type="email_message",
                                            source_object_id=draft_id,
                                            metadata={"campaign_id": campaign.id, "lead_id": lead_data.get("id")},
                                        )
                                    lead_id = lead_data.get("id")
                                    if lead_id:
                                        lead_service.update_lead_touch(lead_id, campaign.id)
                                    draft_count += 1
                                    processed += 1
                                    run_records.append({
                                        "lead_email": lead_info["email"],
                                        "lead_name": lead_info["name"],
                                        "status": "draft",
                                        "subject": review_result.subject,
                                        "selected_draft_type": review_result.selected_draft_type,
                                        "skipped_steps": claim.get("skipped_steps") or [],
                                    })
                                    if callback:
                                        await callback("success", f"Saved draft #{draft_id} for human approval: {lead_info['email']}")
                                except Exception as e:
                                    _fail_initial_outreach_touch(claim_message_id, str(e))
                                    logger.exception(
                                        "Failed to save outbound draft for human approval",
                                        extra={
                                            "kind": "draft_save_failed",
                                            "component": "outreach",
                                            "data": {
                                                **draft_log_data,
                                                "error": str(e),
                                            },
                                        },
                                    )
                                    metering_service.update_ai_usage_action(
                                        usage_action.get("id"),
                                        action_type="outreach_draft_create_failed",
                                        status="error",
                                        metadata_patch={"error": str(e)},
                                    )
                                    failed_count += 1
                                    run_records.append({
                                        "lead_email": lead_info["email"],
                                        "lead_name": lead_info["name"],
                                        "status": "failed",
                                        "error": str(e),
                                    })
                                    if callback:
                                        await callback("error", f"Failed to save draft for {lead_info['email']}: {e}")
                    except Exception as lead_error:
                        _fail_initial_outreach_touch(claim_message_id, str(lead_error))
                        failed_count += 1
                        run_records.append({
                            "lead_email": lead_info["email"],
                            "lead_name": lead_info["name"],
                            "status": "error",
                            "error": str(lead_error),
                        })
                        logger.error(f"Lead processing failed for {lead_info['email']}: {lead_error}")
                        if callback:
                            await callback("error", f"Lead processing failed for {lead_info['email']}: {lead_error}")

                final_msg = (
                    f"Campaign finished: processed={processed}, sent={sent_count}, "
                    f"drafted={draft_count}, skipped={skipped_count}, failed={failed_count}"
                )
                logger.info(final_msg)
                if callback:
                    await callback("success", final_msg)
                return {
                    "success": processed > 0 or skipped_count > 0,
                    "message": final_msg,
                    "processed": processed,
                    "sent": sent_count,
                    "drafted": draft_count,
                    "skipped": skipped_count,
                    "failed": failed_count,
                    "run_records": run_records,
                }
                    
        except Exception as e:
            err_msg = f"Campaign execution error: {str(e)}"
            logger.error(err_msg)
            if callback: await callback("error", err_msg)
            return {"success": False, "error": str(e)}

# Create global instance for API usage
outreach_orchestrator = OutreachOrchestrator()
