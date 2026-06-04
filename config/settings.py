"""Application settings from environment variables."""

from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
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
    llm_pricing_file: str = Field(
        default="config/llm_pricing.json",
        validation_alias="LLM_PRICING_FILE",
        description="Path to the editable model pricing table used for estimated usage costs",
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
    azure_openai_api_key: str | None = Field(
        default=None,
        validation_alias="AZURE_OPENAI_API_KEY",
        description="Azure OpenAI API key for the primary fallback provider",
    )
    azure_openai_endpoint: str | None = Field(
        default=None,
        validation_alias="AZURE_OPENAI_ENDPOINT",
        description="Azure OpenAI endpoint, e.g. https://resource.openai.azure.com",
    )
    azure_openai_deployment: str | None = Field(
        default=None,
        validation_alias="AZURE_OPENAI_DEPLOYMENT",
        description="Azure OpenAI deployment name to use as the model identifier",
    )
    azure_openai_api_version: str = Field(
        default="2024-10-21",
        validation_alias="AZURE_OPENAI_API_VERSION",
        description="Azure OpenAI API version",
    )
    azure_openai_wire_api: Literal["chat_completions", "responses"] = Field(
        default="chat_completions",
        validation_alias="AZURE_OPENAI_WIRE_API",
        description="Azure OpenAI transport used by the Agents SDK provider. responses uses the /openai/v1/ endpoint.",
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
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias="GEMINI_API_KEY",
        description="Reserved Gemini API key field so local .env validation stays strict",
    )
    google_api_key: str | None = Field(
        default=None,
        validation_alias="GOOGLE_API_KEY",
        description="Reserved Google API key field so local .env validation stays strict",
    )
    grok_api_key: str | None = Field(
        default=None,
        validation_alias="GROK_API_KEY",
        description="Reserved xAI/Grok API key field so local .env validation stays strict",
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
    email_provider: Literal["agentmail", "resend", "mailbox"] = Field(
        default="agentmail",
        validation_alias="EMAIL_PROVIDER",
        description="Email transport provider for outbound and monitor replies",
    )
    default_mailbox_id: int | None = Field(
        default=None,
        validation_alias="DEFAULT_MAILBOX_ID",
        description="Optional mailbox_connections.id to use when EMAIL_PROVIDER=mailbox",
    )
    resend_api_key: str | None = Field(
        default=None,
        validation_alias="RESEND_API_KEY",
        description="Resend API key for email operations",
    )
    resend_from_email: str | None = Field(
        default=None,
        validation_alias="RESEND_FROM_EMAIL",
        description="Verified Resend sender, e.g. Market Hacks <sdr@outreach.example.com>",
    )
    resend_reply_to: str | None = Field(
        default=None,
        validation_alias="RESEND_REPLY_TO",
        description="Reply-To address for Resend outbound mail",
    )
    resend_webhook_secret: str | None = Field(
        default=None,
        validation_alias="RESEND_WEBHOOK_SECRET",
        description="Svix signing secret for Resend webhooks",
    )
    crm_provider: str | None = Field(
        default=None,
        validation_alias="CRM_PROVIDER",
        description="CRM provider for direct lead import, currently hubspot",
    )
    crm_api_key: str | None = Field(
        default=None,
        validation_alias="CRM_API_KEY",
        description="CRM API key for direct lead import",
    )
    crm_base_url: str | None = Field(
        default=None,
        validation_alias="CRM_BASE_URL",
        description="Optional CRM API base URL override",
    )
    platform_owner_emails: str = Field(
        default="",
        validation_alias="PLATFORM_OWNER_EMAILS",
        description="Comma-separated email addresses that can create and administer customer organizations",
    )
    mailbox_encryption_key: str | None = Field(
        default=None,
        validation_alias="MAILBOX_ENCRYPTION_KEY",
        description="Fernet key used to encrypt mailbox SMTP/IMAP passwords at rest",
    )
    composio_api_key: str | None = Field(
        default=None,
        description="Composio API key for tool integrations"
    )
    composio_user_id: str | None = Field(
        default=None,
        description="Composio user ID for consistent session management"
    )
    clerk_secret_key: str | None = Field(
        default=None,
        validation_alias="CLERK_SECRET_KEY",
        description="Clerk backend secret key",
    )
    clerk_jwks_url: str | None = Field(
        default=None,
        validation_alias="CLERK_JWKS_URL",
        description="Clerk JWKS URL for JWT verification",
    )
    next_public_clerk_publishable_key: str | None = Field(
        default=None,
        validation_alias="NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
        description="Frontend Clerk publishable key carried in root .env for local builds",
    )
    vercel_oidc_token: str | None = Field(
        default=None,
        validation_alias="VERCEL_OIDC_TOKEN",
        description="Optional Vercel OIDC token ignored by backend runtime",
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
    rate_limit_requests_per_minute: int = Field(
        default=60,
        validation_alias="RATE_LIMIT_REQUESTS_PER_MINUTE",
        description="Simple per-client request limit for user-facing API endpoints",
        gt=0,
    )
    require_human_approval: bool = Field(
        default=True,
        description="If True, emails are saved as drafts for human review instead of being sent immediately."
    )
    require_outreach_human_approval: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("REQUIRE_OUTREACH_HUMAN_APPROVAL", "OUTREACH_REQUIRE_HUMAN_APPROVAL"),
        description="Optional override for outbound outreach approval. Defaults to require_human_approval.",
    )
    require_email_monitor_human_approval: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("REQUIRE_EMAIL_MONITOR_HUMAN_APPROVAL", "EMAIL_MONITOR_REQUIRE_HUMAN_APPROVAL"),
        description="Optional override for inbound email-monitor replies. Defaults to require_human_approval.",
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
    outreach_sender_name: str = Field(
        default="Alex",
        description="Sender display name used in outbound outreach signatures",
    )
    outreach_sender_company: str = Field(
        default="Euclid Tech",
        description="Sender company name used in outbound outreach signatures",
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
        default=(
            "http://localhost:3000,http://localhost:3001,http://localhost:3002,"
            "http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3002"
        ),
        description="Comma-separated allowed CORS origins",
    )
    webhook_secret: str | None = Field(
        default=None,
        validation_alias="WEBHOOK_SECRET",
        description="Shared secret for validating incoming webhook requests (optional for local dev)",
    )
    cron_secret: str | None = Field(
        default=None,
        validation_alias="CRON_SECRET",
        description="Shared secret for trusted schedulers that call due-work endpoints",
    )
    scheduled_sender_enabled: bool = Field(
        default=True,
        validation_alias="SCHEDULED_SENDER_ENABLED",
        description="Run the in-process background sender for due scheduled emails",
    )
    scheduled_sender_interval_seconds: int = Field(
        default=30,
        validation_alias="SCHEDULED_SENDER_INTERVAL_SECONDS",
        description="How often the in-process scheduled email sender checks for due emails",
        gt=0,
        le=3600,
    )
    scheduled_sender_batch_size: int = Field(
        default=50,
        validation_alias="SCHEDULED_SENDER_BATCH_SIZE",
        description="Maximum scheduled emails to process per background sender tick",
        gt=0,
        le=200,
    )
    scheduled_sender_retry_delay_seconds: int = Field(
        default=300,
        validation_alias="SCHEDULED_SENDER_RETRY_DELAY_SECONDS",
        description="How long to wait before retrying a scheduled email after a send failure",
        gt=0,
        le=86400,
    )
    scheduled_sender_max_attempts: int = Field(
        default=3,
        validation_alias="SCHEDULED_SENDER_MAX_ATTEMPTS",
        description="Maximum automatic send attempts before a scheduled email is paused for review",
        gt=0,
        le=20,
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

    @property
    def platform_owner_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.platform_owner_emails.split(",") if email.strip()}

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

    @property
    def effective_outreach_human_approval(self) -> bool:
        if self.require_outreach_human_approval is not None:
            return self.require_outreach_human_approval
        return self.require_human_approval

    @property
    def effective_email_monitor_human_approval(self) -> bool:
        if self.require_email_monitor_human_approval is not None:
            return self.require_email_monitor_human_approval
        return self.require_human_approval


# Global singleton instance
settings = AppConfig()
