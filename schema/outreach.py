"""Pydantic models for outbound email drafts and run results."""

from pydantic import BaseModel, Field


class CampaignInfo(BaseModel):
    """Campaign information from database."""
    id: int = Field(description="Campaign ID")
    name: str = Field(description="Campaign name")
    value_proposition: str = Field(description="Campaign value proposition")
    cta: str = Field(description="Call-to-action text")
    status: str = Field(description="Campaign status (ACTIVE, PAUSED, INACTIVE)")
    meeting_delay_days: int = Field(default=1, description="Days to delay meeting scheduling")
    max_leads_per_campaign: int | None = Field(default=None, description="Max leads to contact")
    lead_selection_order: str = Field(default="newest_first", description="Order to select leads (newest_first, oldest_first, random, highest_score)")
    auto_approve_drafts: bool = Field(default=False, description="Whether to auto-approve email drafts for this campaign")
    max_emails_per_lead: int = Field(default=5, description="Max emails to send per lead in this campaign")


class CampaignCreate(BaseModel):
    """Payload for creating a new campaign."""
    name: str = Field(description="Campaign name")
    value_proposition: str = Field(description="Campaign value proposition")
    cta: str = Field(description="Call-to-action text")
    status: str = Field(default="ACTIVE", description="Campaign status (ACTIVE, PAUSED, INACTIVE)")
    meeting_delay_days: int = Field(default=1, description="Days to delay meeting scheduling")
    max_leads_per_campaign: int | None = Field(default=None, description="Max leads to contact")
    lead_selection_order: str = Field(default="newest_first", description="Order to select leads (newest_first, oldest_first, random, highest_score)")
    auto_approve_drafts: bool = Field(default=False, description="Whether to auto-approve email drafts")
    max_emails_per_lead: int = Field(default=5, description="Max emails to send per lead")


class CampaignUpdate(BaseModel):
    """Payload for updating an existing campaign."""
    name: str | None = Field(default=None, description="Campaign name")
    value_proposition: str | None = Field(default=None, description="Campaign value proposition")
    cta: str | None = Field(default=None, description="Call-to-action text")
    status: str | None = Field(default=None, description="Campaign status (ACTIVE, PAUSED, INACTIVE)")
    meeting_delay_days: int | None = Field(default=None, description="Days to delay meeting scheduling")
    max_leads_per_campaign: int | None = Field(default=None, description="Max leads to contact")
    lead_selection_order: str | None = Field(default=None, description="Order to select leads")
    auto_approve_drafts: bool | None = Field(default=None, description="Whether to auto-approve email drafts")
    max_emails_per_lead: int | None = Field(default=None, description="Max emails to send per lead")


class LeadInfo(BaseModel):
    """Lead information for personalized outreach."""
    name: str = Field(description="Lead's full name")
    email: str = Field(description="Lead's email address") 
    company: str = Field(description="Lead's company name")
    industry: str = Field(description="Company's industry")
    pain_points: str = Field(description="Known challenges or pain points")


class OutreachEmailDraft(BaseModel):
    """Email generation contract: subject + body only."""

    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body")


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


class CampaignExecutionResult(BaseModel):
    """Structured output for the Senior Marketing Agent."""
    rationale: str = Field(description="Chain of thought explaining the campaign execution, lead selection, and why the chosen email draft was best.")
    selected_draft_type: str = Field(description="The type of email draft selected (e.g., professional, engaging, concise).")
    sent_subject: str = Field(description="The subject line of the email that was sent.")
    success: bool = Field(description="Whether the campaign execution was successful.")
    error: str | None = Field(None, description="Error message if the execution failed.")