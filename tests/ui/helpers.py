"""Small Selenium helpers shared by the UI tests (open pages, wait, sign in/out, SMS codes)."""
from __future__ import annotations

import re

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from app.services.common.seed import DEMO_PASSWORD
from tests.conftest import portal_for

TIMEOUT = 8
LOGIN_PATHS = {"patient": "/login", "doctor": "/doctor/login",
               "hospital-admin": "/hospital-admin/login", "system-admin": "/system-admin/login"}


class Browser:
    """One browser window bound to the test server's base URL."""

    def __init__(self, driver: WebDriver, base: str):
        self.driver, self.base = driver, base

    # navigation
    def go(self, path: str) -> None:
        self.driver.get(self.base + path)

    def reload(self) -> None:
        self.driver.refresh()

    @property
    def url(self) -> str:
        return self.driver.current_url

    def wait(self, condition, timeout: float = TIMEOUT):
        return WebDriverWait(self.driver, timeout).until(condition)

    def wait_url(self, pattern: str, timeout: float = TIMEOUT) -> None:
        self.wait(lambda d: re.search(pattern, d.current_url), timeout)

    # elements
    def find(self, css: str) -> WebElement:
        return self.wait(EC.presence_of_element_located((By.CSS_SELECTOR, css)))

    def all(self, css: str) -> list[WebElement]:
        return self.driver.find_elements(By.CSS_SELECTOR, css)

    def visible(self, css: str, timeout: float = TIMEOUT) -> WebElement:
        return self.wait(EC.visibility_of_element_located((By.CSS_SELECTOR, css)), timeout)

    def hidden(self, css: str, timeout: float = TIMEOUT) -> None:
        self.wait(EC.invisibility_of_element_located((By.CSS_SELECTOR, css)), timeout)

    def _click(self, el: WebElement) -> None:
        """Scroll the element to the middle of the window (instantly, not smoothly) and click it."""
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'})", el)
        self.wait(lambda d: el.is_displayed() and el.is_enabled())
        self.wait(lambda d: self._settled(el))  # not mid-animation (dialogs scale in, sections fade in)
        el.click()

    def _settled(self, el: WebElement) -> bool:
        return self.driver.execute_async_script("""
            const [el, done] = arguments;
            const box = () => JSON.stringify(el.getBoundingClientRect());
            const first = box();
            requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => done(
                box() === first && !el.getAnimations({subtree: false}).some(a => a.playState === 'running')
                && !(el.closest('.modal') && el.closest('.modal').getAnimations({subtree: true}).some(a => a.playState === 'running'))), 50)));
        """, el)

    def click(self, css: str) -> None:
        self._click(self.find(css))

    def button(self, name: str, within: str = "body") -> WebElement:
        """A visible button whose text is exactly ``name`` (like a user reading the label)."""
        def find(d):
            for b in d.find_elements(By.CSS_SELECTOR, f"{within} button"):
                if b.is_displayed() and b.text.strip() == name:
                    return b
            return False
        return self.wait(find)

    def press(self, name: str, within: str = "body") -> None:
        self._click(self.button(name, within))

    def fill(self, css: str, value: str) -> None:
        el = self.find(css)
        el.clear()
        el.send_keys(value)

    def select(self, css: str, value: str | None = None, index: int | None = None) -> None:
        s = Select(self.find(css))
        s.select_by_value(value) if value is not None else s.select_by_index(index)

    def text(self, css: str = "body") -> str:
        """Text as the user sees it (waits until the element is shown; some fade in)."""
        return self.visible(css).text

    def wait_text(self, css: str, text: str, timeout: float = TIMEOUT) -> None:
        self.wait(EC.text_to_be_present_in_element((By.CSS_SELECTOR, css), text), timeout)

    def wait_no_text(self, css: str, text: str, timeout: float = TIMEOUT) -> None:
        self.wait(lambda d: text not in d.find_element(By.CSS_SELECTOR, css).text, timeout)

    def attr(self, css: str, name: str) -> str | None:
        return self.find(css).get_attribute(name)

    def wait_attr(self, css: str, name: str, value: str | None, timeout: float = TIMEOUT) -> None:
        self.wait(lambda d: d.find_element(By.CSS_SELECTOR, css).get_attribute(name) == value, timeout)

    def js(self, script: str, *args):
        return self.driver.execute_script(script, *args)


def login(b: Browser, username: str, password: str = DEMO_PASSWORD, portal: str | None = None) -> None:
    """Sign in through the real sign-in page of the account's portal."""
    portal = portal or portal_for(username)
    b.go(LOGIN_PATHS[portal])
    b.fill("#identifier", username)
    b.fill("#password", password)
    b.press("Sign in")
    b.wait(lambda d: not d.current_url.split("?")[0].rstrip("/").endswith(LOGIN_PATHS[portal]))


def logout(b: Browser) -> None:
    b.click("[data-logout]")
    b.wait_url(r"/[\w-]*/?login")


def last_sms_code() -> str:
    """The 6-digit code in the last SMS the (console) SMS provider sent."""
    from app.services.common.sms.console import OUTBOX

    assert OUTBOX, "no SMS was sent"
    return re.search(r"\b(\d{6})\b", OUTBOX[-1][1]).group(1)


def confirm_dialog(b: Browser, button_name: str) -> None:
    """Click the confirm button of the app's confirmation dialog."""
    b.visible("#confirm-modal")
    b.press(button_name, within="#confirm-modal")
