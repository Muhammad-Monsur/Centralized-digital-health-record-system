"""Application configuration.

All settings are read from environment variables (or a local ``.env`` file)
via pydantic-settings, so no secret ever lives in source code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # env_parse_none_str="": an empty value in .env (e.g. "ENABLE_API_DOCS=") means "not set".
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore", env_parse_none_str="")

    # --- Core -----------------------------------------------------------------
    app_name: str = "CDHRS"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    secret_key: str = Field(min_length=32)
    base_url: str = "http://localhost:8000"
    display_timezone: str = "Asia/Dhaka"  # data is stored in UTC; shown in this zone

    # --- Database ----------------------------------------------------------------
    database_url: str = "mysql+pymysql://cdhrs:cdhrs_dev_pw@127.0.0.1:3306/cdhrs?charset=utf8mb4"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800  # seconds; below MySQL's wait_timeout
    db_pool_timeout: int = 30
    sql_echo: bool = False

    # --- Redis (sessions, rate limiting, cache). Empty = in-memory fallback -------
    redis_url: str = ""

    # --- Sessions -------------------------------------------------------------------
    session_cookie_name: str = "cdhrs_session"
    session_idle_timeout_minutes: int = 15
    session_absolute_timeout_hours: int = 8
    session_warning_seconds: int = 60
    cookie_secure: bool = True

    # --- Login protection ----------------------------------------------------------
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # --- OTP / consent / emergency -----------------------------------------------------
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    access_request_ttl_hours: int = 72
    consent_default_hours: int = 24
    consent_max_hours: int = 168
    emergency_access_minutes: int = 60

    # --- SMS -----------------------------------------------------------------------------
    sms_provider: Literal["console", "http"] = "console"
    sms_http_url: str = ""
    sms_http_api_key: str = ""
    sms_http_sender_id: str = "CDHRS"

    # --- Files ---------------------------------------------------------------------------
    upload_dir: Path = BASE_DIR / "storage" / "uploads"
    backup_dir: Path = BASE_DIR / "storage" / "backups"
    max_upload_mb: int = 10

    # OpenAPI docs at /api/docs. Default: on in development, off in production.
    enable_api_docs: bool | None = None

    # --- Static assets / CDN -------------------------------------------------------------
    static_url_prefix: str = "/static"  # set to https://cdn.example.com/static for a CDN
    use_built_assets: bool = False  # True = serve hashed, minified bundles from static/dist

    @field_validator("redis_url", "sms_http_url", "sms_http_api_key", "sms_http_sender_id", "static_url_prefix", "base_url", mode="before")
    @classmethod
    def _empty_str(cls, v: object) -> object:
        return "" if v is None else v  # "KEY=" in .env means empty, not missing

    @field_validator("upload_dir", "backup_dir", mode="after")
    @classmethod
    def _absolute(cls, v: Path) -> Path:
        return v if v.is_absolute() else (BASE_DIR / v)

    def production_problems(self) -> list[str]:
        """Settings that are unsafe in production (startup refuses to continue)."""
        problems = []
        weak_secret = self.secret_key.startswith(("change-me", "test-secret")) or len(set(self.secret_key)) < 12
        if weak_secret:
            problems.append("SECRET_KEY is a placeholder or too simple")
        if any(pw in self.database_url for pw in ("cdhrs_dev_pw", "CHANGE_ME")):
            problems.append("DATABASE_URL uses a default password")
        if not self.redis_url:
            problems.append("REDIS_URL is required (sessions must be shared between instances)")
        elif "redis_dev_pw" in self.redis_url or "@" not in self.redis_url:
            problems.append("REDIS_URL must include a non-default password")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (serve over HTTPS)")
        if self.sms_provider == "console":
            problems.append("SMS_PROVIDER=console would print OTP codes to the log")
        if self.debug:
            problems.append("DEBUG must be false")
        return problems

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def api_docs_enabled(self) -> bool:
        return self.enable_api_docs if self.enable_api_docs is not None else not self.is_production

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings: Settings = get_settings()
