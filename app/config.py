"""Application configuration.

All settings are read from environment variables (or a local ``.env`` file)
via pydantic-settings, so no secret ever lives in source code.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
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
    # Public demo deployment: fictional demo accounts may be seeded, SMS codes are shown on
    # screen (console provider) and every page carries a "demo" banner. Never for real patients.
    demo_mode: bool = False

    # --- Database ----------------------------------------------------------------
    database_url: str = "mysql+pymysql://cdhrs:cdhrs_dev_pw@127.0.0.1:3306/cdhrs?charset=utf8mb4"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800  # seconds; below MySQL's wait_timeout
    db_pool_timeout: int = 30
    sql_echo: bool = False
    # TLS to MySQL (hosted databases such as Aiven). "" = off. REQUIRED = encrypted;
    # VERIFY_CA / VERIFY_IDENTITY = also verify the server certificate against DB_SSL_CA.
    # A "?ssl-mode=..." in DATABASE_URL (as Aiven gives it) sets this automatically.
    db_ssl_mode: str = ""
    db_ssl_ca: str = ""  # the CA certificate itself (PEM text) or a path to it

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
    # "disk" = documents only in UPLOAD_DIR. "database" = also kept in MySQL, so they survive
    # hosts without a persistent disk (e.g. free cloud plans); the disk is then only a cache.
    file_storage: Literal["disk", "database"] = "disk"

    # OpenAPI docs at /api/docs. Default: on in development, off in production.
    enable_api_docs: bool | None = None

    # --- Static assets / CDN -------------------------------------------------------------
    static_url_prefix: str = "/static"  # set to https://cdn.example.com/static for a CDN
    use_built_assets: bool = False  # True = serve hashed, minified bundles from static/dist

    @field_validator("redis_url", "sms_http_url", "sms_http_api_key", "sms_http_sender_id", "static_url_prefix", "base_url", mode="before")
    @classmethod
    def _empty_str(cls, v: object) -> object:
        return "" if v is None else v  # "KEY=" in .env means empty, not missing

    @field_validator("database_url", mode="before")
    @classmethod
    def _sqlalchemy_mysql_url(cls, v: object) -> object:
        """Accept a plain ``mysql://`` URL (as hosting providers such as Railway give it)."""
        if isinstance(v, str) and v.startswith("mysql://"):
            v = "mysql+pymysql://" + v[len("mysql://"):]
            if "charset=" not in v:
                v += ("&" if "?" in v else "?") + "charset=utf8mb4"
        return v

    @model_validator(mode="after")
    def _ssl_from_url(self) -> "Settings":
        """Move ``ssl-mode`` (not a PyMySQL option) from DATABASE_URL into DB_SSL_MODE."""
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(self.database_url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        mode = next((v for k, v in query if k.lower() in ("ssl-mode", "ssl_mode", "sslmode")), None)
        if mode is not None:
            rest = [(k, v) for k, v in query if k.lower() not in ("ssl-mode", "ssl_mode", "sslmode")]
            self.database_url = urlunsplit(parts._replace(query=urlencode(rest)))
            if not self.db_ssl_mode:
                self.db_ssl_mode = mode
        return self

    def db_connect_args(self) -> dict:
        """PyMySQL connect arguments for TLS, from DB_SSL_MODE / DB_SSL_CA."""
        import ssl

        mode = self.db_ssl_mode.strip().upper().replace("-", "_")
        if mode in ("", "DISABLED", "DISABLE", "PREFERRED", "FALSE", "OFF"):
            return {}
        ca = self.db_ssl_ca.strip()
        if ca and "BEGIN CERTIFICATE" not in ca:
            ca = Path(ca).read_text()
        ctx = ssl.create_default_context(cadata=ca or None)
        if ca:  # verify the server against the given CA (and its name for VERIFY_IDENTITY)
            ctx.check_hostname = mode == "VERIFY_IDENTITY"
        else:  # REQUIRED without a CA: encrypted, server certificate not checked (MySQL semantics)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return {"ssl": ctx}

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
        elif "redis_dev_pw" in self.redis_url or ("@" not in self.redis_url and not self._redis_is_private()):
            problems.append("REDIS_URL must include a non-default password")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (serve over HTTPS)")
        if self.sms_provider == "console" and not self.demo_mode:
            problems.append("SMS_PROVIDER=console would print OTP codes to the log (allowed only with DEMO_MODE=true)")
        if self.debug:
            problems.append("DEBUG must be false")
        return problems

    def _redis_is_private(self) -> bool:
        """A single-label host (e.g. Render's ``red-abc123``) is only reachable on the platform's
        private network, so a password-less URL is acceptable there."""
        from urllib.parse import urlsplit

        host = urlsplit(self.redis_url).hostname or ""
        return bool(host) and "." not in host and host not in ("localhost",)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def api_docs_enabled(self) -> bool:
        # Default: on in development and on a public demo (the footer links to it), off in production.
        return self.enable_api_docs if self.enable_api_docs is not None else (not self.is_production or self.demo_mode)

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings: Settings = get_settings()
