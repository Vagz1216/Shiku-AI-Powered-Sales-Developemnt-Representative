"""Campaign tools for retrieving campaign information from database."""

import logging
from typing import Optional

from agents import function_tool
from schema.outreach import CampaignInfo, CampaignCreate, CampaignUpdate
from utils.db_connection import get_conn, sql_random_order, using_postgres

logger = logging.getLogger(__name__)

_CAMP_COLS = (
    "id",
    "organization_id",
    "name",
    "value_proposition",
    "cta",
    "status",
    "meeting_delay_days",
    "max_leads_per_campaign",
    "lead_selection_order",
    "auto_approve_drafts",
    "auto_approve_monitor_replies",
    "max_emails_per_lead",
)


def _camp_tuple(row) -> Optional[tuple]:
    if row is None:
        return None
    if isinstance(row, dict):
        return tuple(row[c] for c in _CAMP_COLS)
    return tuple(row[i] for i in range(len(_CAMP_COLS)))


def _camp_select_cols() -> str:
    return ", ".join(_CAMP_COLS)


def _to_campaign_info(t: tuple) -> CampaignInfo:
    return CampaignInfo(
        id=t[0],
        organization_id=t[1],
        name=t[2],
        value_proposition=t[3] or "",
        cta=t[4] or "",
        status=t[5],
        meeting_delay_days=t[6],
        max_leads_per_campaign=t[7],
        lead_selection_order=t[8],
        auto_approve_drafts=bool(t[9]),
        auto_approve_monitor_replies=bool(t[10]),
        max_emails_per_lead=t[11],
    )


def get_campaign_by_name(campaign_name: str, organization_id: int | None = None) -> Optional[CampaignInfo]:
    """Get campaign details by name from database."""
    try:
        with get_conn() as conn:
            params: list[object] = [campaign_name]
            where = "name = ? AND status = 'ACTIVE'"
            if organization_id is not None:
                where += " AND organization_id = ?"
                params.append(organization_id)
            cur = conn.execute(f"SELECT {_camp_select_cols()} FROM campaigns WHERE {where}", tuple(params))
            t = _camp_tuple(cur.fetchone())
            if t:
                return _to_campaign_info(t)
            return None
    except Exception as e:
        logger.error(f"Error fetching campaign by name: {e}")
        return None


def get_active_campaigns(organization_id: int | None = None) -> list[CampaignInfo]:
    """Get all active campaigns from database."""
    try:
        with get_conn() as conn:
            if organization_id is None:
                cur = conn.execute(f"SELECT {_camp_select_cols()} FROM campaigns WHERE status = 'ACTIVE'")
            else:
                cur = conn.execute(
                    f"SELECT {_camp_select_cols()} FROM campaigns WHERE status = 'ACTIVE' AND organization_id = ?",
                    (organization_id,),
                )
            return [_to_campaign_info(_camp_tuple(r)) for r in cur.fetchall() if _camp_tuple(r)]
    except Exception as e:
        logger.error(f"Error fetching active campaigns: {e}")
        return []


def get_all_campaigns(organization_id: int | None = None) -> list[CampaignInfo]:
    """Get all campaigns (any status) from database."""
    try:
        with get_conn() as conn:
            if organization_id is None:
                cur = conn.execute(f"SELECT {_camp_select_cols()} FROM campaigns")
            else:
                cur = conn.execute(
                    f"SELECT {_camp_select_cols()} FROM campaigns WHERE organization_id = ?",
                    (organization_id,),
                )
            return [_to_campaign_info(_camp_tuple(r)) for r in cur.fetchall() if _camp_tuple(r)]
    except Exception as e:
        logger.error(f"Error fetching all campaigns: {e}")
        return []


