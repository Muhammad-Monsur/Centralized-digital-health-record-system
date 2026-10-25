"""Phase 2: authentication, sessions, CSRF, lockout, security headers."""
from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, User
from app.services.common.security import generate_upi, normalize_upi, password_problems
from tests.conftest import make_client


def test_security_headers_and_no_store(client):
    r = client.get("/login")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "'nonce-" in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in r.text  # inline theme script carries this request's nonce


def test_csrf_required_for_mutations(client):
    r = client.post("/api/v1/auth/login", json={"identifier": "patient", "password": "Demo@12345"})
    assert r.status_code == 403
    r = client.post("/api/v1/auth/login", json={"identifier": "patient", "password": "Demo@12345"}, headers={"X-CSRF-Token": "forged-token-forged-token-forged-token-1234"})
    assert r.status_code == 403


def test_cross_origin_post_rejected_even_with_token(client):
    token = client.csrf()
    r = client.post("/api/v1/auth/login", json={"identifier": "patient", "password": "Demo@12345"}, headers={"X-CSRF-Token": token, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_login_success_sets_hardened_cookie_and_redirects_to_portal(client):
    r = client.login("patient")
    assert r.json()["redirect"] == "/patient"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age" not in cookie
    st = client.get("/api/v1/session/status").json()
    assert st["authenticated"] and 0 < st["expires_in"] <= 15 * 60


def test_login_redirects_by_role(client):
    assert client.login("dr.hasan").json()["redirect"] == "/doctor"
    c2 = make_client()
    assert c2.login("sysadmin").json()["redirect"] == "/admin"


def test_each_role_has_its_own_login_page(client):
    for path in ("/login", "/doctor/login", "/hospital-admin/login", "/system-admin/login", "/admin/login"):
        assert client.get(path).status_code == 200, path
    assert client.get("/register/doctor").status_code == 404  # doctors cannot self-register


def test_wrong_portal_is_rejected_generically(client):
    # Correct password, wrong door -> same message as a wrong password, no session.
    for user, portal in (("dr.hasan", "patient"), ("patient", "doctor"), ("hadmin", "system-admin"), ("sysadmin", "hospital-admin")):
        r = client.api("POST", "/api/v1/auth/login", json={"identifier": user, "password": "Demo@12345", "portal": portal})
        assert r.status_code == 401, (user, portal)
        assert r.json()["detail"] == "That username or password isn't right."
        assert client.get("/api/v1/session/status").json()["authenticated"] is False


def test_staff_and_email_login_through_doctor_portal(client):
    assert client.login("staff.lab@cdhrs.example.com", portal="doctor").json()["redirect"] == "/doctor"


def test_logout_returns_to_role_login(client):
    client.login("dr.hasan")
    assert client.api("POST", "/api/v1/auth/logout").json()["redirect"].startswith("/doctor/login")


def test_anonymous_redirect_goes_to_matching_login(client):
    assert client.get("/patient").headers["location"].startswith("/login?next=")
    assert client.get("/patient/records?page=2").headers["location"] == "/login?next=/patient/records%3Fpage%3D2"


def test_session_rotates_on_login(client):
    client.login("patient")
    first = client.cookies.get("cdhrs_session")
    client.api("POST", "/api/v1/auth/logout")
    client.login("patient")
    assert client.cookies.get("cdhrs_session") != first


def test_open_redirect_blocked(client):
    r = client.api("POST", "/api/v1/auth/login", json={"identifier": "patient", "password": "Demo@12345", "next": "//evil.example/x"})
    assert r.json()["redirect"] == "/patient"


def test_wrong_password_is_generic(client):
    r1 = client.api("POST", "/api/v1/auth/login", json={"identifier": "patient3", "password": "Wrong@12345"})
    r2 = client.api("POST", "/api/v1/auth/login", json={"identifier": "no-such-user", "password": "Wrong@12345"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_account_lockout_after_failures(client, db):
    for _ in range(5):
        client.api("POST", "/api/v1/auth/login", json={"identifier": "patient3", "password": "Wrong@12345"})
    r = client.api("POST", "/api/v1/auth/login", json={"identifier": "patient3", "password": "Demo@12345"})
    assert r.status_code == 429  # correct password refused while locked
    user = db.scalar(select(User).where(User.username == "patient3"))
    assert user.locked_until is not None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.account_locked", AuditLog.user_id == user.user_id))
    user.locked_until = None
    db.commit()


def test_ip_rate_limit(client):
    codes = [client.api("POST", "/api/v1/auth/login", json={"identifier": f"ghost{i}", "password": "x"}).status_code for i in range(32)]
    assert 429 in codes


def test_logout_destroys_session(client):
    client.login("patient")
    cookie = client.cookies.get("cdhrs_session")
    client.api("POST", "/api/v1/auth/logout")
    other = make_client()
    other.cookies.set("cdhrs_session", cookie)
    assert other.get("/api/v1/session/status").json()["authenticated"] is False


def test_password_change_kills_other_sessions(client):
    a = client
    a.login("patient2")
    b = make_client()
    b.login("patient2")
    r = a.api("POST", "/api/v1/auth/password", json={"current_password": "Demo@12345", "new_password": "Changed#Pass2026"})
    assert r.status_code == 200, r.text
    assert b.get("/api/v1/session/status").json()["authenticated"] is False
    assert a.get("/api/v1/session/status").json()["authenticated"] is True
    # change back so other tests keep working
    r = a.api("POST", "/api/v1/auth/password", json={"current_password": "Changed#Pass2026", "new_password": "Demo@12345x"})
    assert r.status_code == 200
    from app.database import SessionLocal
    from app.services.common.security import hash_password

    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.username == "patient2"))
        u.password_hash = hash_password("Demo@12345")
        s.commit()


def test_weak_password_rejected(client):
    client.login("patient")
    r = client.api("POST", "/api/v1/auth/password", json={"current_password": "Demo@12345", "new_password": "abcdefghij"})
    assert r.status_code == 422


def test_password_rules():
    assert password_problems("Demo@12345") == []
    assert password_problems("short") != []
    assert any("username" in p for p in password_problems("Ayesha#2026x", username="ayesha"))


def test_upi_format_and_checksum():
    from app.services.common.security import _ALPHABET

    seen = {generate_upi() for _ in range(2000)}
    assert len(seen) == 2000
    for upi in list(seen)[:60]:
        assert normalize_upi(upi) == upi
        assert normalize_upi(upi.lower().replace("-", " ")) == upi
        raw = upi.replace("-", "")[3:]
        for i in range(12):  # every single-character substitution is caught
            for c in _ALPHABET:
                if c != raw[i]:
                    assert normalize_upi(raw[:i] + c + raw[i + 1:]) is None
        for i in range(11):  # every adjacent swap is caught
            if raw[i] != raw[i + 1]:
                assert normalize_upi(raw[:i] + raw[i + 1] + raw[i] + raw[i + 2:]) is None


def test_inactive_user_cannot_sign_in(client, db):
    from app.models.enums import UserStatus

    u = db.scalar(select(User).where(User.username == "patient3"))
    u.status = UserStatus.INACTIVE
    db.commit()
    r = client.api("POST", "/api/v1/auth/login", json={"identifier": "patient3", "password": "Demo@12345"})
    assert r.status_code == 403
    u.status = UserStatus.ACTIVE
    db.commit()


def test_html_404_and_api_404(client):
    r = client.get("/definitely-missing")
    assert r.status_code == 404 and "text/html" in r.headers["content-type"]
    r = client.get("/api/v1/definitely-missing")
    assert r.status_code == 404 and r.json()["detail"]


def test_compression(client):
    r = client.get("/login", headers={"Accept-Encoding": "br"})
    assert r.headers.get("content-encoding") == "br"
