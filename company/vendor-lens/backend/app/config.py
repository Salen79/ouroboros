from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database: defaults to SQLite (zero-config for local/MVP). Switch to postgres for prod.
    database_url: str = "sqlite+aiosqlite:///./vendorlens.db"

    openrouter_api_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    frontend_url: str = "http://localhost:3001"
    jina_api_key: str = ""
    debug: bool = True

    # Free tier limit per IP
    free_analyses_per_ip: int = 3

    # LLM model — gemini flash is cheap/fast and great for extraction
    llm_model: str = "google/gemini-2.0-flash-001"

    # Request timeout for scraper (seconds)
    scraper_timeout: int = 45

    # Max content length to send to LLM (chars)
    llm_max_content_chars: int = 15000


settings = Settings()
