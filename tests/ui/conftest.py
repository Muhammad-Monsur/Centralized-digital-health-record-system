"""Browser (UI) system tests with Selenium WebDriver: a real browser drives the real app.

"""
from __future__ import annotations

import os
import socket
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator

import pytest

webdriver = pytest.importorskip("selenium.webdriver", reason="UI tests need: pip install selenium")
from selenium.common.exceptions import WebDriverException  # noqa: E402
from selenium.webdriver.chrome.service import Service  # noqa: E402

from tests.ui.helpers import Browser  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "ui: Selenium browser tests (run with: pytest tests/ui)")


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/ui" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.ui)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def ui_server(_database) -> Iterator[str]:
    import uvicorn

    from app.main import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=1) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("the app did not start for the UI tests")
    yield base
    server.should_exit = True
    thread.join(timeout=5)


def _chrome(width: int, height: int) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    if not os.environ.get("UI_HEADED"):
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(f"--window-size={width},{height}")
    opts.set_capability("goog:loggingPrefs", {"browser": "SEVERE"})
    if os.environ.get("CHROME_BINARY"):
        opts.binary_location = os.environ["CHROME_BINARY"]
    service = Service(os.environ["CHROMEDRIVER"]) if os.environ.get("CHROMEDRIVER") else Service()
    return webdriver.Chrome(service=service, options=opts)


@pytest.fixture
def new_browser(ui_server: str) -> Iterator[Callable[..., Browser]]:
    """Factory: ``new_browser(dark=True, reduced_motion=True, mobile=True)``.

    Each call opens a separate browser (own cookies), so one test can act as a doctor and
    a patient at the same time. Uncaught JavaScript errors fail the test.
    """
    opened: list[Browser] = []

    def make(width: int = 1366, height: int = 860, dark: bool = False, reduced_motion: bool = False,
             mobile: bool = False) -> Browser:
        if mobile:
            width, height = 390, 844
        try:
            driver = _chrome(width, height)
        except WebDriverException as e:
            pytest.skip(f"Chrome / ChromeDriver not available: {str(e).splitlines()[0]}")
        features = [{"name": "prefers-color-scheme", "value": "dark" if dark else "light"},
                    {"name": "prefers-reduced-motion", "value": "reduce" if reduced_motion else "no-preference"}]
        driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"features": features})
        if mobile:
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride",
                                   {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True})
            driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {"enabled": True})
        # Hide the cookie notice so it never covers what a test clicks.
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source":
                               "try { localStorage.setItem('cdhrs-cookie-consent', 'essential:2026-01-01') } catch (e) {}"})
        b = Browser(driver, ui_server)
        opened.append(b)
        return b

    yield make
    errors = []
    for b in opened:
        errors += [f"{e['message']}" for e in b.driver.get_log("browser") if "Uncaught" in e["message"]]
        b.driver.quit()
    assert not errors, "uncaught JavaScript errors:\n" + "\n".join(errors)


@pytest.fixture
def browser(new_browser) -> Browser:
    return new_browser()
