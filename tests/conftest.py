"""Test harness.

Runs against a real MySQL database (``cdhrs_test`` by default, override with
TEST_DATABASE_URL) so ENUMs, FKs and JSON behave exactly as in production.
The KV store uses the in-memory backend (APP_ENV=test) and is flushed per test.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

os.environ["APP_ENV"] = "test"
os.environ["COOKIE_SECURE"] = "false"
os.environ["REDIS_URL"] = ""
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "mysql+pymysql://cdhrs:cdhrs_dev_pw@127.0.0.1:3306/cdhrs_test?charset=utf8mb4"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-secret-key")
os.environ["UPLOAD_DIR"] = "storage/test-uploads"
os.environ["BACKUP_DIR"] = "storage/test-backups"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
import app.models  # noqa: E402,F401
from app.services.common.kvstore import kv  # noqa: E402
from app.services.common.seed import DEMO_PASSWORD, seed_demo, seed_rbac, seed_settings  # noqa: E402

assert "cdhrs_test" in settings.database_url or os.environ.get("TEST_DATABASE_URL"), "refusing to run tests against a non-test DB"


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[dict[str, str]]:
    import shutil

    from alembic import command
    from alembic.config import Config

    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    # Build the schema through the real migrations (proves they match the models).
    from app.config import BASE_DIR

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.cmd_opts = type("o", (), {"x": [f"db_url={settings.database_url}"]})()  # type: ignore[assignment]
    command.upgrade(cfg, "head")
    for d in (settings.upload_dir, settings.backup_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        seed_rbac(db)
        seed_settings(db)
        summary = seed_demo(db)
        db.commit()
    yield summary.upis


@pytest.fixture
def upis(_database: dict[str, str]) -> dict[str, str]:
    return _database


@pytest.fixture(autouse=True)
def _flush_kv() -> None:
    kv.flush()  # type: ignore[attr-defined]


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def portal_for(username: str) -> str:
    if username.startswith(("dr.", "staff")):
        return "doctor"
    if username.startswith("hadmin"):
        return "hospital-admin"
    if username.startswith("sysadmin"):
        return "system-admin"
    return "patient"


class Client(TestClient):
    """TestClient that knows how to fetch a CSRF token and sign in."""

    def csrf(self) -> str:
        token = self.get("/api/v1/session/status").json()["csrf_token"]
        assert token
        return token

    def api(self, method: str, url: str, **kw):
        headers = kw.pop("headers", {})
        headers.setdefault("X-CSRF-Token", self.csrf())
        return self.request(method, url, headers=headers, **kw)

    def first_login(self, username: str, password: str, portal: str, new_password: str = "Own#Password2026"):
        """Sign in to an admin-created account and complete the forced password change."""
        r = self.login(username, password, portal=portal)
        assert r.json()["redirect"] == "/account/change-password", r.text
        r = self.api("POST", "/api/v1/auth/password", json={"current_password": password, "new_password": new_password})
        assert r.status_code == 200, r.text
        return r

    def login(self, username: str, password: str = DEMO_PASSWORD, portal: str | None = None):
        r = self.api("POST", "/api/v1/auth/login", json={"identifier": username, "password": password, "portal": portal or portal_for(username)})
        assert r.status_code == 200, r.text
        return r


@pytest.fixture
def client() -> Iterator[Client]:
    from app.main import app

    with Client(app, base_url="http://testserver", follow_redirects=False) as c:
        yield c


def make_client() -> Client:
    from app.main import app

    return Client(app, base_url="http://testserver", follow_redirects=False)
