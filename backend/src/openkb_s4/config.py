"""Environment-driven service configuration; secrets have no shared defaults."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings from S4_* environment variables or the local .env file."""

    model_config = SettingsConfigDict(env_prefix="S4_", env_file=("../.env", ".env"), extra="ignore")
    database_url: str = "postgresql+asyncpg://localhost/openkb_s4"
    data_dir: Path = Path("../var")
    cookie_secure: bool = False
    session_hours: int = 12
    allowed_origin: str = ""
    receipt_token: str = ""
    login_limit: int = 8
    max_import_bytes: int = 20_000_000
    external_alignment_confirmed: bool = False


def get_settings() -> Settings:
    """Load fresh settings; tests and CLI can supply isolated environments."""
    return Settings()
