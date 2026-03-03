from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://vendorlens:vendorlens2026@localhost:5432/vendorlens"
    secret_key: str = "vendorlens-secret-key-change-in-production-2026"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    environment: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    
    class Config:
        env_file = ".env"

settings = Settings()
