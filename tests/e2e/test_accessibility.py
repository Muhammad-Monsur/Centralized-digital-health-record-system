"""Automated accessibility audit (axe-core, WCAG 2.1 A/AA) of key pages in light and dark themes.

axe-core is downloaded once from jsDelivr and cached in your temp folder; without internet
on the first run the test is skipped.
"""
from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path

import pytest

from tests.e2e.helpers import login

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


def _audit(page, axe_source: str) -> list[dict]:
    # audit the final state: no half-faded entrance animations, everything revealed
    page.add_style_tag(content="*, *::before, *::after { transition: none !important; animation-duration: 0s !important; animation-delay: 0s !important; }")
    page.evaluate("document.querySelectorAll('[data-reveal]').forEach(n => n.classList.add('is-visible'))")
    page.wait_for_timeout(300)
    page.add_script_tag(content=axe_source)
    return page.evaluate("""async () => (await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}))
        .violations.map(v => ({id: v.id, impact: v.impact, nodes: v.nodes.length, example: v.nodes[0].html.slice(0, 160)}))""")


PUBLIC = ["/", "/login", "/doctor/login", "/register", "/help", "/privacy"]
SIGNED_IN = [("patient", ["/patient", "/patient/records", "/patient/consent", "/patient/access-history"]),
             ("dr.hasan@cdhrs.example.com", ["/doctor", "/doctor/requests"]),
             ("hadmin@cdhrs.example.com", ["/admin", "/admin/users"])]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_public_pages_have_no_wcag_violations(new_page, axe_source, theme):
    page = new_page(color_scheme=theme, bypass_csp=True)
    problems = {}
    for path in PUBLIC:
        page.goto(path)
        if path == "/":
            page.locator("[data-cy-pause]").click()  # a still frame, not mid-transition
        found = _audit(page, axe_source)
        if found:
            problems[path] = found
    assert not problems, problems


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_portal_pages_have_no_wcag_violations(new_page, axe_source, theme):
    problems = {}
    for user, paths in SIGNED_IN:
        page = new_page(color_scheme=theme, bypass_csp=True)
        login(page, user)
        for path in paths:
            page.goto(path)
            found = _audit(page, axe_source)
            if found:
                problems[f"{user} {path}"] = found
    assert not problems, problems
