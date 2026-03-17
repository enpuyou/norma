import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Automatically load the root .env file into os.environ
# so libraries like `openai` can access them natively.
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(_ROOT_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: Literal["development", "production", "test"] = "development"
    secret_key: str = "changeme"
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite+aiosqlite:///./norma.db"

    # CORS
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3030",
    ]

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Feature flags
    enable_semantic_enforcement: bool = False
    enable_llm_quality_scoring: bool = True
    enable_otlp_export: bool = False

    # Phase 7: API auth + RBAC
    enable_api_key_auth: bool = False
    # JSON map: {"<api-key>": "viewer|operator|admin"}
    api_keys_json: str = ""

    # Phase 7: webhooks
    enable_webhooks: bool = False
    webhook_slack_url: str = ""
    webhook_email_url: str = ""
    webhook_pagerduty_url: str = ""

    # OTLP export
    otlp_endpoint: str = ""
    otlp_service_name: str = "norma-ai"
    otlp_headers_json: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
