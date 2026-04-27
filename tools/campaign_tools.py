"""Campaign tools for retrieving campaign information from database."""

import logging
import sqlite3
from typing import Optional

from agents import function_tool
from schema.outreach import CampaignInfo, CampaignCreate, CampaignUpdate
from utils.db_connection import get_conn

logger = logging.getLogger(__name__)


def get_campaign_by_name(campaign_name: str) -> Optional[CampaignInfo]:
    """Get campaign details by name from database."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE name = ? AND status = 'ACTIVE'",
                (campaign_name,)
            )
            result = cur.fetchone()
            
            if result:
                return CampaignInfo(
                    id=result[0],
                    name=result[1],
                    value_proposition=result[2] or "",
                    cta=result[3] or "",
                    status=result[4],
                    meeting_delay_days=result[5],
                    max_leads_per_campaign=result[6],
                    lead_selection_order=result[7],
                    auto_approve_drafts=bool(result[8]),
                    max_emails_per_lead=result[9]
                )
            return None
    except Exception as e:
        logger.error(f"Error fetching campaign by name: {e}")
        return None


def get_active_campaigns() -> list[CampaignInfo]:
    """Get all active campaigns from database."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE status = 'ACTIVE'"
            )
            results = cur.fetchall()
            
            campaigns = []
            for result in results:
                campaigns.append(CampaignInfo(
                    id=result[0],
                    name=result[1], 
                    value_proposition=result[2] or "",
                    cta=result[3] or "",
                    status=result[4],
                    meeting_delay_days=result[5],
                    max_leads_per_campaign=result[6],
                    lead_selection_order=result[7],
                    auto_approve_drafts=bool(result[8]),
                    max_emails_per_lead=result[9]
                ))
            return campaigns
    except Exception as e:
        logger.error(f"Error fetching active campaigns: {e}")
        return []


def get_all_campaigns() -> list[CampaignInfo]:
    """Get all campaigns (any status) from database."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns"
            )
            results = cur.fetchall()
            
            campaigns = []
            for result in results:
                campaigns.append(CampaignInfo(
                    id=result[0],
                    name=result[1], 
                    value_proposition=result[2] or "",
                    cta=result[3] or "",
                    status=result[4],
                    meeting_delay_days=result[5],
                    max_leads_per_campaign=result[6],
                    lead_selection_order=result[7],
                    auto_approve_drafts=bool(result[8]),
                    max_emails_per_lead=result[9]
                ))
            return campaigns
    except Exception as e:
        logger.error(f"Error fetching all campaigns: {e}")
        return []


def create_campaign(campaign: CampaignCreate) -> Optional[CampaignInfo]:
    """Create a new campaign in the database."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO campaigns (
                    name, value_proposition, cta, status, meeting_delay_days, 
                    max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign.name, campaign.value_proposition, campaign.cta, campaign.status, 
                    campaign.meeting_delay_days, campaign.max_leads_per_campaign, 
                    campaign.lead_selection_order, 1 if campaign.auto_approve_drafts else 0,
                    campaign.max_emails_per_lead
                )
            )
            campaign_id = cur.lastrowid
            
            return CampaignInfo(
                id=campaign_id,
                name=campaign.name,
                value_proposition=campaign.value_proposition,
                cta=campaign.cta,
                status=campaign.status,
                meeting_delay_days=campaign.meeting_delay_days,
                max_leads_per_campaign=campaign.max_leads_per_campaign,
                lead_selection_order=campaign.lead_selection_order,
                auto_approve_drafts=campaign.auto_approve_drafts,
                max_emails_per_lead=campaign.max_emails_per_lead
            )
    except Exception as e:
        logger.error(f"Error creating campaign: {e}")
        return None


def update_campaign(campaign_id: int, updates: CampaignUpdate) -> Optional[CampaignInfo]:
    """Update an existing campaign in the database."""
    try:
        update_fields = []
        update_values = []
        update_dict = updates.model_dump(exclude_unset=True)
        
        if not update_dict:
            return get_campaign_by_id(campaign_id)
            
        for key, value in update_dict.items():
            if key == "auto_approve_drafts":
                value = 1 if value else 0
            update_fields.append(f"{key} = ?")
            update_values.append(value)
            
        update_values.append(campaign_id)
        
        with get_conn() as conn:
            cur = conn.cursor()
            query = f"UPDATE campaigns SET {', '.join(update_fields)} WHERE id = ?"
            cur.execute(query, tuple(update_values))
            
            if cur.rowcount > 0:
                return get_campaign_by_id(campaign_id)
            return None
    except Exception as e:
        logger.error(f"Error updating campaign {campaign_id}: {e}")
        return None


def delete_campaign(campaign_id: int) -> bool:
    """Delete a campaign from the database."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting campaign {campaign_id}: {e}")
        return False


def get_campaign_by_id(campaign_id: int) -> Optional[CampaignInfo]:
    """Get campaign details by ID from database."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE id = ?",
                (campaign_id,)
            )
            result = cur.fetchone()
            
            if result:
                return CampaignInfo(
                    id=result[0],
                    name=result[1],
                    value_proposition=result[2] or "",
                    cta=result[3] or "",
                    status=result[4],
                    meeting_delay_days=result[5],
                    max_leads_per_campaign=result[6],
                    lead_selection_order=result[7],
                    auto_approve_drafts=bool(result[8]),
                    max_emails_per_lead=result[9]
                )
            return None
    except Exception as e:
        logger.error(f"Error fetching campaign by id: {e}")
        return None


def fetch_campaign_info(campaign_name: Optional[str] = None) -> CampaignInfo:
    """Internal function to get campaign details from database."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if campaign_name:
                cur.execute(
                    "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE name = ? AND status = 'ACTIVE'",
                    (campaign_name,)
                )
            else:
                cur.execute(
                    "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE status = 'ACTIVE' ORDER BY RANDOM() LIMIT 1"
                )
            result = cur.fetchone()
            
            if result:
                return CampaignInfo(
                    id=result[0],
                    name=result[1],
                    value_proposition=result[2] or "",
                    cta=result[3] or "",
                    status=result[4],
                    meeting_delay_days=result[5],
                    max_leads_per_campaign=result[6],
                    lead_selection_order=result[7],
                    auto_approve_drafts=bool(result[8]),
                    max_emails_per_lead=result[9]
                )
    except Exception as e:
        logger.error(f"Error fetching campaign: {e}")
    
    # Fallback if no campaigns in database
    return CampaignInfo(
        id=0,
        name="Default Campaign",
        value_proposition="Improve your business with our solution",
        cta="Learn more",
        status="ACTIVE",
        meeting_delay_days=1,
        max_leads_per_campaign=None,
        lead_selection_order="newest_first",
        auto_approve_drafts=False,
        max_emails_per_lead=5
    )

@function_tool
def get_campaign_tool(campaign_name: Optional[str] = None) -> CampaignInfo:
    """Get campaign details from database.
    
    Args:
        campaign_name: Optional name of the specific campaign to retrieve. 
                       If None, a random active campaign is chosen.
    
    Returns:
        Campaign information including name, value proposition, and call-to-action
    """
    return fetch_campaign_info(campaign_name)