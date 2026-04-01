"""Email-related Pydantic schemas."""

from pydantic import BaseModel, Field


class EmailIntent(BaseModel):
    """Structured intent classification result."""
    intent: str = Field(description="Classified intent of the email e.g meeting_request, question, opt_out, interest, neutral, bounce, spam")
    confidence: float = Field(description="Confidence score of the classification (0.0 - 1.0)")


class EmailActionResult(BaseModel):
    """Result of email processing action."""
    action_taken: str = Field(description="Description of the action taken, e.g. replied, skipped, error")
    success: bool = Field(description="Whether the action was successful")
    message_id: str | None = Field(None, description="ID of the sent message if applicable")
    thread_id: str | None = Field(None, description="ID of the email thread if applicable")
    error: str | None = Field(None, description="Error message if the action failed")


class WebhookEvent(BaseModel):
    """AgentMail webhook event structure."""
    event_type: str = Field(..., description="Type of event, e.g. message.received")
    event_id: str = Field(..., description="Unique identifier for the event")
    message: dict = Field(..., description="Message payload")

class MeetingResult(BaseModel):
    """Result of creating a calendar meeting."""
    success: bool = Field(description="Whether the meeting was successfully created")
    meeting_link: str | None = Field(None, description="Link to the created meeting if successful")
    event_id: str | None = Field(None, description="ID of the created calendar event")
    error: str | None = Field(None, description="Error message if the meeting creation failed")

class ResponseEvaluation(BaseModel):
    """Structured response evaluation result."""
    approved: bool = Field(description="Whether the response is approved for sending")
    reason: str = Field(description="Brief explanation of the approval or rejection decision")