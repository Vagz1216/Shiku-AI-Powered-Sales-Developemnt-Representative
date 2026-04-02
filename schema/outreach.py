"""Pydantic models for outbound email drafts and run results."""

from pydantic import BaseModel, Field


class CampaignInfo(BaseModel):
    """Campaign information from database."""
    id: int = Field(description="Campaign ID")
    name: str = Field(description="Campaign name")
    value_proposition: str = Field(description="Campaign value proposition")
    cta: str = Field(description="Call-to-action text")
    status: str = Field(description="Campaign status (ACTIVE, PAUSED, INACTIVE)")


class LeadInfo(BaseModel):
    """Lead information for personalized outreach."""
    name: str = Field(description="Lead's full name")
    email: str = Field(description="Lead's email address") 
    company: str = Field(description="Lead's company name")
    industry: str = Field(description="Company's industry")
    pain_points: str = Field(description="Known challenges or pain points")


class OutreachEmailDraft(BaseModel):
    """Email generation contract: subject + body only."""

    subject: str = Field(description="Email subject", min_length=1)
    body: str = Field(description="Email body", min_length=1)


class OutreachSendResult(BaseModel):
    """Result of sending an outreach email."""
    ok: bool
    message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None


class OutreachRunRecord(BaseModel):
    """Record of a single outreach email attempt."""
    lead_email: str
    lead_name: str | None = None
    subject: str | None = None
    body: str | None = None
    status: str  # generated, sent, failed, error
    message_id: str | None = None
    error: str | None = None
    dry_run: bool = False