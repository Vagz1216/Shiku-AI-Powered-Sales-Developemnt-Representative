import httpx
import logging
from typing import List, Dict, Any
from .base import BaseDiscoverer, DiscoveredLead, ProviderFailure
from config.settings import settings

logger = logging.getLogger(__name__)

class PeopleDataLabsDiscoverer(BaseDiscoverer):
    """People Data Labs (PDL) API implementation for discovering leads.
    PDL offers a generous free tier of 1,000 API calls per month, making it
    an excellent fallback for the Apollo free plan limits.
    """
    
    BASE_URL = "https://api.peopledatalabs.com/v5/person/search"
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or getattr(settings, "pdl_api_key", None)
        if not self.api_key:
            logger.warning("PDL API key not set. Discovery will fail.")

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

    def _build_query(self, icp_params: Dict[str, Any]) -> Dict[str, Any]:
        """Translate ICP parameters into PDL's recommended Elasticsearch query shape."""
        titles = self._clean_list(icp_params.get("job_titles"), 4)
        industries = self._clean_list(icp_params.get("industries"), 3)
        locations = self._clean_list(icp_params.get("locations"), 3)
        seniorities = self._clean_list(icp_params.get("seniority_levels"), 4)

        must: list[dict[str, Any]] = []
        should: list[dict[str, Any]] = []

        email_should = [
            {"exists": {"field": "work_email"}},
            {"exists": {"field": "personal_emails"}},
        ]
        must.append({"bool": {"should": email_should, "minimum_should_match": 1}})

        if seniorities:
            must.append({"terms": {"job_title_levels": seniorities}})

        for industry in industries:
            should.append({"match_phrase": {"job_company_industry": industry}})
        for location in locations:
            should.append({"match_phrase": {"location_country": location}})
        for title in titles:
            should.append({"match_phrase": {"job_title": title}})

        query: dict[str, Any] = {"bool": {"must": must}}
        if should:
            query["bool"]["should"] = should
            query["bool"]["minimum_should_match"] = 1
        return query

    def _failure_from_response(self, response: httpx.Response) -> ProviderFailure:
        status = response.status_code
        message = self._safe_error_message(response)
        if status == 402:
            return ProviderFailure(
                "quota_exhausted",
                "PDL search credits are exhausted or billing is not enabled for this key.",
                retryable=False,
                user_visible=True,
            )
        if status in {401, 403}:
            return ProviderFailure("invalid_key", "PDL API key is invalid or unauthorized.", user_visible=True)
        if status == 400:
            return ProviderFailure("provider_payload_invalid", f"PDL rejected the search payload: {message}")
        if status == 429:
            return ProviderFailure("rate_limited", "PDL rate limit exceeded.", retryable=True, user_visible=True)
        if status >= 500:
            return ProviderFailure("provider_unavailable", "PDL is temporarily unavailable.", retryable=True)
        return ProviderFailure("provider_error", f"PDL request failed with HTTP {status}: {message}")

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
            raise ProviderFailure("missing_key", "PDL_API_KEY is not configured", user_visible=True)
            
        query = self._build_query(icp_params)
        logger.info("Generated PDL Search Query: %s", query)
        
        payload = {
            "query": query,
            "size": min(limit, getattr(settings, "pdl_max_search_size", 10), 100),
        }
        
        headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        # Log the outgoing API Key mask (last 4 characters) to verify .env matches the dashboard
        key_suffix = self.api_key[-4:] if len(self.api_key) >= 4 else "****"
        logger.info(f"Sending request to PDL using API Key ending in: {key_suffix}")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.BASE_URL, json=payload, headers=headers, timeout=30.0)
        except httpx.TimeoutException as exc:
            raise ProviderFailure("timeout", "PDL request timed out.", retryable=True) from exc
        except httpx.RequestError as exc:
            raise ProviderFailure("network_error", f"PDL network error: {exc}", retryable=True) from exc
            
        if response.status_code != 200:
            logger.warning("PDL request failed with HTTP %s: %s", response.status_code, self._safe_error_message(response))
            raise self._failure_from_response(response)
                
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderFailure("invalid_response", "PDL returned malformed JSON.", retryable=True) from exc
            
        def safe_str(val: Any, default: Any = None) -> Any:
            if isinstance(val, bool) or val is None:
                return default
            return str(val).strip()

        results = []
        for person in data.get("data", []):
            work_email = person.get("work_email")
            personal_emails = person.get("personal_emails", [])

            if isinstance(work_email, bool):
                work_email = None

            if isinstance(personal_emails, bool) or not isinstance(personal_emails, list):
                personal_emails = []

            resolved_email = work_email or (personal_emails[0] if personal_emails else None)
            if isinstance(resolved_email, bool):
                resolved_email = None

            if not resolved_email:
                continue

            job = safe_str(person.get("job_company_name"))
            title = safe_str(person.get("job_title"))

            raw_location = person.get("location_locality") or person.get("location_country") or person.get("location_name")
            resolved_location = safe_str(raw_location)

            seniority_list = person.get("job_title_levels")
            seniority = None
            if isinstance(seniority_list, list) and len(seniority_list) > 0:
                seniority = safe_str(seniority_list[0])
                
            lead = DiscoveredLead(
                name=safe_str(person.get("full_name")),
                email=safe_str(resolved_email),
                phone_number=safe_str(person.get("mobile_phone") or person.get("phone_number")),
                linkedin_url=safe_str(person.get("linkedin_url")),
                job_title=title,
                seniority=seniority,
                location=resolved_location,
                company=job,
                industry=safe_str(person.get("job_company_industry")),
                company_website=safe_str(person.get("job_company_website")),
                company_description=safe_str(person.get("job_company_description")),
                company_size=safe_str(person.get("job_company_size")),
                discovery_source="pdl"
            )
            results.append(lead)
                
        return results
