from __future__ import annotations

import random
import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import login


def test_hospital_admin_creates_doctor_who_must_change_password(new_page):
    admin = new_page()
    login(admin, "hadmin@cdhrs.example.com")
    admin.goto("/admin/users")
    admin.get_by_role("button", name="Create doctor").click()

    n = random.randint(1000, 9999)
    email = f"dr.e2e{n}@cdhrs.example.com"
    modal = admin.locator("#account-modal")
    expect(modal).to_be_visible()
    admin.fill("#a-name", f"Dr. Test Doctor {n}")
    admin.fill("#a-email", email)
    admin.fill("#a-designation", "Consultant")
    admin.fill("#a-licence", f"BMDC-A-{n}")
    admin.fill("#a-password", "Initial#Pass2026")
    modal.get_by_role("button", name="Create account").click()
    expect(modal).to_be_hidden()
    admin.goto("/admin/users")
    expect(admin.locator("body")).to_contain_text(f"Dr. Test Doctor {n}")

    # the new doctor signs in at the doctor portal and is sent to change the password first
    doctor = new_page()
    doctor.goto("/doctor/login")
    doctor.fill("#identifier", email)
    doctor.fill("#password", "Initial#Pass2026")
    doctor.get_by_role("button", name="Sign in", exact=True).click()
    doctor.wait_for_url(re.compile(r"/account/change-password"))
    doctor.goto("/doctor")
    doctor.wait_for_url(re.compile(r"/account/change-password"))  # nothing else works until it is changed
    doctor.fill("#current_password", "Initial#Pass2026")
    doctor.fill("#new_password", "Own#DoctorPass2026")
    doctor.get_by_role("button", name="Save and continue").click()
    doctor.wait_for_url(re.compile(r"/doctor(?!/login)"))
    assert "change-password" not in doctor.url


def test_system_admin_sees_system_pages(page: Page):
    login(page, "sysadmin@cdhrs.example.com")
    for path in ("/admin", "/admin/hospitals", "/admin/roles", "/admin/audit", "/admin/backups"):
        page.goto(path)
        expect(page.get_by_role("heading", level=1)).to_be_visible()


def test_hospital_admin_cannot_open_system_pages(page: Page):
    login(page, "hadmin@cdhrs.example.com")
    response = page.goto("/admin/backups")
    assert response.status == 403
