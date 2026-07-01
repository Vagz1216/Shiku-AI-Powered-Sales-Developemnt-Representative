import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, model_validator


class ProviderFailure(Exception):
    """Typed external provider failure used by the lead scout fallback chain."""

    def __init__(self, code: str, message: str, *, retryable: bool = False, user_visible: bool = False):
        self.code = code
        self.retryable = retryable
        self.user_visible = user_visible
        super().__init__(message)


@dataclass(frozen=True)
class ProviderCooldown:
    code: str
    message: str
    until_monotonic: float


_PROVIDER_COOLDOWNS: dict[str, ProviderCooldown] = {}


def provider_cooldown(provider_name: str) -> ProviderCooldown | None:
    cooldown = _PROVIDER_COOLDOWNS.get(provider_name)
    if not cooldown:
        return None
    if cooldown.until_monotonic <= time.monotonic():
        _PROVIDER_COOLDOWNS.pop(provider_name, None)
        return None
    return cooldown


def remember_provider_failure(provider_name: str, failure: ProviderFailure, cooldown_seconds: int) -> None:
    if cooldown_seconds <= 0 or failure.retryable:
        return
    _PROVIDER_COOLDOWNS[provider_name] = ProviderCooldown(
        code=failure.code,
        message=str(failure),
        until_monotonic=time.monotonic() + cooldown_seconds,
    )


def clear_provider_cooldowns() -> None:
    _PROVIDER_COOLDOWNS.clear()

class DiscoveredLead(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    linkedin_url: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None
    pain_points: Optional[str] = None
    job_title: Optional[str] = None
    seniority: Optional[str] = None
    location: Optional[str] = None
    company_size: Optional[str] = None
    company_website: Optional[str] = None
    company_description: Optional[str] = None
    recent_activity: Optional[str] = None
    discovery_source: str

    @model_validator(mode="before")
    @classmethod
    def sanitize_api_data(cls, data: Any) -> Any:
        """
        Sanitize incoming dictionary data before validation.
        Prevents crashes from APIs returning `True`/`False` for masked string fields.
        """
        if isinstance(data, dict):
            for key, value in list(data.items()):
                # Convert boolean values to None (handles API mask flags)
                if isinstance(value, bool):
                    data[key] = None
                
                # Normalize strings
                elif isinstance(value, str):
                    stripped = value.strip()
                    if not stripped:
                        data[key] = None
                    else:
                        data[key] = stripped

        return data

    def to_import_payload(self, campaign_id: int) -> Dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "phone_number": self.phone_number,
            "linkedin_url": self.linkedin_url,
            "company": self.company,
            "industry": self.industry,
            "pain_points": self.pain_points,
            "job_title": self.job_title,
            "seniority": self.seniority,
            "location": self.location,
            "company_size": self.company_size,
            "company_website": self.company_website,
            "company_description": self.company_description,
            "recent_activity": self.recent_activity,
            "status": "NEW",
            "campaign_ids": [campaign_id],
            "enrichment_source": self.discovery_source,
        }

class BaseDiscoverer(ABC):
    """Abstract base class for all lead discovery data sources (Apollo, SerpAPI, etc)."""
    
    @abstractmethod
    async def search_leads(self, icp_params: Dict[str, Any], limit: int = 50) -> List[DiscoveredLead]:
        """
        Search for leads based on ICP parameters.
        
        Args:
            icp_params: Dictionary of search parameters (titles, industries, etc)
            limit: Maximum number of leads to return
            
        Returns:
            List of DiscoveredLead objects
        """
        pass
