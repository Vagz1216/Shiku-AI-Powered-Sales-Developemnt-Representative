"""Lead management API schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_LEAD_STATUSES = {
    "NEW",
    "CONTACTED",
    "WARM",
    "QUALIFIED",
    "MEETING_PROPOSED",
    "MEETING_BOOKED",
    "COLD",
    "OPTED_OUT",
}


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(description="Lead email address")
    name: str | None = None
    company: str | None = None
    industry: str | None = None
    pain_points: str | None = None
    status: str = "NEW"
    email_opt_out: bool = False
    campaign_ids: list[int] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email is required")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        value = value.upper()
        if value not in VALID_LEAD_STATUSES:
            raise ValueError(f"invalid status: {value}")
        return value


class LeadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    name: str | None = None
    company: str | None = None
    industry: str | None = None
    pain_points: str | None = None
    status: str | None = None
    email_opt_out: bool | None = None
    campaign_ids: list[int] | None = None

    @field_validator("email")
    @classmethod
    def normalize_optional_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("valid email is required")
        return value

    @field_validator("status")
    @classmethod
    def validate_optional_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.upper()
        if value not in VALID_LEAD_STATUSES:
            raise ValueError(f"invalid status: {value}")
        return value


class BulkLeadImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leads: list[dict[str, Any]]
    campaign_ids: list[int] = Field(default_factory=list)
    upsert: bool = True
    source: str | None = "ui"


class ApiLeadImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str
    json_path: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    campaign_ids: list[int] = Field(default_factory=list)
    upsert: bool = True
