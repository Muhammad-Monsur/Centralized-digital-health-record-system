"""Registration, sign-in, portals and sign-out, through the real forms (Selenium)."""
from __future__ import annotations

import random

import pytest

from tests.ui.helpers import LOGIN_PATHS, Browser, login, logout


def test_register_form_shows_and_clears_field_errors(browser: Browser):
    browser.go("/register")
    browser.fill("#username", "ab")
    browser.press("Create account")
    browser.wait_attr("#username", "aria-invalid", "true")
    assert browser.text('[data-error-for="username"]')
    # the red state goes away as soon as the field is edited
    browser.find("#username").send_keys("c123")
    browser.wait(lambda d: browser.attr("#username", "aria-invalid") != "true")
    assert browser.find('[data-error-for="username"]').get_attribute("textContent").strip() == ""


@pytest.mark.parametrize("value, valid", [("monsur123", True), ("md.monsur", True), ("monsur_123", True),
                                          ("_monsur", False), ("monsur 123", False), ("ab", False)])
def test_register_username_rule_matches_the_hint(browser: Browser, value: str, valid: bool):
    browser.go("/register")
    browser.fill("#username", value)
    assert browser.js("return arguments[0].checkValidity()", browser.find("#username")) is valid


def test_register_new_patient_gets_a_upi(browser: Browser):
    n = random.randint(10_000_000, 99_999_999)
    browser.go("/register")
    browser.fill("#full_name", "Test Patient")
    browser.js("arguments[0].value = '1999-05-04'", browser.find("#date_of_birth"))
    browser.select("#gender", "male")
    browser.select("#blood_group", "B+")
    browser.fill("#username", f"ui{n}")
    browser.fill("#email", f"ui{n}@cdhrs.example.com")
    browser.fill("#phone", f"017{n}")
    browser.fill("#password", "Strong#Pass2026x")
    browser.fill("#confirm_password", "Strong#Pass2026x")
    browser.click('input[name="accept_terms"]')
    browser.press("Create account")
    browser.wait_url(r"/login\?reason=registered")
    browser.wait_text(".alert-success", "Account created")
    login(browser, f"ui{n}", "Strong#Pass2026x")
    browser.wait_url(r"/patient")
    browser.wait_text("body", "CDH-")  # the new Unique Patient ID


def test_wrong_password_shows_an_error_and_stays(browser: Browser):
    browser.go("/login")
    browser.fill("#identifier", "patient")
    browser.fill("#password", "Wrong#Password1")
    browser.press("Sign in")
    browser.visible("[data-form-error]")
    assert browser.url.endswith("/login")


def test_accounts_only_sign_in_through_their_own_portal(browser: Browser):
    browser.go("/login")  # patient portal
    browser.fill("#identifier", "dr.hasan@cdhrs.example.com")
    browser.fill("#password", "Demo@12345")
    browser.press("Sign in")
    browser.visible("[data-form-error]")
    assert browser.url.endswith("/login")


@pytest.mark.parametrize("username, home", [
    ("patient", "/patient"), ("dr.hasan@cdhrs.example.com", "/doctor"),
    ("hadmin@cdhrs.example.com", "/admin"), ("sysadmin@cdhrs.example.com", "/admin"),
])
def test_each_role_lands_on_its_dashboard_and_signs_out(browser: Browser, username: str, home: str):
    login(browser, username)
    assert browser.url.startswith(browser.base + home), browser.url
    logout(browser)
    browser.go(home)
    browser.wait_url(r"/[\w-]*/?login")  # signed out: the portal sends you back to sign in


def test_admin_chooser_links_to_both_admin_portals(browser: Browser):
    browser.go("/admin/login")
    for path in (LOGIN_PATHS["hospital-admin"], LOGIN_PATHS["system-admin"]):
        assert any(a.is_displayed() for a in browser.all(f'a[href="{path}"]')), path
