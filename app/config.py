from __future__ import annotations

import base64
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SecureShare"
    app_env: str = "development"
    local_demo_mode: bool = False
    debug: bool = False
    base_url: str = "http://localhost:8000"
    mongodb_uri: str = ""
    mongodb_database: str = Field(
        default="secureshare",
        validation_alias=AliasChoices("MONGODB_DATABASE", "MONGODB_DB_NAME"),
    )
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    smtp_host: str = Field(default="", validation_alias=AliasChoices("SMTP_HOST", "MAIL_SERVER"))
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    jwt_secret: str = ""
    session_secret: str = ""
    encryption_key: str = ""
    max_upload_bytes: int = 100 * 1024 * 1024
    storage_quota_bytes: int = 2 * 1024 * 1024 * 1024
    otp_expiry_seconds: int = 300
    otp_resend_seconds: int = 60
    otp_max_attempts: int = 5
    secure_cookies: bool | None = None
    local_blob_dir: Path = Path("var/blobs")

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug_flag(cls, value):
        if isinstance(value, str) and value.lower() in {"release", "production", "prod", "off", "no"}:
            return False
        return value

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        # Vercel deployments must use production secrets and persistent services
        # even when APP_ENV was accidentally left at its development default.
        return self.app_env.lower() == "production" or (
            os.getenv("VERCEL", "").strip().lower() in {"1", "true"}
        )

    @property
    def cookie_secure(self) -> bool:
        return self.secure_cookies if self.secure_cookies is not None else self.is_production

    def session_signing_secret(self) -> str:
        if self.session_secret:
            return self.session_secret
        if self.is_production:
            raise RuntimeError("SESSION_SECRET must be set in production")
        return os.environ.setdefault("SECURESHARE_DEV_SESSION_SECRET", secrets.token_urlsafe(48))

    def token_signing_secret(self) -> str:
        if self.jwt_secret:
            return self.jwt_secret
        if self.is_production:
            raise RuntimeError("JWT_SECRET must be set in production")
        return self.session_signing_secret()

    def encryption_secret(self) -> bytes:
        """Read a base64-encoded 32-byte AES key, creating a local dev key if needed."""
        if self.encryption_key:
            try:
                key = base64.urlsafe_b64decode(self.encryption_key.encode() + b"=" * (-len(self.encryption_key) % 4))
            except Exception as exc:
                raise RuntimeError("ENCRYPTION_KEY must be URL-safe base64 for exactly 32 bytes") from exc
            if len(key) != 32:
                raise RuntimeError("ENCRYPTION_KEY must decode to exactly 32 bytes")
            return key
        if self.is_production:
            raise RuntimeError("ENCRYPTION_KEY must be set in production")
        path = Path("var/dev-encryption.key")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            key = path.read_bytes()
        else:
            key = secrets.token_bytes(32)
            path.write_bytes(key)
        if len(key) != 32:
            raise RuntimeError("var/dev-encryption.key must contain exactly 32 bytes")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
