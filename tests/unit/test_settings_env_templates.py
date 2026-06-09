from config.settings import AppConfig


def test_azure_env_template_loads():
    settings = AppConfig(_env_file=".env.azure.example")

    assert settings.database_url.startswith("postgresql://")
    assert settings.scheduled_sender_enabled is False
    assert settings.default_mailbox_id is None
    assert settings.next_public_api_url
    assert settings.azure_container_registry_login_server


def test_local_env_template_allows_blank_optional_mailbox_id():
    settings = AppConfig(_env_file=".env.example")

    assert settings.default_mailbox_id is None
