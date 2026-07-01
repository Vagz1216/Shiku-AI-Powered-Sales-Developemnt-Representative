"""Application settings from environment variables."""

from typing import Literal

from pydantic import AliasChoices, Field, field_validator
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

    # Database - SQLite (local), PostgreSQL URL (Azure/standard managed Postgres),
    # or Aurora Data API (AWS production)
    database_url: str = Field(
        default="sqlite:///./db/sdr.sqlite3",
        validation_alias="DATABASE_URL",
        description="Database URL: sqlite:///... locally or postgresql://... for standard managed Postgres",
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
    postgres_pool_min_size: int = Field(
        default=1,
        validation_alias="POSTGRES_POOL_MIN_SIZE",
        description="Minimum PostgreSQL pooled connections for standard Postgres deployments",
        ge=0,
    )
    postgres_pool_max_size: int = Field(
        default=20,
        validation_alias="POSTGRES_POOL_MAX_SIZE",
        description="Maximum PostgreSQL pooled connections for standard Postgres deployments",
        ge=1,
    )
    postgres_pool_timeout_seconds: float = Field(
        default=20.0,
        validation_alias="POSTGRES_POOL_TIMEOUT_SECONDS",
        description="Seconds to wait for a PostgreSQL pooled connection before failing fast",
        gt=0,
        le=120,
    )
    clerk_user_cache_ttl_seconds: int = Field(
        default=3600,
        validation_alias="CLERK_USER_CACHE_TTL_SECONDS",
        description="Seconds to cache Clerk user profile enrichment after JWT verification",
        ge=0,
    )
    clerk_user_enrichment_timeout_seconds: float = Field(
        default=5.0,
        validation_alias="CLERK_USER_ENRICHMENT_TIMEOUT_SECONDS",
        description="HTTP timeout for optional Clerk user profile enrichment",
        gt=0,
        le=30,
    )
    clerk_user_enrichment_circuit_cooldown_seconds: int = Field(
        default=30,
        validation_alias="CLERK_USER_ENRICHMENT_CIRCUIT_COOLDOWN_SECONDS",
        description="Seconds to skip optional Clerk user enrichment after repeated failures",
        ge=0,
        le=300,
    )
    tenant_cache_ttl_seconds: int = Field(
        default=60,
        validation_alias="TENANT_CACHE_TTL_SECONDS",
        description="Seconds to cache authenticated user and organization membership lookups",
        ge=0,
        le=600,
    )
    platform_organization_id: int = Field(
        default=1,
        validation_alias="PLATFORM_ORGANIZATION_ID",
        description="Organization ID owned by the platform/system owner for first-party workflows",
        ge=1,
    )

    # API Keys (.env: OPENAI_API_KEY, AGENTMAIL_*)
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        description="OpenAI API key for AI model access",
    )
    openai_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_BASE_URL", "LITELLM_BASE_URL"),
        description="Optional OpenAI-compatible base URL, for example a LiteLLM proxy ending in /v1",
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
    azure_deepseek_api_key: str | None = Field(
        default=None,
        validation_alias="AZURE_DEEPSEEK_API_KEY",
        description="Azure DeepSeek (Serverless API) API key",
    )
    azure_deepseek_endpoint: str | None = Field(
        default=None,
        validation_alias="AZURE_DEEPSEEK_ENDPOINT",
        description="Azure DeepSeek Serverless API endpoint URL",
    )
    azure_deepseek_model: str = Field(
        default="DeepSeek-R1",
        validation_alias="AZURE_DEEPSEEK_MODEL",
        description="Azure DeepSeek model deployment name",
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
    llm_routing_mode: Literal["quality_first", "balanced", "cost_optimized"] = Field(
        default="quality_first",
        validation_alias="LLM_ROUTING_MODE",
        description=(
            "Provider ordering policy. quality_first preserves the platform hierarchy; "
            "balanced is task-aware and avoids expensive models for simple work; "
            "cost_optimized lets low-risk agents try cheaper capable providers first."
        ),
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias="GROQ_MODEL",
        description="Groq fallback model. Groq is skipped for structured-output agents.",
    )
    cerebras_model: str = Field(
        default="gpt-oss-120b",
        validation_alias="CEREBRAS_MODEL",
        description="Cerebras fallback model. Cerebras is skipped for tool-calling agents.",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias="GEMINI_MODEL",
        description="Gemini fallback model used through the OpenAI-compatible Gemini endpoint.",
    )
    openrouter_meta_model: str = Field(
        default="meta-llama/llama-3.2-3b-instruct:free",
        validation_alias="OPENROUTER_META_MODEL",
        description="OpenRouter Meta fallback model.",
    )
    openrouter_llama_model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct:free",
        validation_alias="OPENROUTER_LLAMA_MODEL",
        description="OpenRouter Llama fallback model.",
    )
    openrouter_deepseek_model: str = Field(
        default="qwen/qwen-2-7b-instruct:free",
        validation_alias="OPENROUTER_DEEPSEEK_MODEL",
        description="OpenRouter DeepSeek/Qwen fallback model.",
    )
    openrouter_google_model: str = Field(
        default="google/gemini-2.0-flash-lite-preview-02-05:free",
        validation_alias="OPENROUTER_GOOGLE_MODEL",
        description="OpenRouter Google fallback model.",
    )
    openrouter_auto_model: str = Field(
        default="openrouter/free",
        validation_alias="OPENROUTER_AUTO_MODEL",
        description="OpenRouter auto-router fallback model.",
    )
    organization_llm_keys_enabled: bool = Field(
        default=False,
        validation_alias="ORGANIZATION_LLM_KEYS_ENABLED",
        description=(
            "Feature flag for future organization-owned LLM credentials. When disabled, "
            "all LLM calls use platform-level provider keys."
        ),
    )
    organization_llm_provider_mode: Literal["platform_first", "organization_first", "organization_only"] = Field(
        default="platform_first",
        validation_alias="ORGANIZATION_LLM_PROVIDER_MODE",
        description=(
            "Controls how organization-owned LLM keys should be mixed with platform keys "
            "when ORGANIZATION_LLM_KEYS_ENABLED is enabled."
        ),
    )
    apply_db_migrations_on_startup: bool = Field(
        default=False,
        validation_alias="APPLY_DB_MIGRATIONS_ON_STARTUP",
        description="Optional single-instance Docker/Coolify startup migration switch.",
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
    langfuse_secret_key: str | None = Field(
        default=None,
        validation_alias="LANGFUSE_SECRET_KEY",
        description="Langfuse Secret Key for observability tracing",
    )
    langfuse_public_key: str | None = Field(
        default=None,
        validation_alias="LANGFUSE_PUBLIC_KEY",
        description="Langfuse Public Key for observability tracing",
    )
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL"),
        description="Langfuse Host URL",
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
    apollo_api_key: str | None = Field(
        default=None,
        validation_alias="APOLLO_API_KEY",
        description="Apollo.io API Key for lead enrichment",
    )
    pdl_api_key: str | None = Field(
        default=None,
        validation_alias="PDL_API_KEY",
        description="People Data Labs API Key for free lead discovery fallback",
    )
    pdl_max_search_size: int = Field(
        default=10,
        validation_alias="PDL_MAX_SEARCH_SIZE",
        description="Maximum PDL Person Search result size per request; also caps credit burn.",
        ge=1,
        le=100,
    )
    lead_scout_provider_cooldown_seconds: int = Field(
        default=900,
        validation_alias="LEAD_SCOUT_PROVIDER_COOLDOWN_SECONDS",
        description="Seconds to skip a lead discovery provider after a non-retryable account/schema failure.",
        ge=0,
        le=86400,
    )
    lead_scout_mock_fallback_enabled: bool = Field(
        default=False,
        validation_alias="LEAD_SCOUT_MOCK_FALLBACK_ENABLED",
        description="Enable simulated lead discovery fallback. Keep false in production.",
    )
    tavily_api_key: str | None = Field(
        default=None,
        validation_alias="TAVILY_API_KEY",
        description="Tavily search API key for real-time lead signal research (recent posts, company news)",
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
    mailbox_oauth_state_secret: str | None = Field(
        default=None,
        validation_alias="MAILBOX_OAUTH_STATE_SECRET",
        description="Secret used to sign mailbox OAuth state payloads",
    )
    mailbox_oauth_frontend_redirect_url: str = Field(
        default="http://localhost:3000/mailboxes",
        validation_alias="MAILBOX_OAUTH_FRONTEND_REDIRECT_URL",
        description="Frontend URL to return to after a mailbox OAuth callback",
    )
    google_oauth_client_id: str | None = Field(
        default=None,
        validation_alias="GOOGLE_OAUTH_CLIENT_ID",
        description="Google OAuth client ID for tenant Gmail/Workspace mailbox connections",
    )
    google_oauth_client_secret: str | None = Field(
        default=None,
        validation_alias="GOOGLE_OAUTH_CLIENT_SECRET",
        description="Google OAuth client secret for tenant Gmail/Workspace mailbox connections",
    )
    microsoft_oauth_client_id: str | None = Field(
        default=None,
        validation_alias="MICROSOFT_OAUTH_CLIENT_ID",
        description="Microsoft Entra app client ID for tenant Outlook/Microsoft 365 mailbox connections",
    )
    microsoft_oauth_client_secret: str | None = Field(
        default=None,
        validation_alias="MICROSOFT_OAUTH_CLIENT_SECRET",
        description="Microsoft Entra app client secret for tenant Outlook/Microsoft 365 mailbox connections",
    )
    microsoft_oauth_tenant: str = Field(
        default="common",
        validation_alias="MICROSOFT_OAUTH_TENANT",
        description="Microsoft OAuth tenant segment, usually common, organizations, or a tenant ID",
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
    next_public_api_url: str | None = Field(
        default=None,
        validation_alias="NEXT_PUBLIC_API_URL",
        description="Frontend API URL carried in root .env for local/static builds",
    )
    vercel_oidc_token: str | None = Field(
        default=None,
        validation_alias="VERCEL_OIDC_TOKEN",
        description="Optional Vercel OIDC token ignored by backend runtime",
    )
    azure_client_id: str | None = Field(
        default=None,
        validation_alias="AZURE_CLIENT_ID",
        description="GitHub OIDC Azure client id; accepted so shared env templates stay loadable",
    )
    azure_tenant_id: str | None = Field(
        default=None,
        validation_alias="AZURE_TENANT_ID",
        description="GitHub OIDC Azure tenant id; ignored by backend runtime",
    )
    azure_subscription_id: str | None = Field(
        default=None,
        validation_alias="AZURE_SUBSCRIPTION_ID",
        description="GitHub OIDC Azure subscription id; ignored by backend runtime",
    )
    azure_resource_group: str | None = Field(
        default=None,
        validation_alias="AZURE_RESOURCE_GROUP",
        description="Azure deployment resource group; ignored by backend runtime",
    )
    azure_container_registry_name: str | None = Field(
        default=None,
        validation_alias="AZURE_CONTAINER_REGISTRY_NAME",
        description="Azure Container Registry name; ignored by backend runtime",
    )
    azure_container_registry_login_server: str | None = Field(
        default=None,
        validation_alias="AZURE_CONTAINER_REGISTRY_LOGIN_SERVER",
        description="Azure Container Registry login server; ignored by backend runtime",
    )
    azure_container_app_name: str | None = Field(
        default=None,
        validation_alias="AZURE_CONTAINER_APP_NAME",
        description="Azure Container App name; ignored by backend runtime",
    )
    azure_static_web_apps_api_token: str | None = Field(
        default=None,
        validation_alias="AZURE_STATIC_WEB_APPS_API_TOKEN",
        description="Azure Static Web Apps deployment token; ignored by backend runtime",
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
    scheduled_sender_initial_delay_seconds: int = Field(
        default=5,
        validation_alias="SCHEDULED_SENDER_INITIAL_DELAY_SECONDS",
        description="Startup delay before the in-process scheduled sender first checks the database",
        ge=0,
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
    mailbox_sync_default_limit: int = Field(
        default=10,
        validation_alias="MAILBOX_SYNC_DEFAULT_LIMIT",
        description="Default unread IMAP messages to inspect per mailbox sync trigger",
        gt=0,
        le=25,
    )
    mailbox_sync_enabled: bool = Field(
        default=False,
        validation_alias="MAILBOX_SYNC_ENABLED",
        description="Run an in-process SMTP/IMAP mailbox polling loop for local/simple single-replica deployments",
    )
    mailbox_sync_mark_seen: bool = Field(
        default=True,
        validation_alias="MAILBOX_SYNC_MARK_SEEN",
        description="Whether production mailbox sync marks successfully handled or deduped IMAP messages as seen",
    )
    mailbox_sync_wait: bool = Field(
        default=False,
        validation_alias="MAILBOX_SYNC_WAIT",
        description="Whether /api/mailboxes/sync-due waits for processing before returning by default",
    )
    mailbox_sync_interval_seconds: int = Field(
        default=300,
        validation_alias="MAILBOX_SYNC_INTERVAL_SECONDS",
        description="Recommended external scheduler frequency for mailbox sync jobs",
        gt=0,
        le=86400,
    )
    mailbox_sync_initial_delay_seconds: int = Field(
        default=15,
        validation_alias="MAILBOX_SYNC_INITIAL_DELAY_SECONDS",
        description="Startup delay before the in-process mailbox poller first checks the database",
        ge=0,
        le=3600,
    )
    mailbox_connection_timeout_seconds: float = Field(
        default=15.0,
        validation_alias="MAILBOX_CONNECTION_TIMEOUT_SECONDS",
        description="Socket timeout for SMTP/IMAP connection tests and IMAP polling",
        gt=0,
        le=120,
    )

    @field_validator("default_mailbox_id", mode="before")
    @classmethod
    def _blank_default_mailbox_id(cls, value):
        if value == "":
            return None
        return value

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
