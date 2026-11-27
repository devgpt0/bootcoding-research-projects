from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve the project root from this file so loading does not depend on the
# directory from which Uvicorn is started.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and project .env."""

    livekit_url: str | None = None
    livekit_api_key: str | None = None
    livekit_api_secret: str | None = None
    livekit_agent_deployment: str = "local-dev"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def livekit_configuration_status() -> dict[str, bool]:
    """Return credential presence without exposing any credential values."""
    return {
        "LIVEKIT_URL": bool(settings.livekit_url and settings.livekit_url.strip()),
        "LIVEKIT_API_KEY": bool(
            settings.livekit_api_key and settings.livekit_api_key.strip()
        ),
        "LIVEKIT_API_SECRET": bool(
            settings.livekit_api_secret and settings.livekit_api_secret.strip()
        ),
    }
