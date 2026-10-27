"""Automated accessibility audit (axe-core, WCAG 2.1 A/AA) of key pages in light and dark themes (Selenium).

axe-core is downloaded once from jsDelivr and cached in your temp folder; without internet
on the first run the test is skipped.
"""
from __future__ import annotations

import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

from tests.ui.helpers import login

AXE_VERSION = "4.10.2"
AXE_URL = f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
AXE_FILE = Path(tempfile.gettempdir()) / f"cdhrs-axe-{AXE_VERSION}.min.js"


@pytest.fixture(scope="module")
def axe_source() -> str:
    if not AXE_FILE.exists():
        try:
            with urllib.request.urlopen(AXE_URL, timeout=20) as r:
                AXE_FILE.write_bytes(r.read())
        except OSError as e:
            pytest.skip(f"could not download axe-core ({e})")
    return AXE_FILE.read_text(encoding="utf-8")


def _audit(b, axe_source: str) -> list[dict]:
    # audit the final state: no half-faded entrance animations, everything revealed
    b.js("""const s = document.createElement('style');
            s.textContent = '*, *::before, *::after { transition: none !important; animation-duration: 0s !important; animation-delay: 0s !important; }';
            document.head.appendChild(s);
            document.querySelectorAll('[data-reveal]').forEach(n => n.classList.add('is-visible'));""")
    time.sleep(0.3)
    b.js(axe_source)  # executed directly by WebDriver, so the page's CSP does not block it
    return b.driver.execute_async_script("""const done = arguments[arguments.length - 1];
        axe.run(document, {runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']})
          .then(r => done(r.violations.map(v => ({id: v.id, impact: v.impact, nodes: v.nodes.length, example: v.nodes[0].html.slice(0, 160)}))));""")


PUBLIC = ["/", "/login", "/doctor/login", "/register", "/help", "/privacy"]
SIGNED_IN = [("patient", ["/patient", "/patient/records", "/patient/consent", "/patient/access-history"]),
             ("dr.hasan@cdhrs.example.com", ["/doctor", "/doctor/requests"]),
             ("hadmin@cdhrs.example.com", ["/admin", "/admin/users"])]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_public_pages_have_no_wcag_violations(new_browser, axe_source, theme):
    b = new_browser(dark=theme == "dark")
    b.driver.set_script_timeout(30)
    problems = {}
    for path in PUBLIC:
        b.go(path)
        if path == "/":
            b.click("[data-cy-pause]")  # a still frame, not mid-transition
        found = _audit(b, axe_source)
        if found:
            problems[path] = found
    assert not problems, problems


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_portal_pages_have_no_wcag_violations(new_browser, axe_source, theme):
    problems = {}
    for user, paths in SIGNED_IN:
        b = new_browser(dark=theme == "dark")
        b.driver.set_script_timeout(30)
        login(b, user)
        for path in paths:
            b.go(path)
            found = _audit(b, axe_source)
            if found:
                problems[f"{user} {path}"] = found
    assert not problems, problems
