from __future__ import annotations
import os
import socket
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator

import pytest

sync_api = pytest.importorskip(
    "playwright.sync_api", reason="browser tests need: pip install playwright && python -m playwright install chromium"
)
from playwright.sync_api import Browser, BrowserContext, Page, expect  # noqa: E402,F401

expect.set_options(timeout=8_000)


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: browser tests (run with: pytest tests/e2e)")


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/e2e" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


# ---------------------------------------------------------------- live server

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(_database) -> Iterator[str]:
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
        pytest.fail("the app did not start for the browser tests")
    yield base
    server.should_exit = True
    thread.join(timeout=5)


# ---------------------------------------------------------------- browser

@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    name = os.environ.get("E2E_BROWSER", "chromium")
    with sync_api.sync_playwright() as p:
        try:
            b = getattr(p, name).launch(headless=not os.environ.get("E2E_HEADED"),
                                        slow_mo=int(os.environ.get("E2E_SLOWMO", "0")))
        except Exception as e:  # browser binary not downloaded
            pytest.skip(f"{name} is not installed: python -m playwright install {name} ({str(e).splitlines()[0]})")
        yield b
        b.close()


@pytest.fixture
def new_page(browser: Browser, live_server: str) -> Iterator[Callable[..., Page]]:
    contexts: list[BrowserContext] = []
    errors: list[str] = []

    def make(**kwargs) -> Page:
        kwargs.setdefault("viewport", {"width": 1366, "height": 860})
        ctx = browser.new_context(base_url=live_server, **kwargs)
        # Hide the cookie notice so it never covers what a test clicks.
        ctx.add_init_script("try { localStorage.setItem('cdhrs-cookie-consent', 'essential:2026-01-01') } catch (e) {}")
        contexts.append(ctx)
        page = ctx.new_page()
        page.on("pageerror", lambda exc: errors.append(f"{page.url}: {exc}"))
        return page

    yield make
    for ctx in contexts:
        ctx.close()
    assert not errors, "uncaught JavaScript errors:\n" + "\n".join(errors)


@pytest.fixture
def page(new_page) -> Page:
    return new_page()
