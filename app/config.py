from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.seed_config import DEFAULT_SPREADSHEET_ID

_APP_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _APP_DIR.parent
# Monorepo: .../backend/app/config.py  |  Standalone repo: .../app/config.py
if _BACKEND_ROOT.name == "backend":
    ROOT = _BACKEND_ROOT.parent
    DATA_ROOT = _BACKEND_ROOT
else:
    ROOT = _BACKEND_ROOT
    DATA_ROOT = _BACKEND_ROOT

CREDENTIALS_DIR = DATA_ROOT / "credentials"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    app_name: str = "VectoRise Workforce Portal"
    environment: str = "development"  # development | production
    debug: bool = True
    database_url: str = f"sqlite:///{DATA_ROOT / 'data' / 'dashboard.db'}"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    google_spreadsheet_id: str = DEFAULT_SPREADSHEET_ID
    google_service_account_path: str = str(CREDENTIALS_DIR / "google-service-account.json")
    sync_interval_minutes: int = 15
    enable_sync_scheduler: bool = True

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    admin_email: str = "admin@vectoriseinc.dev"
    admin_password: str = "admin123"
    seed_database: bool | None = None

    upload_dir: str = str(DATA_ROOT / "uploads")
    max_upload_mb: int = 5
    daily_jobs_hour: int = 23
    daily_jobs_minute: int = 0

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def should_seed(self) -> bool:
        if self.seed_database is not None:
            return self.seed_database
        return not self.is_production

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)

    @field_validator("google_spreadsheet_id", mode="before")
    @classmethod
    def default_spreadsheet_id(cls, value):
        if value is None or str(value).strip() == "":
            return DEFAULT_SPREADSHEET_ID
        return value

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.is_production and self.jwt_secret in {"", "change-me-in-production", "dev-secret-change-me"}:
            raise ValueError("JWT_SECRET must be set to a strong unique value in production")
        return self


settings = Settings()
