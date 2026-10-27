"""Administrators in a real browser: a hospital admin creates a doctor, who must change the password (Selenium)."""
from __future__ import annotations

import random
import urllib.error
import urllib.request

from tests.ui.helpers import Browser, login


def test_hospital_admin_creates_doctor_who_must_change_password(new_browser):
    admin = new_browser()
    login(admin, "hadmin@cdhrs.example.com")
    admin.go("/admin/users")
    admin.press("Create doctor")
    admin.visible("#account-modal")
    n = random.randint(1000, 9999)
    email = f"dr.ui{n}@cdhrs.example.com"
    admin.fill("#a-name", f"Dr. Test Doctor {n}")
    admin.fill("#a-email", email)
    admin.fill("#a-designation", "Consultant")
    admin.fill("#a-licence", f"BMDC-A-{n}")
    admin.fill("#a-password", "Initial#Pass2026")
    admin.press("Create account", within="#account-modal")
    admin.hidden("#account-modal")
    admin.go("/admin/users")
    admin.wait_text("body", f"Dr. Test Doctor {n}")

    # the new doctor signs in at the doctor portal and is sent to change the password first
    doctor = new_browser()
    doctor.go("/doctor/login")
    doctor.fill("#identifier", email)
    doctor.fill("#password", "Initial#Pass2026")
    doctor.press("Sign in")
    doctor.wait_url(r"/account/change-password")
    doctor.go("/doctor")
    doctor.wait_url(r"/account/change-password")  # nothing else works until it is changed
    doctor.fill("#current_password", "Initial#Pass2026")
    doctor.fill("#new_password", "Own#DoctorPass2026")
    doctor.press("Save and continue")
    doctor.wait_url(r"/doctor(?!/login)")
    assert "change-password" not in doctor.url


def test_system_admin_sees_system_pages(browser: Browser):
    login(browser, "sysadmin@cdhrs.example.com")
    for path in ("/admin", "/admin/hospitals", "/admin/roles", "/admin/audit", "/admin/backups"):
        browser.go(path)
        assert browser.visible("h1").text, path


def test_hospital_admin_cannot_open_system_pages(browser: Browser):
    login(browser, "hadmin@cdhrs.example.com")
    browser.go("/admin/backups")
    assert "Access denied" in browser.driver.title
    # the same request with the browser's own session cookie gets HTTP 403
    cookie = "; ".join(f"{c['name']}={c['value']}" for c in browser.driver.get_cookies())
    req = urllib.request.Request(browser.base + "/admin/backups", headers={"Cookie": cookie})
    try:
        urllib.request.urlopen(req, timeout=10)
        status = 200
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 403
