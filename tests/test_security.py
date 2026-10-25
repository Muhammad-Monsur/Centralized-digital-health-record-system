"""Phase 8: systematic security tests (route inventory, CSRF everywhere, role isolation,
injection, and regression tests for the independent security review's findings)."""
from __future__ import annotations

import re
import time

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.main import app
from app.models import AuditLog, Patient, User
from app.services.common.kvstore import kv
from app.services.common.sms.console import OUTBOX
from tests.conftest import make_client

# Routes that are deliberately public (everything else must require a session).
PUBLIC = {
    "/", "/help", "/privacy", "/register", "/login", "/doctor/login", "/hospital-admin/login", "/system-admin/login",
    "/admin/login", "/healthz", "/api/v1/search", "/api/v1/faq", "/api/v1/session/status",
    "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/patients/register", "/api/v1/newsletter", "/api/v1/contact",
    "/api/openapi.json", "/api/docs", "/api/docs/oauth2-redirect", "/api/redoc",
}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _walk(routes):
    """Flatten routes, descending into included routers (this FastAPI keeps them nested)."""
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _walk(inner.routes)
        elif isinstance(r, APIRoute) or (hasattr(r, "methods") and hasattr(r, "path")):
            yield r


def _routes():
    for r in _walk(app.routes):
        if r.path.startswith("/static"):
            continue
        for m in sorted(getattr(r, "methods", None) or []):
            if m != "HEAD":
                yield m, r.path


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda m: "CDH-0000-0000-0000" if "upi" in m.group(0) else ("cdhrs-backup-20260101-000000.tar.gz" if "name" in m.group(0) else "1"), path)


ALL_ROUTES = sorted(set(_routes()))


def test_route_inventory_is_not_empty():
    assert len(ALL_ROUTES) > 60


@pytest.mark.parametrize("method,path", [r for r in ALL_ROUTES if r[1] not in PUBLIC])
def test_every_non_public_route_requires_sign_in(client, method, path):
    url = _concrete(path)
    if method in MUTATING:
        r = client.api(method, url, json={})
        assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}"
    else:
        r = client.request(method, url)
        assert r.status_code in (401, 303), f"{method} {path} -> {r.status_code}"
        if r.status_code == 303:
            assert "/login" in r.headers["location"]


@pytest.mark.parametrize("method,path", [r for r in ALL_ROUTES if r[0] in MUTATING])
def test_every_mutation_requires_csrf_token(method, path):
    c = make_client()
    c.login("sysadmin")
    r = c.request(method, _concrete(path), json={})
    assert r.status_code == 403 and "another site" in r.json()["detail"], f"{method} {path} -> {r.status_code}"


@pytest.mark.parametrize("user,prefixes", [
    ("patient", ("/api/v1/admin/", "/api/v1/doctor/", "/admin", "/doctor")),
    ("dr.hasan", ("/api/v1/admin/", "/api/v1/patient/", "/admin", "/patient")),
    ("staff.lab", ("/api/v1/admin/", "/api/v1/patient/", "/admin", "/patient")),
    ("hadmin", ("/api/v1/patient/", "/api/v1/doctor/", "/patient", "/doctor")),
    ("sysadmin", ("/api/v1/patient/", "/api/v1/doctor/", "/patient", "/doctor")),
])
def test_roles_cannot_reach_other_portals(user, prefixes):
    c = make_client()
    c.login(user)
    checked = 0
    for method, path in ALL_ROUTES:
        if not path.startswith(prefixes) or path in PUBLIC or path.endswith("/login"):
            continue
        if path.startswith("/admin") and user in ("hadmin", "sysadmin"):
            continue
        r = c.api(method, _concrete(path), json={}) if method in MUTATING else c.request(method, _concrete(path))
        assert r.status_code in (403, 404, 422), f"{user}: {method} {path} -> {r.status_code}"
        if r.status_code == 422:  # body validation ran -> the permission check must have come first; make sure
            assert method in MUTATING, f"{user}: {method} {path}"
        checked += 1
    assert checked > 3


