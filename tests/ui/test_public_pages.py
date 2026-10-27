"""Public pages in a real browser: landing page, hero animation, theme, FAQ, mobile layout, API docs (Selenium)."""
from __future__ import annotations

import time

import pytest

from tests.ui.helpers import Browser


def test_landing_page_sections_in_order(browser: Browser):
    browser.go("/")
    heading = "Access Your Medical Reports Anytime From Anywhere"  # fades in on load, so wait for it
    browser.wait(lambda d: browser.find("h1").text.replace("\n", " ") == heading)
    order = browser.js("return [...document.querySelectorAll('main > section')].map(s => s.id || s.getAttribute('aria-labelledby'))")
    assert order == ["hero-h", "benefits", "history", "get-started", "faq", "news-h", "about"], order
    assert "Team CDHRS" in browser.find("#about").get_attribute("textContent")


def test_hero_cycle_plays_jumps_and_pauses(browser: Browser):
    browser.go("/")
    count, title = "[data-cy-count]", ".cy-scene.is-active .cy-title"
    browser.wait_text(count, "1")
    browser.wait_text(title, "Save your documents")

    # advances by itself every 3 seconds
    browser.wait_text(count, "2", timeout=5)
    browser.wait_text(title, "Make it public or private")

    # a step button jumps straight to that step
    browser.click('.cy-node-btn[data-step="4"]')
    browser.wait_text(count, "5")
    browser.wait_text(title, "Accept or revoke any time")
    assert browser.attr('.cy-node-btn[data-step="4"]', "aria-current") == "step"
    # only the visible scene is exposed to screen readers
    assert len(browser.all(".cy-scene:not([aria-hidden])")) == 1

    # pause stops it
    browser.click("[data-cy-pause]")
    browser.wait_attr("[data-cy-pause]", "aria-pressed", "true")
    assert browser.attr("[data-cy-pause]", "aria-label") == "Play the animation"
    frozen = browser.text(count)
    time.sleep(4)
    assert browser.text(count) == frozen

    # play resumes
    browser.click("[data-cy-pause]")
    browser.wait(lambda d: browser.text(count) != frozen, timeout=5)


def test_hero_cycle_does_not_autoplay_with_reduced_motion(new_browser):
    b = new_browser(reduced_motion=True)
    b.go("/")
    time.sleep(4)
    assert b.text("[data-cy-count]") == "1"
    assert b.attr("[data-cy-pause]", "aria-label") == "Play the animation"
    b.click('.cy-node-btn[data-step="2"]')  # still usable by hand
    b.wait_text("[data-cy-count]", "3")


def test_mobile_layout_has_no_sideways_scroll(new_browser):
    b = new_browser(mobile=True)
    b.go("/")
    assert b.js("return document.documentElement.scrollWidth") <= 390
    assert not b.find(".cy-ring").is_displayed()          # ring becomes a row of steps
    assert b.find('.cy-node-btn[data-step="5"]').is_displayed()
    for sid in ("benefits", "history", "get-started", "faq", "about"):
        b.js("arguments[0].scrollIntoView({behavior: 'instant'})", b.find(f"#{sid}"))
        assert b.js("return document.documentElement.scrollWidth") <= 390, sid


def test_dark_theme_toggle_is_remembered(browser: Browser):
    browser.go("/")
    start = browser.attr("html", "data-theme")
    browser.click("[data-theme-toggle]")
    flipped = "dark" if start == "light" else "light"
    browser.wait_attr("html", "data-theme", flipped)
    browser.reload()
    browser.wait_attr("html", "data-theme", flipped)


def test_faq_accordion_opens_and_closes(browser: Browser):
    browser.go("/")
    trigger = ".accordion-trigger"
    panel = "#" + browser.attr(trigger, "aria-controls")
    assert browser.attr(trigger, "aria-expanded") == "false"
    browser.click(trigger)
    browser.wait_attr(trigger, "aria-expanded", "true")
    browser.visible(panel)
    browser.click(trigger)
    browser.wait_attr(trigger, "aria-expanded", "false")


def test_newsletter_validates_then_subscribes(browser: Browser):
    browser.go("/")
    browser.fill("#nl-email", "not-an-email")
    browser.press("Subscribe", within=".newsletter-form")
    browser.wait_attr("#nl-email", "aria-invalid", "true")
    browser.fill("#nl-email", "reader@cdhrs.example.com")
    browser.press("Subscribe", within=".newsletter-form")
    browser.wait(lambda d: browser.find("#nl-email").get_attribute("value") == "")  # form resets on success


def test_api_docs_render(browser: Browser):
    browser.go("/api/docs")
    browser.wait(lambda d: browser.js("return typeof SwaggerUIBundle !== 'undefined'") or "Could not load" in browser.text(), timeout=15)
    if "Could not load" in browser.text():
        pytest.skip("Swagger UI is loaded from cdn.jsdelivr.net; no internet here")
    browser.visible(".opblock", timeout=15)
    assert len(browser.all(".opblock")) > 40
    assert "/api/v1/auth/login" in browser.text()


def test_help_and_privacy_pages_load(browser: Browser):
    browser.go("/help")
    assert "help" in browser.text("h1").lower()
    browser.go("/privacy")
    assert browser.text("h1") == "Privacy notice"
