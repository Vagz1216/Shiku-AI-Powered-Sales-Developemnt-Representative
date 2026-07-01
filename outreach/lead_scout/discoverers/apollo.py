import httpx
import logging
from typing import List, Dict, Any
from .base import BaseDiscoverer, DiscoveredLead, ProviderFailure
from config.settings import settings

logger = logging.getLogger(__name__)

class ApolloDiscoverer(BaseDiscoverer):
    """Apollo.io API implementation for discovering leads."""
    
    BASE_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or getattr(settings, "apollo_api_key", None)
        if not self.api_key:
            logger.warning("Apollo API key not set. Discovery will fail.")

    def _clean_list(self, values: Any, limit: int) -> list[str]:
        if not isinstance(values, list):
            return []
        cleaned = []
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = " ".join(value.split()).strip()
            if normalized:
                cleaned.append(normalized)
        return cleaned[:limit]

    def _failure_from_response(self, response: httpx.Response) -> ProviderFailure:
        status = response.status_code
        message = self._safe_error_message(response)
        if status in {401, 403}:
            return ProviderFailure("invalid_key", "Apollo API key is invalid or unauthorized.", user_visible=True)
        if status == 402:
            return ProviderFailure("quota_exhausted", "Apollo credits or billing are exhausted.", user_visible=True)
        if status == 422:
            return ProviderFailure("provider_payload_invalid", f"Apollo rejected the search payload: {message}")
        if status == 429:
            return ProviderFailure("rate_limited", "Apollo rate limit exceeded.", retryable=True, user_visible=True)
        if status >= 500:
            return ProviderFailure("provider_unavailable", "Apollo is temporarily unavailable.", retryable=True)
        return ProviderFailure("provider_error", f"Apollo request failed with HTTP {status}: {message}")

    def _safe_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:300]
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value[:300]
        return str(payload)[:300]

    async def search_leads(self, icp_params: Dict[str, Any], limit: int = 50) -> List[DiscoveredLead]:
        if not self.api_key:
            raise ProviderFailure("missing_key", "APOLLO_API_KEY is not configured", user_visible=True)

        keywords = self._clean_list(icp_params.get("keywords"), 6)
        industries = self._clean_list(icp_params.get("industries"), 4)
        all_keywords = keywords + industries
        
        payload = {
            "person_titles": self._clean_list(icp_params.get("job_titles"), 6),
            "organization_num_employees_ranges": self._clean_list(icp_params.get("company_size_ranges"), 5),
            "person_locations": self._clean_list(icp_params.get("locations"), 5),
            "person_seniorities": self._clean_list(icp_params.get("seniority_levels"), 5),
            "q_keywords": " ".join(all_keywords),
            "per_page": min(limit, 100) # Apollo limit per page
        }
        
        # Clean up empty lists to not break Apollo's search
        payload = {k: v for k, v in payload.items() if v}

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.BASE_URL, json=payload, headers=headers, timeout=30.0)
        except httpx.TimeoutException as exc:
            raise ProviderFailure("timeout", "Apollo request timed out.", retryable=True) from exc
        except httpx.RequestError as exc:
            raise ProviderFailure("network_error", f"Apollo network error: {exc}", retryable=True) from exc

        if response.status_code != 200:
            logger.warning(
                "Apollo request failed with HTTP %s: %s",
                response.status_code,
                self._safe_error_message(response),
            )
            raise self._failure_from_response(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderFailure("invalid_response", "Apollo returned malformed JSON.", retryable=True) from exc
            
        results = []
            
        def safe_str(val: Any, default: Any = None) -> Any:
            if isinstance(val, bool) or val is None:
                return default
            return str(val).strip()
                
        people = data.get("people") or data.get("contacts") or []
        for person in people:
            org = person.get("organization") or {}
                
            city = safe_str(person.get("city"), "")
            state = safe_str(person.get("state"), "")
            country = safe_str(person.get("country"), "")
            location_parts = [p for p in [city, state, country] if p]
            location = ", ".join(location_parts) if location_parts else None

            email = safe_str(person.get("email"))
            if not email:
                continue
                
            lead = DiscoveredLead(
                name=safe_str(f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()),
                email=email,
                phone_number=safe_str(person.get("sanitized_phone") or person.get("phone_number")),
                linkedin_url=safe_str(person.get("linkedin_url")),
                job_title=safe_str(person.get("title")),
                seniority=safe_str(person.get("seniority")),
                location=location,
                company=safe_str(org.get("name")),
                industry=safe_str(org.get("primary_industry") or person.get("industry")),
                company_website=safe_str(org.get("website_url")),
                company_description=safe_str(org.get("short_description")),
                company_size=safe_str(org.get("estimated_num_employees")),
                discovery_source="apollo"
            )
            results.append(lead)
                
        return results
