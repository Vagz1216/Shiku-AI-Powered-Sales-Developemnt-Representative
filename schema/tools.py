"""Tool-related Pydantic schemas."""

from pydantic import BaseModel, Field


class SendEmailResult(BaseModel):
    """Result of sending an email."""
    ok: bool = Field(description="Whether the email was sent successfully")
    message_id: str | None = Field(None, description="ID of the sent message if successful")
    thread_id: str | None = Field(None, description="ID of the email thread if applicable")
    error: str | None = Field(None, description="Error message if sending failed")