def test_mutations_rejected_before_validation_for_wrong_role():
    """A 422 would mean the body was parsed before authorisation; check permissions run first."""
    c = make_client()
    c.login("patient")
    for path in ("/api/v1/admin/users", "/api/v1/admin/hospitals", "/api/v1/admin/settings"):
        assert c.api("POST" if not path.endswith("settings") else "PUT", path, json={"garbage": True}).status_code == 403, path


# ---------------------------------------------------------------- injection

XSS = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def test_stored_xss_is_escaped_everywhere(db, upis):
    p = make_client()
    p.login("patient")
    r = p.api("POST", "/api/v1/patient/records", data={"title": XSS[:180], "details": XSS, "information_type": "other",
                                                        "information_date": "2024-01-01", "visibility": "public"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    detail = p.get(f"/patient/records/{rid}").text
    listing = p.get("/patient/records", params={"q": "script"}).text  # filtered so the record is on page 1
    for page in (detail, listing):
        assert "<script>alert" not in page and "<img src=x" not in page
        assert "&lt;script&gt;" in page
    d = make_client()
    d.login("dr.hasan")
    html = d.get(f"/doctor/patients/{upis['patient']}/records/{rid}").text
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    p.api("DELETE", f"/api/v1/patient/records/{rid}")


@pytest.mark.parametrize("payload", ["' OR '1'='1", "1; DROP TABLE user; --", "%' UNION SELECT password_hash FROM user -- ", "\\", "_%_%"])
def test_sql_injection_payloads_are_inert(payload):
    p = make_client()
    p.login("patient2")
    r = p.get("/api/v1/patient/records", params={"q": payload})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert p.get("/api/v1/search", params={"q": payload}).status_code == 200
    a = make_client()
    a.login("sysadmin")
    assert a.get("/admin/audit", params={"q": payload, "user": payload}).status_code == 200
    assert a.get("/admin/users", params={"q": payload}).status_code == 200


def test_upi_lookup_rejects_injection():
    d = make_client()
    d.login("dr.hasan")
    assert d.api("POST", "/api/v1/doctor/patients/lookup", json={"upi": "CDH-' OR 1=1 --xx"}).status_code == 422
    assert d.get("/doctor/patients/' OR 1=1 --").status_code == 404


# ---------------------------------------------------------------- headers & sessions

@pytest.mark.parametrize("user,path", [("patient", "/patient"), ("patient", "/patient/records/1"), ("dr.hasan", "/doctor"), ("sysadmin", "/admin/audit")])
def test_phi_pages_are_never_cacheable(user, path):
    c = make_client()
    c.login(user)
    r = c.get(path)
    assert "no-store" in r.headers["cache-control"]
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_preset_session_cookie_is_not_adopted():
    """Session fixation: an id planted before sign-in is never promoted to a real session."""
    planted = "attacker-chosen-session-id-attacker-chosen-session"
    c = make_client()
    token = c.csrf()
    r = c.post("/api/v1/auth/login", json={"identifier": "patient", "password": "Demo@12345", "portal": "patient"},
               headers={"X-CSRF-Token": token, "Cookie": f"cdhrs_csrf={c.cookies.get('cdhrs_csrf')}; cdhrs_session={planted}"})
    assert r.status_code == 200
    issued = re.search(r"cdhrs_session=([^;]+)", r.headers["set-cookie"]).group(1)
    assert issued != planted
    other = make_client()
    assert other.get("/api/v1/session/status", headers={"Cookie": f"cdhrs_session={planted}"}).json()["authenticated"] is False


def test_idle_session_expires(monkeypatch):
    c = make_client()
    c.login("patient")
    assert c.get("/api/v1/session/status").json()["authenticated"]
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 16 * 60)
    assert c.get("/api/v1/session/status").json()["authenticated"] is False
    assert c.get("/api/v1/patient/records").status_code == 401


# ---------------------------------------------------------------- review findings (regressions)

@pytest.mark.parametrize("nxt", ["/\t/evil.example", "/\r/evil.example", "//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)"])
def test_open_redirect_variants_blocked(nxt):
    c = make_client()
    r = c.api("POST", "/api/v1/auth/login", json={"identifier": "patient3", "password": "Demo@12345", "portal": "patient", "next": nxt})
    assert r.json()["redirect"] == "/patient"


def test_csrf_token_is_masked_differently_each_response():
    c = make_client()
    a = c.get("/api/v1/session/status").json()["csrf_token"]
    b = c.get("/api/v1/session/status").json()["csrf_token"]
    assert a != b
    # both decode to the same secret, so either works
    assert c.post("/api/v1/newsletter", json={"email": "mask1@example.com"}, headers={"X-CSRF-Token": a}).status_code == 201
    assert c.post("/api/v1/newsletter", json={"email": "mask2@example.com"}, headers={"X-CSRF-Token": b}).status_code == 201


def test_phone_change_needs_password_and_alerts_old_number(db):
    c = make_client()
    c.login("patient3")
    p = db.scalar(select(Patient).join(User).where(User.username == "patient3"))
    body = {"full_name": p.user.full_name, "email": p.user.email, "phone": "01999999999", "date_of_birth": p.date_of_birth.isoformat(),
            "gender": p.gender.value, "blood_group": p.blood_group.value, "address": p.address, "profile_visibility": p.profile_visibility.value}
    r = c.api("PUT", "/api/v1/patient/profile", json=body)
    assert r.status_code == 403 and "current_password" in r.json()["fields"]
    assert c.api("PUT", "/api/v1/patient/profile", json={**body, "current_password": "Wrong#Pass123"}).status_code == 403
    old = p.user.phone
    assert c.api("PUT", "/api/v1/patient/profile", json={**body, "current_password": "Demo@12345"}).status_code == 200
    assert any(to == old and "was changed" in msg for to, msg in OUTBOX[-3:])
    # change back (other tests rely on the original number)
    assert c.api("PUT", "/api/v1/patient/profile", json={**body, "phone": old, "current_password": "Demo@12345"}).status_code == 200
    # editing other fields alone needs no password
    body2 = {**body, "phone": old, "address": "Changed address 1"}
    assert c.api("PUT", "/api/v1/patient/profile", json=body2).status_code == 200


def test_attempted_usernames_not_stored_in_clear():
    c = make_client()
    c.api("POST", "/api/v1/auth/login", json={"identifier": "secret.person@example.com", "password": "x", "portal": "patient"})
    keys = list(kv._data) if hasattr(kv, "_data") else []  # in-memory store in tests
    assert keys and not any("secret.person" in k for k in keys)


def test_inter_hospital_view_hides_record_titles(upis):
    d = make_client()
    d.login("dr.akter")  # Riverside opens a Lakeview-written public record
    html = d.get(f"/doctor/patients/{upis['patient']}").text
    rid = re.search(r'/records/(\d+)">Complete blood count', html).group(1)
    d.get(f"/doctor/patients/{upis['patient']}/records/{rid}")
    a = make_client()
    a.login("sysadmin")
    page = a.get("/admin/emergency?tab=inter").text
    assert "Dr. Nusrat Akter" in page and "Complete blood count" not in page


def test_api_docs_disabled_in_production(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "enable_api_docs", None)
    assert settings.api_docs_enabled is False
    monkeypatch.setattr(settings, "enable_api_docs", True)
    assert settings.api_docs_enabled is True


def test_production_guard_lists_unsafe_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "cookie_secure", False)
    problems = settings.production_problems()
    assert any("REDIS_URL" in p for p in problems) and any("COOKIE_SECURE" in p for p in problems)


def test_restore_keeps_newer_audit_history(db):
    a = make_client()
    a.login("sysadmin")
    name = a.api("POST", "/api/v1/admin/backups").json()["name"]
    from app.services.common.audit import audit

    audit(db, action="admin.after_backup_marker", entity="test", user_id=None)
    db.commit()
    assert a.api("POST", f"/api/v1/admin/backups/{name}/restore", json={"confirm": "RESTORE"}).status_code == 200
    db.rollback()
    db.expire_all()
    assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.after_backup_marker")) is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "backup.restored")) is not None
