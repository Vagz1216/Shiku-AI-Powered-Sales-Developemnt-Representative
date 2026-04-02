"""Configuration module for Squad3 application."""

from .settings import AppConfig, settings

__all__ = ["AppConfig", "settings"]


# Legacy function for backward compatibility
def get_settings() -> AppConfig:
    """Get settings instance. For backward compatibility."""
    return settings


def reload_settings() -> AppConfig:
    """Reload settings from environment. Creates new instance."""
    global settings
    settings = AppConfig()
    return settings