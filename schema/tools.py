"""Tool-related Pydantic schemas."""

from pydantic import BaseModel, Field


class SendEmailResult(BaseModel):
    """Result of sending an email."""
    ok: bool = Field(description="Whether the email was sent successfully")
    message_id: str | None = Field(None, description="ID of the sent message if successful")
    thread_id: str | None = Field(None, description="ID of the email thread if applicable")
    error: str | None = Field(None, description="Error message if sending failed")


class LeadOut(BaseModel):
    """Lead output schema with full details."""
    id: int | None = Field(None, description="Lead's ID")
    name: str | None = Field(None, description="Lead's name")
    email: str = Field(description="Lead's email address")
    company: str | None = Field(None, description="Lead's company")
    industry: str | None = Field(None, description="Lead's industry")
    pain_points: str | None = Field(None, description="Lead's pain points")


class StaffOut(BaseModel):
    """Staff output schema with name, email, timezone, and availability."""
    name: str = Field(description="Staff member's name")
    email: str = Field(description="Staff member's email address")
    timezone: str | None = Field(None, description="Staff member's timezone")
    availability: str | None = Field(None, description="Staff member's weekly availability in JSON format")