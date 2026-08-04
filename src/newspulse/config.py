"""Application configuration.

All settings are read from environment variables (see .env.example). Nothing
beauty-specific lives here yet — this is just the base config the whole engine
will build on.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "NewsPulse"
    app_env: str = "local"  # local | staging | production
    log_level: str = "INFO"

    # --- Storage (used from Phase 0.2 onward) ---
    database_url: str = "postgresql+psycopg://newspulse:newspulse@db:5432/newspulse"


def get_settings() -> Settings:
    """Return application settings.

    Kept as a function so tests and future dependency-injection can override it.
    """
    return Settings()


settings = get_settings()
