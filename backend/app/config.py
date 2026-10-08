"""Application configuration loaded from environment variables.

Infrastructure configuration lives exclusively here (rule: business rules in
database metadata, infrastructure configuration in environment variables).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "BRSR Reporting Portal"
    environment: str = "development"

    # Database
    database_url: str = "postgresql+psycopg://brsr:brsr@postgres:5432/brsr"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Object storage (S3-compatible: RustFS, MinIO, AWS S3, ...)
    s3_endpoint: str = "http://s3:9000"
    s3_access_key: str = "brsr"
    s3_secret_key: str = "brsr-secret"
    s3_bucket: str = "brsr-evidence"
    s3_public_endpoint: str = ""

    # JWT
    jwt_secret: str = "dev-only-secret-change-me-in-production-32b"
    jwt_algorithm: str = "HS256"
    jwt_access_expiry_minutes: int = 60
    jwt_refresh_expiry_days: int = 7

    # Evidence upload limits
    max_evidence_file_size_mb: int = 25
    allowed_evidence_mime_types: str = (
        "application/pdf,text/csv,application/vnd.openxmlformats-officedocument."
        "spreadsheetml.sheet,image/png,image/jpeg"
    )

    # Validation tuning
    default_yoy_variance_threshold_percent: float = 20.0

    # Reminders
    reminder_days_before_due: int = 7
    escalation_days_after_overdue: int = 3

    # AI/OCR providers
    ai_provider: str = "none"
    ai_api_key: str = ""
    ocr_provider: str = "none"
    ai_model: str = "gpt-4o-mini"

    # Frontend
    frontend_api_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_mime_list(self) -> list[str]:
        return [m.strip() for m in self.allowed_evidence_mime_types.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
