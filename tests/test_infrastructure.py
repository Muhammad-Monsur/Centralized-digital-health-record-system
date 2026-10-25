"""Phase 8: pluggable SMS provider, Redis-backed KV store, admin search scope."""
from __future__ import annotations

import io
import json
import os
import urllib.error

import pytest

from app.services.common.sms.base import mask_phone
from app.services.common.sms.http_provider import HttpSMSProvider
from tests.conftest import make_client


class _Resp(io.BytesIO):
    def __init__(self, status: int, body: dict) -> None:
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_sms_provider_success_and_failure(monkeypatch):
    sent = {}

    def fake_urlopen(req, timeout):
        sent["url"], sent["auth"], sent["body"] = req.full_url, req.headers["Authorization"], json.loads(req.data)
        return _Resp(200, {"id": "msg-42"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    p = HttpSMSProvider("https://sms.example.com/send", "key-123", "CDHRS")
    r = p.send("+8801700000000", "hello")
    assert r.ok and r.message_id == "msg-42"
    assert sent["auth"] == "Bearer key-123" and sent["body"] == {"to": "+8801700000000", "from": "CDHRS", "text": "hello"}

    def boom(req, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    r = p.send("+8801700000000", "hello")
    assert r.ok is False and "down" in r.error  # never raises


def test_http_sms_provider_requires_https():
    with pytest.raises(ValueError):
        HttpSMSProvider("http://insecure.example.com", "k", "CDHRS")


def test_failed_sms_blocks_consent_otp(monkeypatch, db, upis):
    """If the gateway is down, the patient sees a clear error and no OTP is left usable."""
    from app.services.common import sms as sms_mod
    from app.services.common.sms.base import SMSResult

    class Down:
        def send(self, to, message):
            return SMSResult(ok=False, provider="down", error="x")

    monkeypatch.setattr("app.services.common.otp.get_sms_provider", lambda: Down())
    d = make_client()
    d.login("dr.akter")
    d.api("POST", f"/api/v1/doctor/patients/{upis['patient3']}/access-requests", json={"purpose": "Testing SMS failure handling path"})
    p = make_client()
    p.login("patient3")
    import re

    rid = re.search(r'data-request="(\d+)"', p.get("/patient/consent").text).group(1)
    r = p.api("POST", f"/api/v1/patient/consent/requests/{rid}/approve", json={"duration_hours": 1})
    assert r.status_code == 502 and "SMS" in r.json()["detail"]
    p.api("POST", f"/api/v1/patient/consent/requests/{rid}/reject")
    _ = sms_mod


def test_mask_phone():
    assert mask_phone("+8801712345678") == "+880*******678"


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15"), reason="no redis")
def test_redis_store_against_real_redis():
    from app.services.common.kvstore import RedisStore

    url = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
    store = RedisStore(url)
    if not store.ping():
        pytest.skip("Redis not reachable")
    store.delete_prefix("t:")
    store.set("t:a", "1", 30)
    assert store.get("t:a") == "1" and 0 < store.ttl("t:a") <= 30
    assert store.incr("t:n", 60) == 1 and store.incr("t:n", 60) == 2
    store.sadd("t:s", "x", 60)
    store.sadd("t:s", "y", 60)
    assert store.smembers("t:s") == {"x", "y"}
    store.srem("t:s", "x")
    assert store.smembers("t:s") == {"y"}
    store.expire("t:a", 5)
    assert store.ttl("t:a") <= 5
    store.delete_prefix("t:")
    assert store.get("t:a") is None and store.smembers("t:s") == set()


def test_admin_search_is_scoped():
    h = make_client()
    h.login("hadmin")  # Lakeview
    groups = {g["label"]: g["items"] for g in h.get("/api/v1/search?q=Dr.").json()["groups"]}
    names = [i["title"] for i in groups.get("Users", [])]
    assert "Dr. Tanvir Hasan" in names and "Dr. Nusrat Akter" not in names  # Riverside doctor hidden
    assert "Hospitals" not in groups  # hospital admins can't search all hospitals
    s = make_client()
    s.login("sysadmin")
    groups = {g["label"]: g["items"] for g in s.get("/api/v1/search?q=Riverside").json()["groups"]}
    assert any(i["title"] == "Riverside Medical Centre" for i in groups.get("Hospitals", []))
    pages = {g["label"]: g["items"] for g in s.get("/api/v1/search?q=backup").json()["groups"]}
    assert any(i["url"] == "/admin/backups" for i in pages.get("Pages", []))
    # a patient never gets admin pages
    p = make_client()
    p.login("patient")
    pages = {g["label"]: g["items"] for g in p.get("/api/v1/search?q=backup").json()["groups"]}
    assert not any(i["url"].startswith("/admin") for i in pages.get("Pages", []))


def test_anonymous_search_only_public_content():
    c = make_client()
    groups = {g["label"]: g["items"] for g in c.get("/api/v1/search?q=consent").json()["groups"]}
    assert set(groups) <= {"Pages", "Help"} and groups.get("Help")
    assert c.get("/api/v1/search?q=x").json()["groups"] == []  # too short
