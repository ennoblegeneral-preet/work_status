import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _serverless() -> bool:
    """True on Vercel / AWS Lambda style runtimes, where no process stays alive between requests."""
    markers = ("VERCEL", "VERCEL_ENV", "VERCEL_URL", "VERCEL_REGION", "AWS_LAMBDA_FUNCTION_NAME", "LAMBDA_TASK_ROOT")
    return any(os.environ.get(m) for m in markers)


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

    # MongoDB connection string, e.g. mongodb+srv://user:pass@cluster0.xxxx.mongodb.net/teamtrack
    # (MongoDB Atlas). The database name comes from MONGODB_DB, else the URI path, else "teamtrack".
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str | None = None

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

    # Background scheduler (reminders, scheduled reports). Off on Vercel, where
    # functions don't run continuously; a Vercel Cron Job calls /api/cron/automation.
    scheduler_enabled: bool = Field(default_factory=lambda: not _serverless())
    scheduler_interval_minutes: int = 15
    # Shared secret for the cron endpoint (Vercel sends "Authorization: Bearer <CRON_SECRET>")
    cron_secret: str | None = None

    # Rate limits (requests per minute per user/IP)
    rate_limit_login_per_minute: int = 10
    rate_limit_ai_per_minute: int = 20

    # Built React app served by this API (single-service deployment).
    # Defaults to ../frontend/dist; the page is skipped if the folder doesn't exist.
    frontend_dist: str = str(_BACKEND_DIR.parent / "frontend" / "dist")

    # First admin account, created at startup only when the database has no users.
    admin_email: str | None = None
    admin_password: str | None = None
    admin_name: str = "Admin"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
