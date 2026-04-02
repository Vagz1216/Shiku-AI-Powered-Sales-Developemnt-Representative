"""Application settings from environment variables."""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields instead of raising errors
    )

    # Core settings
    debug: bool = Field(
        default=False,
        description="Enable debug mode for development"
    )
    log_level: str = Field(
        default="info",
        description="Logging level (debug, info, warning, error, critical)"
    )
    app_name: str = Field(
        default="Squad3",
        description="Application name"
    )
    port: int = Field(
        default=8000,
        description="Server port number",
        gt=0, le=65535
    )

    # Database & Cache
    database_url: str | None = Field(
        default=None,
        description="Database connection URL"
    )

    # API Keys
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key for AI model access"
    )
    agentmail_api_key: str | None = Field(
        default=None,
        description="AgentMail API key for email operations"
    )
    agentmail_inbox_id: str | None = Field(
        default=None,
        description="AgentMail inbox identifier"
    )

    # Model Parameters - Intent Extraction
    intent_model: str = Field(
        default="gpt-4o-mini", 
        description="AI model for email intent classification"
    )
    intent_temperature: float = Field(
        default=0.1, 
        description="Temperature for intent analysis (0.0-1.0, lower = more consistent)",
        ge=0.0, le=1.0
    )
    intent_max_tokens: int = Field(
        default=100, 
        description="Maximum tokens for intent extraction responses",
        gt=0, le=4000
    )
    
    # Model Parameters - Email Response
    response_model: str = Field(
        default="gpt-4o-mini", 
        description="AI model for email response generation"
    )
    response_temperature: float = Field(
        default=0.7, 
        description="Temperature for email responses (0.0-1.0, higher = more creative)",
        ge=0.0, le=1.0
    )
    response_max_tokens: int = Field(
        default=1000, 
        description="Maximum tokens for email response generation",
        gt=0, le=2000
    )


    # Convenient aliases
    @property
    def openai_key(self) -> str | None:
        return self.openai_api_key
    
    @property
    def agent_mail_api(self) -> str | None:
        return self.agentmail_api_key
    
    @property
    def agent_mail_inbox(self) -> str | None:
        return self.agentmail_inbox_id
    
    @property
    def db_url(self) -> str | None:
        return self.database_url


# Global singleton instance
settings = AppConfig()