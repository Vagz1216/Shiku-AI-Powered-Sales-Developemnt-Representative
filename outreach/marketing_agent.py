"""Senior Marketing Orchestrator that coordinates database-driven outreach campaigns."""

import logging
import json
from typing import Dict, Any, Optional, Callable, Awaitable

from config.logging import setup_logging
from config.settings import settings
from agents import trace, gen_trace_id

from tools.campaign_tools import fetch_campaign_info
from tools.send_email import send_plain_email
from outreach.workers import run_drafter_agent, run_reviewer_agent
from services import lead_service
from utils.quick_replies import (
    quick_replies_for_outreach,
    quick_replies_html_for_outreach,
    plain_text_to_basic_html,
)

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Type for SSE callback
SSECallback = Callable[[str, str], Awaitable[None]]

class OutreachOrchestrator:
    """Orchestrates complete database-driven outreach campaigns using Worker Agents."""
    
    async def execute_campaign(
        self, 
        campaign_name: Optional[str] = None,
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
                metadata={"campaign": campaign_name or "random_active"}
            ):
                # 1. Get Campaign
                msg = "Fetching campaign details..."
                logger.info(msg)
                if callback: await callback("info", msg)
                
                campaign = fetch_campaign_info(campaign_name=campaign_name)
                if not campaign:
                    err_msg = "No active campaign found"
                    if callback: await callback("error", err_msg)
                    return {"success": False, "error": err_msg}
                
                # 2. Get campaign-scoped eligible leads
                requested_max = campaign.max_leads_per_campaign or settings.max_leads_per_campaign
                batch_size = max(1, min(requested_max, settings.max_leads_per_campaign))
                msg = f"Fetching up to {batch_size} eligible lead(s) for campaign: {campaign.name}..."
                logger.info(msg)
                if callback: await callback("info", msg)
                
                lead_res = lead_service.get_leads(
                    campaign_id=campaign.id,
                    max_leads=batch_size,
                    order_by=campaign.lead_selection_order,
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
                }
                sent_count = 0
                draft_count = 0
                failed_count = 0
                processed = 0
                run_records: list[Dict[str, Any]] = []

                for index, lead_data in enumerate(leads, start=1):
                    lead_info = {
                        "name": lead_data.get("name", "Valued Contact"),
                        "email": lead_data.get("email"),
                        "company": lead_data.get("company", "Your Company"),
                        "industry": lead_data.get("industry", "Business"),
                        "pain_points": lead_data.get("pain_points", "Operational challenges"),
                        "touch_count": lead_data.get("touch_count", 0),
                        "emails_sent": lead_data.get("emails_sent", 0),
                        "responded": lead_data.get("responded", 0),
                    }

                    progress_msg = f"[{index}/{len(leads)}] Processing lead: {lead_info['name']} <{lead_info['email']}>"
                    logger.info(progress_msg)
                    if callback:
                        await callback("info", progress_msg)

                    try:
                        drafts = await run_drafter_agent(camp_info, lead_info)
                        review_result = await run_reviewer_agent(camp_info, lead_info, drafts)

                        if campaign.auto_approve_drafts:
                            body_with_qr = review_result.body + quick_replies_for_outreach(
                                review_result.subject,
                                lead_email=lead_info["email"],
                                campaign_id=campaign.id,
                            )
                            html_body = plain_text_to_basic_html(review_result.body) + quick_replies_html_for_outreach(
                                review_result.subject,
                                lead_email=lead_info["email"],
                                campaign_id=campaign.id,
                            )
                            send_res = await send_plain_email(
                                email=lead_info["email"],
                                name=lead_info["name"],
                                subject=review_result.subject,
                                body=body_with_qr,
                                html_body=html_body,
                            )
                            if send_res.ok:
                                try:
                                    from utils.db_connection import get_conn
                                    with get_conn() as conn:
                                        conn.execute(
                                            "INSERT INTO email_messages (lead_id, campaign_id, direction, subject, body, status, approved) VALUES (?, ?, 'outbound', ?, ?, 'SENT', 1)",
                                            (lead_data.get("id"), campaign.id, review_result.subject, review_result.body)
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
                                })
                                if callback:
                                    await callback("success", f"Sent '{review_result.selected_draft_type}' draft to {lead_info['email']}")
                            else:
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
                            try:
                                from utils.db_connection import get_conn
                                with get_conn() as conn:
                                    conn.execute(
                                        "INSERT INTO email_messages (lead_id, campaign_id, direction, subject, body, status, approved) VALUES (?, ?, 'outbound', ?, ?, 'DRAFT', 0)",
                                        (lead_data.get("id"), campaign.id, review_result.subject, review_result.body)
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
                                })
                                if callback:
                                    await callback("success", f"Saved draft for approval: {lead_info['email']}")
                            except Exception as e:
                                failed_count += 1
                                run_records.append({
                                    "lead_email": lead_info["email"],
                                    "lead_name": lead_info["name"],
                                    "status": "failed",
                                    "error": str(e),
                                })
                                logger.error(f"Failed to save draft to database: {e}")
                                if callback:
                                    await callback("error", f"Failed to save draft for {lead_info['email']}: {e}")
                    except Exception as lead_error:
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
                    f"drafted={draft_count}, failed={failed_count}"
                )
                logger.info(final_msg)
                if callback:
                    await callback("success", final_msg)
                return {
                    "success": processed > 0,
                    "message": final_msg,
                    "processed": processed,
                    "sent": sent_count,
                    "drafted": draft_count,
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
