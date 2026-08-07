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

    # --- Object storage: raw article text (local dev; DO Spaces in production) ---
    storage_dir: str = "./data/raw"

    # --- Collector politeness ---
    user_agent: str = "NewsPulseBot/0.1 (+https://www.asiacosmepulse.com)"

    # --- Mistral AI (enrichment + synthesis, from Phase 2) ---
    mistral_api_key: str = ""
    mistral_model: str = "mistral-small-latest"

    # --- Webhook / NewsAPI ingestion (Phase 9) ---
    newsapi_key: str = ""
    newsapi_query: str = '(beauty OR skincare OR makeup OR cosmetics OR fragrance OR "hair care")'
    webhook_secret: str = ""
    rebuild_after_n: int = 5


def get_settings() -> Settings:
    """Return application settings.

    Kept as a function so tests and future dependency-injection can override it.
    """
    return Settings()


settings = get_settings()
