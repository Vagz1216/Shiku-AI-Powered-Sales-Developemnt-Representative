"""Campaign tools for retrieving campaign information from database."""

import logging
from typing import Optional

from agents import function_tool
from schema.outreach import CampaignInfo, CampaignCreate, CampaignUpdate
from utils.db_connection import get_conn, sql_random_order, using_aurora

logger = logging.getLogger(__name__)

_CAMP_COLS = (
    "id",
    "name",
    "value_proposition",
    "cta",
    "status",
    "meeting_delay_days",
    "max_leads_per_campaign",
    "lead_selection_order",
    "auto_approve_drafts",
    "max_emails_per_lead",
)


def _camp_tuple(row) -> Optional[tuple]:
    if row is None:
        return None
    if isinstance(row, dict):
        return tuple(row[c] for c in _CAMP_COLS)
    return tuple(row[i] for i in range(10))


def _to_campaign_info(t: tuple) -> CampaignInfo:
    return CampaignInfo(
        id=t[0],
        name=t[1],
        value_proposition=t[2] or "",
        cta=t[3] or "",
        status=t[4],
        meeting_delay_days=t[5],
        max_leads_per_campaign=t[6],
        lead_selection_order=t[7],
        auto_approve_drafts=bool(t[8]),
        max_emails_per_lead=t[9],
    )


def get_campaign_by_name(campaign_name: str) -> Optional[CampaignInfo]:
    """Get campaign details by name from database."""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE name = ? AND status = 'ACTIVE'",
                (campaign_name,),
            )
            t = _camp_tuple(cur.fetchone())
            if t:
                return _to_campaign_info(t)
            return None
    except Exception as e:
        logger.error(f"Error fetching campaign by name: {e}")
        return None


def get_active_campaigns() -> list[CampaignInfo]:
    """Get all active campaigns from database."""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE status = 'ACTIVE'"
            )
            return [_to_campaign_info(_camp_tuple(r)) for r in cur.fetchall() if _camp_tuple(r)]
    except Exception as e:
        logger.error(f"Error fetching active campaigns: {e}")
        return []


def get_all_campaigns() -> list[CampaignInfo]:
    """Get all campaigns (any status) from database."""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns"
            )
            return [_to_campaign_info(_camp_tuple(r)) for r in cur.fetchall() if _camp_tuple(r)]
    except Exception as e:
        logger.error(f"Error fetching all campaigns: {e}")
        return []


def create_campaign(campaign: CampaignCreate) -> Optional[CampaignInfo]:
    """Create a new campaign in the database."""
    try:
        with get_conn() as conn:
            params = (
                campaign.name,
                campaign.value_proposition,
                campaign.cta,
                campaign.status,
                campaign.meeting_delay_days,
                campaign.max_leads_per_campaign,
                campaign.lead_selection_order,
                campaign.auto_approve_drafts,
                campaign.max_emails_per_lead,
            )
            if using_aurora():
                cur = conn.execute(
                    """
                    INSERT INTO campaigns (
                        name, value_proposition, cta, status, meeting_delay_days,
                        max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id, name, value_proposition, cta, status, meeting_delay_days,
                        max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead
                    """,
                    params,
                )
                row = cur.fetchone()
                t = _camp_tuple(row)
                return _to_campaign_info(t) if t else None

            cur = conn.execute(
                """
                INSERT INTO campaigns (
                    name, value_proposition, cta, status, meeting_delay_days,
                    max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
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
                max_emails_per_lead=campaign.max_emails_per_lead,
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
            update_fields.append(f"{key} = ?")
            update_values.append(value)

        update_values.append(campaign_id)

        with get_conn() as conn:
            set_clause = ", ".join(update_fields)
            if using_aurora():
                # Data API often does not populate numberOfRecordsUpdated for UPDATE; use RETURNING.
                cols_sql = ", ".join(_CAMP_COLS)
                cur = conn.execute(
                    f"UPDATE campaigns SET {set_clause} WHERE id = ? RETURNING {cols_sql}",
                    tuple(update_values),
                )
                row = cur.fetchone()
                t = _camp_tuple(row)
                return _to_campaign_info(t) if t else None

            cur = conn.execute(
                f"UPDATE campaigns SET {set_clause} WHERE id = ?",
                tuple(update_values),
            )
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
            cur = conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting campaign {campaign_id}: {e}")
        return False


def get_campaign_by_id(campaign_id: int) -> Optional[CampaignInfo]:
    """Get campaign details by ID from database."""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE id = ?",
                (campaign_id,),
            )
            t = _camp_tuple(cur.fetchone())
            if t:
                return _to_campaign_info(t)
            return None
    except Exception as e:
        logger.error(f"Error fetching campaign by id: {e}")
        return None


def fetch_campaign_info(campaign_name: Optional[str] = None) -> CampaignInfo:
    """Internal function to get campaign details from database."""
    try:
        rnd = sql_random_order()
        with get_conn() as conn:
            if campaign_name:
                cur = conn.execute(
                    "SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE name = ? AND status = 'ACTIVE'",
                    (campaign_name,),
                )
            else:
                cur = conn.execute(
                    f"SELECT id, name, value_proposition, cta, status, meeting_delay_days, max_leads_per_campaign, lead_selection_order, auto_approve_drafts, max_emails_per_lead FROM campaigns WHERE status = 'ACTIVE' ORDER BY {rnd} LIMIT 1"
                )
            t = _camp_tuple(cur.fetchone())
            if t:
                return _to_campaign_info(t)
    except Exception as e:
        logger.error(f"Error fetching campaign: {e}")

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
        max_emails_per_lead=5,
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
