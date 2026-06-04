"""Schemas for multi-tenant organization and mailbox onboarding."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


OrgRole = Literal["org_admin", "sales_manager", "sales_user", "viewer"]
OrgUserStatus = Literal["ACTIVE", "INVITED", "DISABLED"]
MailboxProvider = Literal["smtp_imap", "resend", "gmail", "microsoft"]


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
    trial_days: int = Field(default=14, ge=0, le=365)
    max_users: int | None = Field(default=None, ge=1)
    max_campaigns: int | None = Field(default=None, ge=1)
    max_leads: int | None = Field(default=None, ge=1)
    max_monthly_emails: int | None = Field(default=None, ge=1)
    max_monthly_ai_tokens: int | None = Field(default=None, ge=1)
    max_monthly_ai_credits: int | None = Field(default=None, ge=1)
    overage_allowed: bool = False
    overage_price_cents_per_ai_credit: int | None = Field(default=None, ge=1)
    active: bool = True


class SubscriptionPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    monthly_price_cents: int | None = Field(default=None, ge=0)
    trial_days: int | None = Field(default=None, ge=0, le=365)
    max_users: int | None = Field(default=None, ge=1)
    max_campaigns: int | None = Field(default=None, ge=1)
    max_leads: int | None = Field(default=None, ge=1)
    max_monthly_emails: int | None = Field(default=None, ge=1)
    max_monthly_ai_tokens: int | None = Field(default=None, ge=1)
    max_monthly_ai_credits: int | None = Field(default=None, ge=1)
    overage_allowed: bool | None = None
    overage_price_cents_per_ai_credit: int | None = Field(default=None, ge=1)
    active: bool | None = None


class OrganizationPlanSelect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int = Field(gt=0)


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
