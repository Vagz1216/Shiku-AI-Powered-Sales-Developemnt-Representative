"""Tool-related Pydantic schemas."""

from pydantic import BaseModel, Field


class SendEmailResult(BaseModel):
    """Result of sending an email."""
    ok: bool = Field(description="Whether the email was sent successfully")
    message_id: str | None = Field(None, description="ID of the sent message if successful")
    thread_id: str | None = Field(None, description="ID of the email thread if applicable")
    error: str | None = Field(None, description="Error message if sending failed")


class LeadOut(BaseModel):
    """Lead output schema with name and email."""
    name: str | None = Field(None, description="Lead's name")
    email: str = Field(description="Lead's email address")


class StaffOut(BaseModel):
    """Staff output schema with name and email."""
    name: str = Field(description="Staff member's name")
    email: str = Field(description="Staff member's email address")