"""Email-related Pydantic schemas."""

from pydantic import BaseModel, Field


class EmailIntent(BaseModel):
    """Structured intent classification result."""
    rationale: str = Field(description="Chain of thought explaining the reasoning behind the classification.")
    intent: str = Field(description="Classified intent of the email e.g meeting_request, meeting_confirmation, question, opt_out, interest, neutral, bounce, spam")
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
    rationale: str = Field(description="Chain of thought explaining the reasoning behind the evaluation.")
    approved: bool = Field(description="Whether the response is approved for sending")
    reason: str = Field(description="Brief explanation of the approval or rejection decision")


class MeetingDetails(BaseModel):
    """Structured meeting details for calendar event creation."""
    rationale: str = Field(default="", description="Chain of thought explaining the reasoning behind the selected meeting details.")
    subject: str = Field(description="Professional meeting subject line")
    start_time: str = Field(description="Meeting start time in YYYY-MM-DD HH:MM format")
    duration_minutes: int = Field(description="Duration of the meeting in minutes")
    description: str = Field(description="Brief meeting description with context from email conversation")
    conversation_summary: str = Field(description="Concise summary of the email thread context for staff notification")


class EmailResponse(BaseModel):
    """Structured email response output."""
    rationale: str = Field(description="Chain of thought explaining the reasoning behind the generated response.")
    response_text: str = Field(description="The generated email response text")
    action: str = Field(description="Action taken: generated, skipped, or error")
    reason: str | None = Field(None, description="Reason for skipping or error if applicable")