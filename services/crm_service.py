"""CRM ingestion adapters."""

from __future__ import annotations

from typing import Any

import httpx

from config import settings


def _normalize_hubspot_contact(record: dict[str, Any]) -> dict[str, Any]:
    props = record.get("properties") or {}
    first = props.get("firstname") or ""
    last = props.get("lastname") or ""
    name = " ".join(part for part in [first, last] if part).strip() or props.get("name")
    return {
        "email": props.get("email"),
        "name": name,
        "company": props.get("company"),
        "industry": props.get("industry"),
        "pain_points": props.get("notes") or props.get("hs_content_membership_notes"),
        "status": "NEW",
        "email_opt_out": bool(props.get("hs_email_optout")),
    }


async def fetch_crm_leads(provider: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch leads from a configured CRM provider."""
    provider = (provider or settings.crm_provider or "hubspot").lower()
    if provider != "hubspot":
        raise ValueError(f"Unsupported CRM provider: {provider}")
    if not settings.crm_api_key:
        raise ValueError("CRM_API_KEY is required for HubSpot import")

    base_url = (settings.crm_base_url or "https://api.hubapi.com").rstrip("/")
    params = {
        "limit": str(max(1, min(limit, 100))),
        "properties": "email,firstname,lastname,company,industry,hs_email_optout",
    }
    headers = {"Authorization": f"Bearer {settings.crm_api_key}"}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        response = await client.get(f"{base_url}/crm/v3/objects/contacts", params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()

    return [
        lead
        for lead in (_normalize_hubspot_contact(item) for item in payload.get("results", []))
        if lead.get("email")
    ]
