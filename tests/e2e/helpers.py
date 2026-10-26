from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from app.services.common.seed import DEMO_PASSWORD
from tests.conftest import portal_for

LOGIN_PATHS = {"patient": "/login", "doctor": "/doctor/login",
               "hospital-admin": "/hospital-admin/login", "system-admin": "/system-admin/login"}


def login(page: Page, username: str, password: str = DEMO_PASSWORD, portal: str | None = None) -> None:
    """Sign in through the real sign-in page of the account's portal."""
    portal = portal or portal_for(username)
    page.goto(LOGIN_PATHS[portal])
    page.fill("#identifier", username)
    page.fill("#password", password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_url(lambda url: not url.rstrip("/").endswith(LOGIN_PATHS[portal]), timeout=8_000)


def logout(page: Page) -> None:
    page.locator("[data-logout]").first.click()
    page.wait_for_url(re.compile(r"/[\w-]*/?login"))


def last_sms_code() -> str:
    """The 6-digit code in the last SMS the (console) SMS provider sent."""
    from app.services.common.sms.console import OUTBOX

    assert OUTBOX, "no SMS was sent"
    return re.search(r"\b(\d{6})\b", OUTBOX[-1][1]).group(1)


def confirm_dialog(page: Page, button_name: str) -> None:
    """Click the confirm button of the app's confirmation dialog."""
    dialog = page.locator("#confirm-modal")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name=button_name).click()
