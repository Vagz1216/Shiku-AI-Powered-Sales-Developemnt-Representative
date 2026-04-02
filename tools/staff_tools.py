"""Tool wrappers for staff-related operations.

Each function returns a strict JSON structure:
{
    "success": bool,
    "data": ...,
    "error": null|string
}
"""
from typing import Dict, Any, Optional
from agents import function_tool
from services import staff_service
from schema import StaffOut


@function_tool
def get_staff_tool(staff_id: Optional[int] = None) -> Dict[str, Any]:
    """Get a specific staff member by ID or a random staff member.
    
    Args:
        staff_id: Optional ID of the staff member to get. If None, returns a random staff member.
        
    Returns:
        Dict with success status, staff data (name and email), and error if any
    """
    result = staff_service.get_staff(staff_id=staff_id)
    if result is None:
        return {"success": False, "data": None, "error": "Staff member not found"}
    
    try:
        staff_out = StaffOut(**result)
        return {"success": True, "data": staff_out.model_dump(), "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": f"Validation error: {str(e)}"}