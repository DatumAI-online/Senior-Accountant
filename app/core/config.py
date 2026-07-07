"""
Application configuration.

Settings are loaded from environment variables (and an optional .env file)
using pydantic-settings. Keeping configuration centralized here means the
rest of the codebase never touches os.environ directly.
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
