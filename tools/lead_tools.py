"""Tool wrappers for lead-related operations.

Each function returns a strict JSON structure:
{
    "success": bool,
    "data": ...,
    "error": null|string
}
"""
from typing import Dict, Any, Optional, List
from agents import function_tool
from services import lead_service
from schema import LeadOut


@function_tool
def get_leads_tool(campaign_id: Optional[int] = None, max_leads: Optional[int] = None, order_by: str = 'newest_first') -> Dict[str, Any]:
    """Get leads eligible for outreach.
    
    Args:
        campaign_id: Optional campaign ID to filter leads
        max_leads: Optional maximum number of leads to return
        order_by: Order to select leads ('newest_first', 'oldest_first', 'random')
        
    Returns:
        Dict with success status, lead data, and error if any
    """
    res = lead_service.get_leads(campaign_id=campaign_id, max_leads=max_leads, order_by=order_by)
    if not res.get("success"):
        return res
    raw = res.get("data") or []
    validated: List[LeadOut] = []
    errors = []
    for idx, item in enumerate(raw):
        try:
            validated.append(LeadOut(**item))
        except Exception as e:
            errors.append(f"item_{idx}: {str(e)}")
    if errors:
        return {"success": False, "data": None, "error": "; ".join(errors)}
    return {"success": True, "data": [l.model_dump() for l in validated], "error": None}


@function_tool
def update_lead_touch_tool(lead_id: int, campaign_id: int) -> Dict[str, Any]:
    """Update lead touch count and campaign email count.
    
    Args:
        lead_id: ID of the lead to update
        campaign_id: ID of the campaign
        
    Returns:
        Dict with success status, updated data, and error if any
    """
    if not isinstance(lead_id, int) or not isinstance(campaign_id, int):
        return {"success": False, "data": None, "error": "lead_id and campaign_id must be integers"}
    return lead_service.update_lead_touch(lead_id=lead_id, campaign_id=campaign_id)


@function_tool
def get_thread_tool(lead_id: int) -> Dict[str, Any]:
    """Get email thread for a specific lead.
    
    Args:
        lead_id: ID of the lead to get email thread for
        
    Returns:
        Dict with success status, email messages data, and error if any
    """
    if not isinstance(lead_id, int):
        return {"success": False, "data": None, "error": "lead_id must be an integer"}
    return lead_service.get_thread(lead_id=lead_id)


@function_tool
def update_lead_status_tool(lead_id: int, status: str) -> Dict[str, Any]:
    """Update lead status.
    
    Args:
        lead_id: ID of the lead to update
        status: New status for the lead
        
    Returns:
        Dict with success status, updated data, and error if any
    """
    if not isinstance(lead_id, int) or not isinstance(status, str):
        return {"success": False, "data": None, "error": "lead_id must be int and status must be string"}
    return lead_service.update_lead_status(lead_id=lead_id, status=status)


@function_tool
def log_event_tool(event_type: str, payload: Optional[str] = None, metadata: Optional[str] = None) -> Dict[str, Any]:
    """Log an event to the events table.
    
    Args:
        event_type: Type of the event to log
        payload: Optional event payload data
        metadata: Optional event metadata
        
    Returns:
        Dict with success status, logged data, and error if any
    """
    if not isinstance(event_type, str) or not event_type:
        return {"success": False, "data": None, "error": "event_type is required and must be a string"}
    return lead_service.log_event(event_type=event_type, payload=payload, metadata=metadata)


def fetch_lead_info(lead_id: Optional[int] = None) -> Dict[str, Any]:
    """Internal function to get a specific lead by ID or a random lead."""
    result = lead_service.get_lead(lead_id=lead_id)
    if result is None:
        return {"success": False, "data": None, "error": "Lead not found"}
    
    try:
        lead_out = LeadOut(**result)
        return {"success": True, "data": lead_out.model_dump(), "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": f"Validation error: {str(e)}"}

@function_tool
def get_lead_tool(lead_id: Optional[int] = None) -> Dict[str, Any]:
    """Get a specific lead by ID or a random lead.
    
    Args:
        lead_id: Optional ID of the lead to get. If None, returns a random lead.
        
    Returns:
        Dict with success status, lead data (name and email), and error if any
    """
    return fetch_lead_info(lead_id)
