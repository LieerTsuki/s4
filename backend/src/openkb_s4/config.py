"""Environment-driven service configuration; secrets have no shared defaults."""
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings from S4_* environment variables or the local .env file."""

    model_config = SettingsConfigDict(env_prefix="S4_", env_file=("../.env", ".env"), extra="ignore")
    database_url: str = "postgresql+asyncpg://localhost/openkb_s4"
    data_dir: Path = Path(__file__).resolve().parents[3] / "var"
    cookie_secure: bool = False
    session_hours: int = 12
    allowed_origin: str = ""
    receipt_token: str = ""
    import_token: str = ""
    import_service_user_id: str = ""
    login_limit: int = 8
    max_import_bytes: int = 20_000_000
    external_alignment_confirmed: bool = False
    # Only isolated historical regression environments may create v1 records.
    legacy_writes_enabled: bool = False
    reconcile_interval_seconds: int = Field(default=300, ge=1)
    worker_heartbeat_seconds: int = Field(default=15, ge=1)
    worker_lease_seconds: int = Field(default=120, ge=5)
    worker_max_attempts: int = Field(default=3, ge=1, le=20)
    operations_pending_warning_seconds: int = Field(default=300, ge=1)
    operations_receipt_warning_seconds: int = Field(default=86400, ge=1)

    @model_validator(mode="after")
    def heartbeat_precedes_expiry(self) -> "Settings":
        if self.import_token and self.receipt_token and self.import_token == self.receipt_token:
            raise ValueError("S3 ingress and S5 receipt credentials must be distinct.")
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds:
            raise ValueError("Worker heartbeat interval must be shorter than its lease.")
        return self


def get_settings() -> Settings:
    """Load fresh settings; tests and CLI can supply isolated environments."""
    return Settings()
