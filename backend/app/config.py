from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Reads the project-root .env and backend/.env (the latter wins); real
    # environment variables override both.
    model_config = SettingsConfigDict(
        env_file=(_BACKEND_DIR.parent / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TeamTrack AI"
    environment: str = "development"

    # SQLite by default for local development; set to a Postgres URL in production,
    # e.g. postgresql+psycopg://user:pass@host:5432/teamtrack
    database_url: str = "sqlite:///./teamtrack.db"

    # Auth
    jwt_secret: str = "dev-only-secret-change-me-in-production-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12

    # CORS (comma separated)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # LLM. Without any credentials the app falls back to a rule-based parser and
    # deterministic reports, clearly labelled as non-AI.
    # "auto": Groq when GROQ_API_KEY is set, else Claude when Anthropic credentials are set
    # "groq" / "anthropic": force that provider
    # "fallback": never call an LLM
    llm_provider: str = "auto"

    # Groq (OpenAI-compatible API). MODEL in .env selects the Groq model.
    groq_api_key: str | None = None
    groq_model: str = Field(default="openai/gpt-oss-120b", validation_alias=AliasChoices("groq_model", "model"))
    groq_max_tokens: int = 8000

    # Claude
    llm_model: str = "claude-opus-5-5"
    llm_parse_effort: str = "low"
    llm_report_effort: str = "medium"
    llm_use_server_fallbacks: bool = True
    anthropic_api_key: str | None = None

    # Background scheduler (reminders, scheduled reports)
    scheduler_enabled: bool = True
    scheduler_interval_minutes: int = 15

    # Rate limits (requests per minute per user/IP)
    rate_limit_login_per_minute: int = 10
    rate_limit_ai_per_minute: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
