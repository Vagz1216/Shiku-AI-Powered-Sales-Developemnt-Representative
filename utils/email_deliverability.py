"""Small deterministic helpers for safer outbound email deliverability."""

from __future__ import annotations

import re


_SPAMMY_SUBJECT_PATTERNS = (
    "partnership opportunity",
    "partnership opportunities",
    "partnership",
    "outreach",
    "following up",
    "follow up",
    "quick question",
    "fresh thought",
)


def normalize_outreach_subject(subject: str | None, *, company_name: str | None = None) -> str:
    """Replace spammy cold-outreach subject patterns with a simple request subject."""
    text = " ".join((subject or "").strip().split())
    normalized = text.lower()
    if not text or any(pattern in normalized for pattern in _SPAMMY_SUBJECT_PATTERNS):
        company = _clean_company_name(company_name)
        return f"Rates and media for {company}" if company else "Rates and media request"
    return text


def _clean_company_name(company_name: str | None) -> str:
    company = " ".join((company_name or "").strip().split())
    if not company:
        return ""
    if company.lower() in {"default", "default organization", "organization"}:
        return ""
    if re.search(r"\bstay\s*ez\b|\bstayez\b", company, flags=re.IGNORECASE):
        return "StayEZ"
    return company
