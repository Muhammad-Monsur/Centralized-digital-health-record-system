"""Public pages in a real browser: landing page, hero animation, theme, FAQ, mobile layout, API docs."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect


def test_landing_page_sections_in_order(page: Page):
    page.goto("/")
    expect(page.get_by_role("heading", level=1)).to_have_text("Access Your Medical Reports Anytime From Anywhere")
    order = page.evaluate("[...document.querySelectorAll('main > section')].map(s => s.id || s.getAttribute('aria-labelledby'))")
    assert order == ["hero-h", "benefits", "history", "get-started", "faq", "news-h", "about"], order
    expect(page.locator("#about")).to_contain_text("Team CDHRS")


def test_hero_cycle_plays_jumps_and_pauses(page: Page):
    page.goto("/")
    count = page.locator("[data-cy-count]")
    title = page.locator(".cy-scene.is-active .cy-title")
    expect(count).to_have_text("1")
    expect(title).to_have_text("Save your documents")

    # advances by itself every 3 seconds
    expect(count).to_have_text("2", timeout=5_000)
    expect(title).to_have_text("Make it public or private")

    # a step button jumps straight to that step
    page.locator('.cy-node-btn[data-step="4"]').click()
    expect(count).to_have_text("5")
    expect(title).to_have_text("Accept or revoke any time")
    expect(page.locator('.cy-node-btn[data-step="4"]')).to_have_attribute("aria-current", "step")
    # only the visible scene is exposed to screen readers
    assert page.locator(".cy-scene:not([aria-hidden])").count() == 1

    # pause stops it
    pause = page.locator("[data-cy-pause]")
    pause.click()
    expect(pause).to_have_attribute("aria-pressed", "true")
    expect(pause).to_have_attribute("aria-label", "Play the animation")
    frozen = count.text_content()
    page.wait_for_timeout(4_000)
    expect(count).to_have_text(frozen)

    # play resumes
    pause.click()
    expect(count).not_to_have_text(frozen, timeout=5_000)


def test_hero_cycle_does_not_autoplay_with_reduced_motion(new_page):
    page = new_page(reduced_motion="reduce")
    page.goto("/")
    page.wait_for_timeout(4_000)
    expect(page.locator("[data-cy-count]")).to_have_text("1")
    expect(page.locator("[data-cy-pause]")).to_have_attribute("aria-label", "Play the animation")
    page.locator('.cy-node-btn[data-step="2"]').click()  # still usable by hand
    expect(page.locator("[data-cy-count]")).to_have_text("3")


def test_mobile_layout_has_no_sideways_scroll(new_page):
    page = new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page.goto("/")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    expect(page.locator(".cy-ring")).to_be_hidden()          # ring becomes a row of steps
    expect(page.locator('.cy-node-btn[data-step="5"]')).to_be_visible()
    for sid in ("benefits", "history", "get-started", "faq", "about"):
        page.locator(f"#{sid}").scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth") <= 390, sid


def test_dark_theme_toggle_is_remembered(page: Page):
    page.goto("/")
    html = page.locator("html")
    start = html.get_attribute("data-theme")
    page.locator("[data-theme-toggle]").first.click()
    flipped = "dark" if start == "light" else "light"
    expect(html).to_have_attribute("data-theme", flipped)
    page.reload()
    expect(html).to_have_attribute("data-theme", flipped)


def test_faq_accordion_opens_and_closes(page: Page):
    page.goto("/")
    trigger = page.locator(".accordion-trigger").first
    trigger.scroll_into_view_if_needed()
    panel = page.locator("#" + trigger.get_attribute("aria-controls"))
    expect(trigger).to_have_attribute("aria-expanded", "false")
    trigger.click()
    expect(trigger).to_have_attribute("aria-expanded", "true")
    expect(panel).to_be_visible()
    trigger.click()
    expect(trigger).to_have_attribute("aria-expanded", "false")


def test_newsletter_validates_then_subscribes(page: Page):
    page.goto("/")
    form = page.locator(".newsletter-form")
    form.scroll_into_view_if_needed()
    page.fill("#nl-email", "not-an-email")
    form.get_by_role("button", name="Subscribe").click()
    expect(page.locator("#nl-email")).to_have_attribute("aria-invalid", "true")
    page.fill("#nl-email", "reader@cdhrs.example.com")
    form.get_by_role("button", name="Subscribe").click()
    expect(page.locator("#nl-email")).to_have_value("")  # form resets on success


def test_api_docs_render(page: Page):
    page.goto("/api/docs")
    page.wait_for_function("typeof SwaggerUIBundle !== 'undefined' || document.body.innerText.includes('Could not load')")
    if "Could not load" in page.inner_text("body"):
        pytest.skip("Swagger UI is loaded from cdn.jsdelivr.net; no internet here")
    expect(page.locator(".opblock").first).to_be_visible()
    assert page.locator(".opblock").count() > 40
    expect(page.get_by_text("/api/v1/auth/login")).to_be_visible()


def test_help_and_privacy_pages_load(page: Page):
    for path, heading in (("/help", re.compile("help", re.I)), ("/privacy", "Privacy notice")):
        page.goto(path)
        expect(page.get_by_role("heading", level=1)).to_have_text(heading)
