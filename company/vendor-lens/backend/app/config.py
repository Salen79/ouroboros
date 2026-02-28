from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://ai_company:dev_password@localhost:5432/ai_company"
    openrouter_api_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    frontend_url: str = "http://localhost:3001"
    jina_api_key: str = ""
    debug: bool = True

    # Free tier limit per IP
    free_analyses_per_ip: int = 3
    # OpenRouter model to use
    llm_model: str = "anthropic/claude-3.5-sonnet"


settings = Settings()
