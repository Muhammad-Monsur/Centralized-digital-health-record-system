"""Registration, sign-in, portals and sign-out, through the real forms."""
from __future__ import annotations

import random
import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import LOGIN_PATHS, login, logout


def test_register_form_shows_and_clears_field_errors(page: Page):
    page.goto("/register")
    page.fill("#username", "ab")
    page.get_by_role("button", name="Create account").click()
    username = page.locator("#username")
    expect(username).to_have_attribute("aria-invalid", "true")
    expect(page.locator('[data-error-for="username"]')).not_to_be_empty()
    # the red state goes away as soon as the field is edited
    username.press_sequentially("c123")
    expect(username).not_to_have_attribute("aria-invalid", "true")
    expect(page.locator('[data-error-for="username"]')).to_be_empty()


@pytest.mark.parametrize("value, valid", [("monsur123", True), ("md.monsur", True), ("monsur_123", True),
                                          ("_monsur", False), ("monsur 123", False), ("ab", False)])
def test_register_username_rule_matches_the_hint(page: Page, value: str, valid: bool):
    page.goto("/register")
    page.fill("#username", value)
    assert page.locator("#username").evaluate("e => e.checkValidity()") is valid


def test_register_new_patient_gets_a_upi(page: Page):
    n = random.randint(10_000_000, 99_999_999)
    page.goto("/register")
    page.fill("#full_name", "Test Patient")
    page.fill("#date_of_birth", "1999-05-04")
    page.select_option("#gender", "male")
    page.select_option("#blood_group", "B+")
    page.fill("#username", f"e2e{n}")
    page.fill("#email", f"e2e{n}@cdhrs.example.com")
    page.fill("#phone", f"017{n}")
    page.fill("#password", "Strong#Pass2026x")
    page.fill("#confirm_password", "Strong#Pass2026x")
    page.check('input[name="accept_terms"]')
    page.get_by_role("button", name="Create account").click()
    page.wait_for_url(re.compile(r"/login\?reason=registered"))
    expect(page.locator(".alert-success")).to_contain_text("Account created")
    login(page, f"e2e{n}", "Strong#Pass2026x")
    page.wait_for_url(re.compile(r"/patient"))
    expect(page.locator("body")).to_contain_text("CDH-")  # the new Unique Patient ID


def test_wrong_password_shows_an_error_and_stays(page: Page):
    page.goto("/login")
    page.fill("#identifier", "patient")
    page.fill("#password", "Wrong#Password1")
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator("[data-form-error]")).to_be_visible()
    assert page.url.endswith("/login")


def test_accounts_only_sign_in_through_their_own_portal(page: Page):
    page.goto("/login")  # patient portal
    page.fill("#identifier", "dr.hasan@cdhrs.example.com")
    page.fill("#password", "Demo@12345")
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator("[data-form-error]")).to_be_visible()
    assert page.url.endswith("/login")


@pytest.mark.parametrize("username, home", [
    ("patient", "/patient"), ("dr.hasan@cdhrs.example.com", "/doctor"),
    ("hadmin@cdhrs.example.com", "/admin"), ("sysadmin@cdhrs.example.com", "/admin"),
])
def test_each_role_lands_on_its_dashboard_and_signs_out(page: Page, live_server: str, username: str, home: str):
    login(page, username)
    assert page.url.startswith(live_server + home), page.url
    logout(page)
    page.goto(home)
    page.wait_for_url(re.compile(r"/[\w-]*/?login"))  # signed out: the portal sends you back to sign in


def test_admin_chooser_links_to_both_admin_portals(page: Page):
    page.goto("/admin/login")
    for path in (LOGIN_PATHS["hospital-admin"], LOGIN_PATHS["system-admin"]):
        expect(page.locator(f'a[href="{path}"]').first).to_be_visible()
