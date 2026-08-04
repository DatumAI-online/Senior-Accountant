"""
Application configuration.

Settings are loaded from environment variables (and an optional .env file)
using pydantic-settings. Keeping configuration centralized here means the
rest of the codebase never touches os.environ directly.

Three separate database URLs are intentional, not an oversight: AI agents
and CPA-facing endpoints connect to Postgres as *different* database roles
with different grants (see alembic/versions/0001_initial_schema.py). This
is what makes the "AI can never approve its own work" control a database
guarantee rather than an application-code promise. See
DATUM_AI_BOOKKEEPING_TEAM_PLAN.md, Section 10.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Anthropic / Claude ---
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    claude_max_tokens: int = 1024

    # --- App metadata ---
    app_name: str = "datum-skill-brain"
    app_version: str = "0.1.0"
    environment: str = "development"

    # --- CORS ---
    cors_allow_origins: str = "*"

    # --- Database: admin (schema owner, used only by Alembic/bootstrap) ---
    admin_database_url: str = (
        "postgresql+psycopg2://datumai_admin:datumai_admin_dev_pw@localhost:5432/datumai_dev"
    )

    # --- Database: AI service role (all 4 agents connect through this) ---
    # No grant path to approved/rejected/posted/reversed status values,
    # no DELETE grant on any table, no access to review_decisions at all.
    ai_service_database_url: str = (
        "postgresql+psycopg2://datumai_ai_service:datumai_ai_service_dev_pw@localhost:5432/datumai_dev"
    )

    # --- Database: CPA service role (only CPA-facing endpoints use this) ---
    cpa_service_database_url: str = (
        "postgresql+psycopg2://datumai_cpa_service:datumai_cpa_service_dev_pw@localhost:5432/datumai_dev"
    )

    # --- Auth ---
    jwt_secret_key: str = "change-me-in-every-environment"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so we only parse the environment once."""
    return Settings()
