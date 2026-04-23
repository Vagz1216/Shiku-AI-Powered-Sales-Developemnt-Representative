from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class LeadProvider(ABC):
    """Abstract base class for lead data operations.
    
    This implements the Adapter pattern allowing us to switch between
    a local database, Aurora Serverless, or an external CRM (like HubSpot).
    """

    @abstractmethod
    def get_leads(self, email_cap: int = 5) -> Dict[str, Any]:
        """Return leads eligible for outreach."""
        pass

    @abstractmethod
    def update_lead_touch(self, lead_id: int, campaign_id: int) -> Dict[str, Any]:
        """Increment touch_count and update last_contacted_at."""
        pass

    @abstractmethod
    def get_thread(self, lead_id: int) -> Dict[str, Any]:
        """Get email thread for a lead."""
        pass

    @abstractmethod
    def update_lead_status(self, lead_id: int, status: str) -> Dict[str, Any]:
        """Update the status of a lead."""
        pass

    @abstractmethod
    def log_event(self, event_type: str, payload: Optional[str] = None, metadata: Optional[str] = None) -> Dict[str, Any]:
        """Log an event."""
        pass

    @abstractmethod
    def get_lead(self, lead_id: Optional[int] = None) -> Optional[dict]:
        """Return a specific lead or a random one."""
        pass
