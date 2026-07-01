"""Schemas for multi-tenant organization and mailbox onboarding."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


OrgRole = Literal["org_admin", "sales_manager", "sales_user", "viewer"]
OrgUserStatus = Literal["ACTIVE", "INVITED", "DISABLED"]
MailboxProvider = Literal["smtp_imap", "resend", "gmail", "microsoft"]
LLMProvider = Literal["openai", "azure_openai", "gemini", "groq", "cerebras", "openrouter"]
LLMProviderMode = Literal["platform_first", "organization_first", "organization_only"]
LLMRoutingMode = Literal["quality_first", "balanced", "cost_optimized"]
SubscriptionStatus = Literal["TRIALING", "ACTIVE", "PAST_DUE", "CANCELED", "EXPIRED"]


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=80)
    owner_email: str | None = None
    timezone: str = Field(default="Africa/Nairobi", max_length=80)


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, max_length=80)


class SubscriptionPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    monthly_price_cents: int = Field(default=0, ge=0)
    currency_code: str = Field(default="USD", min_length=3, max_length=3)
    market_code: str = Field(default="GLOBAL", min_length=2, max_length=16)
    trial_days: int = Field(default=14, ge=0, le=365)
    max_users: int | None = Field(default=None, ge=1)
    max_campaigns: int | None = Field(default=None, ge=1)
    max_leads: int | None = Field(default=None, ge=1)
    max_monthly_emails: int | None = Field(default=None, ge=1)
    max_monthly_ai_tokens: int | None = Field(default=None, ge=1)
    max_monthly_ai_credits: int | None = Field(default=None, ge=1)
    overage_allowed: bool = False
    overage_price_cents_per_ai_credit: int | None = Field(default=None, ge=1)
    allow_byok: bool = False
    byok_provider_mode: LLMProviderMode = "platform_first"
    max_llm_credentials: int | None = Field(default=None, ge=1)
    allowed_llm_routing_modes: list[LLMRoutingMode] = Field(
        default_factory=lambda: ["cost_optimized", "balanced", "quality_first"]
    )
    default_llm_routing_mode: LLMRoutingMode = "balanced"
    trial_allowed_llm_routing_modes: list[LLMRoutingMode] = Field(default_factory=lambda: ["cost_optimized"])
    active: bool = True


class SubscriptionPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    monthly_price_cents: int | None = Field(default=None, ge=0)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    market_code: str | None = Field(default=None, min_length=2, max_length=16)
    trial_days: int | None = Field(default=None, ge=0, le=365)
    max_users: int | None = Field(default=None, ge=1)
    max_campaigns: int | None = Field(default=None, ge=1)
    max_leads: int | None = Field(default=None, ge=1)
    max_monthly_emails: int | None = Field(default=None, ge=1)
    max_monthly_ai_tokens: int | None = Field(default=None, ge=1)
    max_monthly_ai_credits: int | None = Field(default=None, ge=1)
    overage_allowed: bool | None = None
    overage_price_cents_per_ai_credit: int | None = Field(default=None, ge=1)
    allow_byok: bool | None = None
    byok_provider_mode: LLMProviderMode | None = None
    max_llm_credentials: int | None = Field(default=None, ge=1)
    allowed_llm_routing_modes: list[LLMRoutingMode] | None = None
    default_llm_routing_mode: LLMRoutingMode | None = None
    trial_allowed_llm_routing_modes: list[LLMRoutingMode] | None = None
    active: bool | None = None


class OrganizationLLMCredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: LLMProvider
    label: str | None = Field(default=None, max_length=120)
    api_key: str = Field(min_length=1, max_length=5000)
    default_model: str | None = Field(default=None, max_length=160)
    base_url: str | None = Field(default=None, max_length=500)
    azure_endpoint: str | None = Field(default=None, max_length=500)
    azure_deployment: str | None = Field(default=None, max_length=160)
    azure_api_version: str | None = Field(default=None, max_length=80)


class OrganizationLLMCredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=120)
    status: Literal["ACTIVE", "DISABLED"] | None = None
    api_key: str | None = Field(default=None, min_length=1, max_length=5000)
    default_model: str | None = Field(default=None, max_length=160)
    base_url: str | None = Field(default=None, max_length=500)
    azure_endpoint: str | None = Field(default=None, max_length=500)
    azure_deployment: str | None = Field(default=None, max_length=160)
    azure_api_version: str | None = Field(default=None, max_length=80)


class OrganizationPlanSelect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int = Field(gt=0)


class OrganizationSubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int | None = Field(default=None, gt=0)
    status: SubscriptionStatus | None = None
    trial_ends_at: str | None = None
    current_period_started_at: str | None = None
    current_period_ends_at: str | None = None


class OrganizationUserUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    role: OrgRole = "org_admin"
    status: OrgUserStatus = "ACTIVE"


class MailboxCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: MailboxProvider = "smtp_imap"
    display_name: str | None = Field(default=None, max_length=120)
    email_address: str
    daily_limit: int = Field(default=100, ge=1, le=5000)

    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_use_ssl: bool = True
    smtp_username: str | None = None
    smtp_password: str | None = None

    imap_host: str | None = None
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_use_ssl: bool = True
    imap_username: str | None = None
    imap_password: str | None = None

    resend_domain: str | None = None
    resend_from_email: str | None = None
    resend_reply_to: str | None = None
    resend_api_key: str | None = None
    resend_webhook_secret: str | None = None


class MailboxUpdate(MailboxCreate):
    """Update mailbox settings.

    Secret fields are optional. When omitted or blank, the existing encrypted
    secret is retained by the service layer.
    """
