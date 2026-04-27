"""Application settings from environment variables."""

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
    log_file: str = Field(
        default="logs/squad3.log",
        description="Path to log file for persistent logging"
    )
    log_max_size_mb: int = Field(
        default=10,
        description="Maximum log file size in MB before rotation",
        gt=0, le=100
    )
    log_backup_count: int = Field(
        default=5,
        description="Number of backup log files to keep",
        gt=0, le=20
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

    # Database - SQLite (local) or Aurora Data API (production)
    database_url: str = Field(
        default="sqlite:///./db/sdr.sqlite3",
        validation_alias="DATABASE_URL",
        description="Database URL (default: SQLite next to db/schema.sql)",
    )
    db_cluster_arn: str | None = Field(
        default=None,
        validation_alias="DB_CLUSTER_ARN",
        description="Aurora cluster ARN for Data API (when set, overrides database_url)",
    )
    db_secret_arn: str | None = Field(
        default=None,
        validation_alias="DB_SECRET_ARN",
        description="Secrets Manager ARN for Aurora credentials",
    )
    db_name_aurora: str = Field(
        default="sdr",
        validation_alias="DB_NAME",
        description="Aurora database name",
    )

    # API Keys (.env: OPENAI_API_KEY, AGENTMAIL_*)
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        description="OpenAI API key for AI model access",
    )
    openai_tracing_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_TRACING_KEY",
        description="Separate OpenAI API key used only for traces export. If unset, uses OPENAI_API_KEY.",
    )
    openrouter_api_key: str | None = Field(
        default=None,
        validation_alias="OPENROUTER_API_KEY",
        description="OpenRouter API key for fallback AI access",
    )
    cerebras_api_key: str | None = Field(
        default=None,
        validation_alias="CEREBRAS_API_KEY",
        description="Cerebras API key(s) for fallback AI access. Comma-separated for multiple keys.",
    )
    groq_api_key: str | None = Field(
        default=None,
        validation_alias="GROQ_API_KEY",
        description="Groq API key(s) for fallback AI access. Comma-separated for multiple keys.",
    )
    agentmail_api_key: str | None = Field(
        default=None,
        validation_alias="AGENTMAIL_API_KEY",
        description="AgentMail API key for email operations",
    )
    agentmail_inbox_id: str | None = Field(
        default=None,
        validation_alias="AGENTMAIL_INBOX_ID",
        description="AgentMail inbox identifier",
    )
    composio_api_key: str | None = Field(
        default=None,
        description="Composio API key for tool integrations"
    )
    composio_user_id: str | None = Field(
        default=None,
        description="Composio user ID for consistent session management"
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
        gt=0,
        le=2000,
    )

    # SaaS / System Configuration
    use_dummy_data: bool = Field(
        default=True,
        description="Use dummy database data for external tools like Calendar in capstone demo"
    )
    default_meeting_delay_days: int = Field(
        default=1,
        description="Number of days to wait before proposing a meeting if not specified by the lead",
        ge=0
    )
    max_leads_per_campaign: int = Field(
        default=50,
        description="Maximum number of leads to process in a single campaign run",
        gt=0
    )
    lead_selection_order: str = Field(
        default="newest_first",
        description="Order in which leads are selected for a campaign (newest_first, oldest_first, highest_score)"
    )
    daily_email_limit: int = Field(
        default=200,
        description="Maximum number of emails the system can send per day to protect sender reputation",
        gt=0
    )
    require_human_approval: bool = Field(
        default=False,
        description="If True, emails are saved as drafts for human review instead of being sent immediately."
    )

    # --- Outreach agent (packages/agents/outreach_*) ---
    outreach_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model for outbound email generation",
    )
    outreach_temperature: float = Field(
        default=0.5,
        ge=0.0,
        le=2.0,
        description="Temperature for outbound copy",
    )
    outreach_max_tokens: int = Field(
        default=500,
        gt=0,
        le=4096,
        description="Max tokens for outbound email generation",
    )
    max_words_per_email: int = Field(
        default=200,
        ge=1,
        description="Guardrail: max words in outbound body",
    )
    tone: str = Field(
        default="professional",
        description="Tone hint for outbound generation",
    )
    forbidden_phrases: str = Field(
        default="guaranteed ROI,100% guarantee,no risk",
        description="Comma-separated substrings to block in outbound copy",
    )
    opt_out_footer: str = Field(
        default="\n\nIf you'd prefer not to hear from us, reply with STOP and we will remove you.",
        description="Appended to outbound body when no opt-out wording detected",
    )

    # Deployment
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:3001,http://localhost:3002",
        description="Comma-separated allowed CORS origins",
    )
    webhook_secret: str | None = Field(
        default=None,
        validation_alias="WEBHOOK_SECRET",
        description="Shared secret for validating incoming webhook requests (optional for local dev)",
    )

    # Multi-key helpers: split comma-separated values into lists
    @property
    def groq_api_keys(self) -> list[str]:
        if not self.groq_api_key:
            return []
        return [k.strip() for k in self.groq_api_key.split(",") if k.strip()]

    @property
    def cerebras_api_keys(self) -> list[str]:
        if not self.cerebras_api_key:
            return []
        return [k.strip() for k in self.cerebras_api_key.split(",") if k.strip()]

    @property
    def openrouter_api_keys(self) -> list[str]:
        if not self.openrouter_api_key:
            return []
        return [k.strip() for k in self.openrouter_api_key.split(",") if k.strip()]

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
    def db_url(self) -> str:
        return self.database_url


# Global singleton instance
settings = AppConfig()