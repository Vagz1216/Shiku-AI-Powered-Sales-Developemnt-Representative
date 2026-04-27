"""Senior Marketing Orchestrator that coordinates database-driven outreach campaigns."""

import logging
import json
from typing import Dict, Any, Optional, Callable, Awaitable

from config.logging import setup_logging
from agents import trace, gen_trace_id

from tools.campaign_tools import fetch_campaign_info
from tools.lead_tools import fetch_lead_info
from tools.send_email import send_plain_email
from outreach.workers import run_drafter_agent, run_reviewer_agent
from services import lead_service

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
                
                # 2. Get Lead
                msg = f"Fetching lead for campaign: {campaign.name}..."
                logger.info(msg)
                if callback: await callback("info", msg)
                
                lead_res = fetch_lead_info()
                if not lead_res.get("success"):
                    err_msg = f"Failed to get lead: {lead_res.get('error')}"
                    if callback: await callback("error", err_msg)
                    return {"success": False, "error": err_msg}
                lead_data = lead_res["data"]
                
                camp_info = {
                    "name": campaign.name,
                    "value_proposition": campaign.value_proposition,
                }
                lead_info = {
                    "name": lead_data.get("name", "Valued Contact"),
                    "email": lead_data.get("email"),
                    "company": lead_data.get("company", "Your Company"),
                    "industry": lead_data.get("industry", "Business"),
                    "pain_points": lead_data.get("pain_points", "Operational challenges")
                }
                
                # 3. Delegate to Drafter Agent
                msg = f"Delegating to DrafterAgent for lead: {lead_info['name']}..."
                logger.info(msg)
                if callback: await callback("info", msg)
                
                drafts = await run_drafter_agent(camp_info, lead_info)
                
                # 4. Delegate to Reviewer Agent
                msg = "Drafts generated. Reviewing and selecting best version..."
                logger.info(msg)
                if callback: await callback("info", msg)
                
                review_result = await run_reviewer_agent(camp_info, lead_info, drafts)
                
                # 5. Handle Email Delivery (Auto-approve vs Human Approval)
                if campaign.auto_approve_drafts:
                    msg = f"Auto-approve enabled. Sending '{review_result.selected_draft_type}' email to {lead_info['email']} directly..."
                    logger.info(msg)
                    if callback: await callback("info", msg)
                    
                    send_res = await send_plain_email(
                        email=lead_info["email"],
                        name=lead_info["name"],
                        subject=review_result.subject,
                        body=review_result.body
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
                            lead_service.update_lead_status(lead_id, "CONTACTED")

                        final_msg = "Database-driven outreach campaign completed successfully via Orchestrator (Auto-approved)"
                        logger.info(final_msg)
                        if callback: await callback("success", final_msg)
                        
                        return {
                            "success": True,
                            "message": f"Automated campaign executed using Orchestrator pattern. Sent {review_result.selected_draft_type} draft (Auto-approved).",
                            "agent_result": {
                                "rationale": review_result.rationale,
                                "selected_draft_type": review_result.selected_draft_type,
                                "sent_subject": review_result.subject,
                                "success": True
                            }
                        }
                    else:
                        err_msg = f"Email delivery failed: {send_res.error}"
                        if callback: await callback("error", err_msg)
                        return {"success": False, "error": send_res.error}
                else:
                    msg = f"Review complete. Saving '{review_result.selected_draft_type}' email draft for {lead_info['email']} to approval queue..."
                    logger.info(msg)
                    if callback: await callback("info", msg)
                    
                    try:
                        from utils.db_connection import get_conn
                        with get_conn() as conn:
                            conn.execute(
                                "INSERT INTO email_messages (lead_id, campaign_id, direction, subject, body, status, approved) VALUES (?, ?, 'outbound', ?, ?, 'DRAFT', 0)",
                                (lead_data.get("id"), campaign.id, review_result.subject, review_result.body)
                            )
                    except Exception as e:
                        logger.error(f"Failed to save draft to database: {e}")

                    lead_id = lead_data.get("id")
                    if lead_id:
                        lead_service.update_lead_touch(lead_id, campaign.id)

                    final_msg = "Draft generated and saved to approval queue."
                    logger.info(final_msg)
                    if callback: await callback("success", final_msg)
                    
                    return {
                        "success": True,
                        "message": f"Draft saved for human approval. Selected {review_result.selected_draft_type} draft.",
                        "agent_result": {
                            "rationale": review_result.rationale,
                            "selected_draft_type": review_result.selected_draft_type,
                            "sent_subject": review_result.subject,
                            "success": True
                        }
                    }
                    
        except Exception as e:
            err_msg = f"Campaign execution error: {str(e)}"
            logger.error(err_msg)
            if callback: await callback("error", err_msg)
            return {"success": False, "error": str(e)}

# Create global instance for API usage
outreach_orchestrator = OutreachOrchestrator()
