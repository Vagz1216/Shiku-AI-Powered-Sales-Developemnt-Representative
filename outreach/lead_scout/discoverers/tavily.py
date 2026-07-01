import asyncio
import logging
from typing import List
from urllib.parse import urlparse

import httpx

from config.settings import settings
from .base import DiscoveredLead

logger = logging.getLogger(__name__)


class TavilySignalEnricher:
    """Use Tavily for lightweight company/activity enrichment on discovered leads."""

    BASE_URL = "https://api.tavily.com/search"
    MAX_ENRICHMENTS = 5
    NOISY_DOMAINS = (
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "x.com",
        "twitter.com",
        "youtube.com",
        "crunchbase.com",
        "wikipedia.org",
    )

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or getattr(settings, "tavily_api_key", None)
        if not self.api_key:
            logger.warning("Tavily API key not set. Signal enrichment will be skipped.")

    def _needs_enrichment(self, lead: DiscoveredLead) -> bool:
        return not lead.company_description or not lead.recent_activity or not lead.company_website

    def _query_for_lead(self, lead: DiscoveredLead) -> str:
        parts = [
            f'"{lead.company}"' if lead.company else "",
            f'"{lead.name}"' if lead.name else "",
            lead.job_title or "",
            "company overview recent news funding hiring launch official website",
        ]
        return " ".join(part for part in parts if part).strip()

    def _normalize_snippet(self, value: str | None, limit: int = 280) -> str | None:
        if not value:
            return None
        cleaned = " ".join(str(value).split())
        if not cleaned:
            return None
        return cleaned[:limit].rstrip()

    def _website_from_results(self, results: list[dict]) -> str | None:
        for result in results:
            url = result.get("url")
            if not url:
                continue
            hostname = (urlparse(url).hostname or "").lower()
            if hostname.startswith("www."):
                hostname = hostname[4:]
            if not hostname or any(noisy in hostname for noisy in self.NOISY_DOMAINS):
                continue
            return url
        return None

    async def _enrich_one(self, client: httpx.AsyncClient, lead: DiscoveredLead) -> DiscoveredLead:
        query = self._query_for_lead(lead)
        if not query:
            return lead

        response = await client.post(
            self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "search_depth": "basic",
                "topic": "general",
                "max_results": 3,
                "include_raw_content": False,
                "include_answer": False,
            },
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        if not results:
            return lead

        first_result = results[0]
        content = self._normalize_snippet(first_result.get("content"))
        website = self._website_from_results(results)
        source = lead.discovery_source or "unknown"
        if "tavily" not in source:
            source = f"{source}+tavily"

        return lead.model_copy(
            update={
                "company_description": lead.company_description or content,
                "recent_activity": lead.recent_activity or content,
                "company_website": lead.company_website or website,
                "discovery_source": source,
            }
        )

    async def enrich_leads(self, leads: List[DiscoveredLead]) -> List[DiscoveredLead]:
        if not self.api_key or not leads:
            return leads

        targets = [(index, lead) for index, lead in enumerate(leads) if self._needs_enrichment(lead)]
        if not targets:
            return leads

        limited_targets = targets[: self.MAX_ENRICHMENTS]
        logger.info("Running Tavily enrichment for %s discovered lead(s).", len(limited_targets))
        updated = list(leads)

        async with httpx.AsyncClient(timeout=8.0) as client:
            enriched = await asyncio.gather(
                *(self._enrich_one(client, lead) for _, lead in limited_targets),
                return_exceptions=True,
            )

        for (index, original), result in zip(limited_targets, enriched):
            if isinstance(result, Exception):
                logger.warning("Tavily enrichment failed for %s: %s", original.email or original.company or "lead", result)
                continue
            updated[index] = result
        return updated
