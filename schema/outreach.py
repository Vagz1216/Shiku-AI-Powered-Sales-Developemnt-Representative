"""Pydantic models for outbound email drafts and run results."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


LLMRoutingMode = Literal["quality_first", "balanced", "cost_optimized"]


class CampaignInfo(BaseModel):
    """Campaign information from database."""
    model_config = ConfigDict(extra="forbid")

    id: int = Field(description="Campaign ID")
    organization_id: int = Field(default=1, description="Owning organization ID")
    name: str = Field(description="Campaign name")
    value_proposition: str = Field(description="Campaign value proposition")
    cta: str = Field(description="Call-to-action text")
    status: str = Field(description="Campaign status (ACTIVE, PAUSED, INACTIVE)")
    meeting_delay_days: int = Field(default=1, description="Days to delay meeting scheduling")
    max_leads_per_campaign: int | None = Field(default=None, description="Max leads to contact")
    lead_selection_order: str = Field(default="newest_first", description="Order to select leads (newest_first, oldest_first, random, highest_score)")
    auto_approve_drafts: bool = Field(default=False, description="Whether to auto-send outbound outreach drafts for this campaign")
    auto_approve_monitor_replies: bool = Field(default=False, description="Whether to auto-send webhook/email-monitor replies for this campaign")
    max_emails_per_lead: int = Field(default=5, description="Max emails to send per lead in this campaign")
    llm_routing_mode: LLMRoutingMode | None = Field(default=None, description="Optional campaign-level LLM routing mode override")


class CampaignCreate(BaseModel):
    """Payload for creating a new campaign."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Campaign name")
    value_proposition: str = Field(description="Campaign value proposition")
    cta: str = Field(description="Call-to-action text")
    status: str = Field(default="ACTIVE", description="Campaign status (ACTIVE, PAUSED, INACTIVE)")
    meeting_delay_days: int = Field(default=1, description="Days to delay meeting scheduling")
    max_leads_per_campaign: int | None = Field(default=None, description="Max leads to contact")
    lead_selection_order: str = Field(default="newest_first", description="Order to select leads (newest_first, oldest_first, random, highest_score)")
    auto_approve_drafts: bool = Field(default=False, description="Whether to auto-send outbound outreach drafts")
    auto_approve_monitor_replies: bool = Field(default=False, description="Whether to auto-send webhook/email-monitor replies")
    max_emails_per_lead: int = Field(default=5, description="Max emails to send per lead")
    llm_routing_mode: LLMRoutingMode | None = Field(default=None, description="Optional campaign-level LLM routing mode override")


class CampaignUpdate(BaseModel):
    """Payload for updating an existing campaign."""
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, description="Campaign name")
    value_proposition: str | None = Field(default=None, description="Campaign value proposition")
    cta: str | None = Field(default=None, description="Call-to-action text")
    status: str | None = Field(default=None, description="Campaign status (ACTIVE, PAUSED, INACTIVE)")
    meeting_delay_days: int | None = Field(default=None, description="Days to delay meeting scheduling")
    max_leads_per_campaign: int | None = Field(default=None, description="Max leads to contact")
    lead_selection_order: str | None = Field(default=None, description="Order to select leads")
    auto_approve_drafts: bool | None = Field(default=None, description="Whether to auto-send outbound outreach drafts")
    auto_approve_monitor_replies: bool | None = Field(default=None, description="Whether to auto-send webhook/email-monitor replies")
    max_emails_per_lead: int | None = Field(default=None, description="Max emails to send per lead")
    llm_routing_mode: LLMRoutingMode | None = Field(default=None, description="Optional campaign-level LLM routing mode override")


class LeadInfo(BaseModel):
    """Lead information for personalized outreach."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Lead's full name")
    email: str = Field(description="Lead's email address") 
    phone_number: str | None = Field(default=None, description="Lead's phone number")
    linkedin_url: str | None = Field(default=None, description="Lead's LinkedIn URL")
    company: str = Field(description="Lead's company name")
    industry: str = Field(description="Company's industry")
    pain_points: str = Field(description="Known challenges or pain points")


class OutreachEmailDraft(BaseModel):
    """Message generation contract."""
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(default="", description="Message subject (empty for WhatsApp/LinkedIn)")
    body: str = Field(description="Message body")
    channel: str = Field(default="email", description="Channel (email, whatsapp, linkedin)")
    deep_link_url: str = Field(default="", description="Deep link URL if applicable")


class OutreachSendResult(BaseModel):
    """Result of sending an outreach email."""
    model_config = ConfigDict(extra="forbid")

    ok: bool
    message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None


class OutreachRunRecord(BaseModel):
    """Record of a single outreach email attempt."""
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(description="Concise audit summary explaining the campaign execution, lead selection, and why the chosen email draft was best.")
    selected_draft_type: str = Field(description="The type of email draft selected (e.g., professional, engaging, concise).")
    sent_subject: str = Field(description="The subject line of the email that was sent.")
    success: bool = Field(description="Whether the campaign execution was successful.")
    error: str | None = Field(None, description="Error message if the execution failed.")
