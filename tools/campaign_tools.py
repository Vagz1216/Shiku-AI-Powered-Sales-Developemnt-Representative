"""Campaign tools for retrieving campaign information from database."""

import logging
import sqlite3
from typing import Optional

from agents import function_tool
from schema.outreach import CampaignInfo
from utils.db_connection import get_conn

logger = logging.getLogger(__name__)


def get_campaign_by_name(campaign_name: str) -> Optional[CampaignInfo]:
    """Get campaign details by name from database."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name, value_proposition, cta, status FROM campaigns WHERE name = ? AND status = 'ACTIVE'",
                (campaign_name,)
            )
            result = cur.fetchone()
            
            if result:
                return CampaignInfo(
                    id=result[0],
                    name=result[1],
                    value_proposition=result[2] or "",
                    cta=result[3] or "",
                    status=result[4]
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
                "SELECT id, name, value_proposition, cta, status FROM campaigns WHERE status = 'ACTIVE'"
            )
            results = cur.fetchall()
            
            campaigns = []
            for result in results:
                campaigns.append(CampaignInfo(
                    id=result[0],
                    name=result[1], 
                    value_proposition=result[2] or "",
                    cta=result[3] or "",
                    status=result[4]
                ))
            return campaigns
    except Exception as e:
        logger.error(f"Error fetching active campaigns: {e}")
        return []


@function_tool
def get_campaign_tool(campaign_name: Optional[str] = None) -> CampaignInfo:
    """Get campaign details from database.
    
    Args:
        campaign_name: Optional name of the specific campaign to retrieve. 
                       If None, a random active campaign is chosen.
    
    Returns:
        Campaign information including name, value proposition, and call-to-action
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if campaign_name:
                cur.execute(
                    "SELECT id, name, value_proposition, cta, status FROM campaigns WHERE name = ? AND status = 'ACTIVE'",
                    (campaign_name,)
                )
            else:
                cur.execute(
                    "SELECT id, name, value_proposition, cta, status FROM campaigns WHERE status = 'ACTIVE' ORDER BY RANDOM() LIMIT 1"
                )
            result = cur.fetchone()
            
            if result:
                return CampaignInfo(
                    id=result[0],
                    name=result[1],
                    value_proposition=result[2] or "",
                    cta=result[3] or "",
                    status=result[4]
                )
    except Exception as e:
        logger.error(f"Error fetching campaign: {e}")
    
    # Fallback if no campaigns in database
    return CampaignInfo(
        id=0,
        name="Default Campaign",
        value_proposition="Improve your business with our solution",
        cta="Learn more",
        status="ACTIVE"
    )