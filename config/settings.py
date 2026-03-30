"""Application settings from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env", 
        env_file_encoding="utf-8",
        case_sensitive=False,
        frozen=True,
        extra="ignore",  # Ignore extra fields instead of raising errors
    )

    # Core settings
    debug: bool = False
    log_level: str = "info"
    app_name: str = "Squad3"
    port: int = 8000

    # Database & Cache
    database_url: str | None = None

    # API Keys
    openai_api_key: str | None = None
    agentmail_api_key: str | None = None
    agentmail_inbox_id: str | None = None

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