def create_campaign(campaign: CampaignCreate, organization_id: int = 1) -> Optional[CampaignInfo]:
    """Create a new campaign in the database."""
    try:
        with get_conn() as conn:
            params = (
                organization_id,
                campaign.name,
                campaign.value_proposition,
                campaign.cta,
                campaign.status,
                campaign.meeting_delay_days,
                campaign.max_leads_per_campaign,
                campaign.lead_selection_order,
                campaign.auto_approve_drafts,
                campaign.auto_approve_monitor_replies,
                campaign.max_emails_per_lead,
            )
            if using_postgres():
                cur = conn.execute(
                    """
                    INSERT INTO campaigns (
                        organization_id, name, value_proposition, cta, status, meeting_delay_days,
                        max_leads_per_campaign, lead_selection_order, auto_approve_drafts,
                        auto_approve_monitor_replies, max_emails_per_lead
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id, organization_id, name, value_proposition, cta, status, meeting_delay_days,
                        max_leads_per_campaign, lead_selection_order, auto_approve_drafts,
                        auto_approve_monitor_replies, max_emails_per_lead
                    """,
                    params,
                )
                row = cur.fetchone()
                t = _camp_tuple(row)
                return _to_campaign_info(t) if t else None

            cur = conn.execute(
                """
                INSERT INTO campaigns (
                    organization_id, name, value_proposition, cta, status, meeting_delay_days,
                    max_leads_per_campaign, lead_selection_order, auto_approve_drafts,
                    auto_approve_monitor_replies, max_emails_per_lead
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            campaign_id = cur.lastrowid
            return CampaignInfo(
                id=campaign_id,
                organization_id=organization_id,
                name=campaign.name,
                value_proposition=campaign.value_proposition,
                cta=campaign.cta,
                status=campaign.status,
                meeting_delay_days=campaign.meeting_delay_days,
                max_leads_per_campaign=campaign.max_leads_per_campaign,
                lead_selection_order=campaign.lead_selection_order,
                auto_approve_drafts=campaign.auto_approve_drafts,
                auto_approve_monitor_replies=campaign.auto_approve_monitor_replies,
                max_emails_per_lead=campaign.max_emails_per_lead,
            )
    except Exception as e:
        logger.error(f"Error creating campaign: {e}")
        return None


def update_campaign(campaign_id: int, updates: CampaignUpdate, organization_id: int | None = None) -> Optional[CampaignInfo]:
    """Update an existing campaign in the database."""
    try:
        update_fields = []
        update_values = []
        update_dict = updates.model_dump(exclude_unset=True)

        if not update_dict:
            return get_campaign_by_id(campaign_id, organization_id)

        for key, value in update_dict.items():
            update_fields.append(f"{key} = ?")
            update_values.append(value)

        update_values.append(campaign_id)

        with get_conn() as conn:
            set_clause = ", ".join(update_fields)
            if using_postgres():
                # PostgreSQL/Data API may not expose useful rowcount consistently; use RETURNING.
                cols_sql = ", ".join(_CAMP_COLS)
                where = "id = ?"
                if organization_id is not None:
                    update_values.append(organization_id)
                    where += " AND organization_id = ?"
                cur = conn.execute(f"UPDATE campaigns SET {set_clause} WHERE {where} RETURNING {cols_sql}", tuple(update_values))
                row = cur.fetchone()
                t = _camp_tuple(row)
                return _to_campaign_info(t) if t else None

            where = "id = ?"
            if organization_id is not None:
                update_values.append(organization_id)
                where += " AND organization_id = ?"
            cur = conn.execute(f"UPDATE campaigns SET {set_clause} WHERE {where}", tuple(update_values))
            if cur.rowcount > 0:
                return get_campaign_by_id(campaign_id, organization_id)
            return None
    except Exception as e:
        logger.error(f"Error updating campaign {campaign_id}: {e}")
        return None


def delete_campaign(campaign_id: int, organization_id: int | None = None) -> bool:
    """Delete a campaign from the database."""
    try:
        with get_conn() as conn:
            if organization_id is None:
                cur = conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
            else:
                cur = conn.execute(
                    "DELETE FROM campaigns WHERE id = ? AND organization_id = ?",
                    (campaign_id, organization_id),
                )
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting campaign {campaign_id}: {e}")
        return False


def get_campaign_by_id(campaign_id: int, organization_id: int | None = None) -> Optional[CampaignInfo]:
    """Get campaign details by ID from database."""
    try:
        with get_conn() as conn:
            if organization_id is None:
                cur = conn.execute(f"SELECT {_camp_select_cols()} FROM campaigns WHERE id = ?", (campaign_id,))
            else:
                cur = conn.execute(
                    f"SELECT {_camp_select_cols()} FROM campaigns WHERE id = ? AND organization_id = ?",
                    (campaign_id, organization_id),
                )
            t = _camp_tuple(cur.fetchone())
            if t:
                return _to_campaign_info(t)
            return None
    except Exception as e:
        logger.error(f"Error fetching campaign by id: {e}")
        return None


def fetch_campaign_info(campaign_name: Optional[str] = None, organization_id: int | None = None) -> CampaignInfo | None:
    """Internal function to get campaign details from database."""
    try:
        rnd = sql_random_order()
        with get_conn() as conn:
            if campaign_name:
                params: list[object] = [campaign_name]
                where = "name = ? AND status = 'ACTIVE'"
                if organization_id is not None:
                    where += " AND organization_id = ?"
                    params.append(organization_id)
                cur = conn.execute(f"SELECT {_camp_select_cols()} FROM campaigns WHERE {where}", tuple(params))
            else:
                params = []
                where = "status = 'ACTIVE'"
                if organization_id is not None:
                    where += " AND organization_id = ?"
                    params.append(organization_id)
                cur = conn.execute(
                    f"SELECT {_camp_select_cols()} FROM campaigns WHERE {where} ORDER BY {rnd} LIMIT 1",
                    tuple(params),
                )
            t = _camp_tuple(cur.fetchone())
            if t:
                return _to_campaign_info(t)
    except Exception as e:
        logger.error(f"Error fetching campaign: {e}")

    return None


@function_tool
def get_campaign_tool(campaign_name: Optional[str] = None) -> CampaignInfo:
    """Get campaign details from database.

    Args:
        campaign_name: Optional name of the specific campaign to retrieve.
                       If None, a random active campaign is chosen.

    Returns:
        Campaign information including name, value proposition, and call-to-action
    """
    return fetch_campaign_info(campaign_name) or CampaignInfo(
        id=0,
        organization_id=1,
        name="Default Campaign",
        value_proposition="Improve your business with our solution",
        cta="Learn more",
        status="ACTIVE",
        meeting_delay_days=1,
        max_leads_per_campaign=None,
        lead_selection_order="newest_first",
        auto_approve_drafts=False,
        auto_approve_monitor_replies=False,
        max_emails_per_lead=5,
    )
