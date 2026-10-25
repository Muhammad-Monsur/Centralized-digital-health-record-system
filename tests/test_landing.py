"""Landing page content and the API documentation pages."""
from __future__ import annotations

import re

PUBLIC_PAGES = ["/", "/login", "/doctor/login", "/hospital-admin/login", "/system-admin/login", "/admin/login",
                "/register", "/help", "/privacy"]


def test_about_us_is_the_last_section(client):
    html = client.get("/").text
    ids = re.findall(r'<section class="[^"]*"(?: id="([^"]+)")? aria-labelledby="([^"]+)"', html)
    order = [i or label for i, label in ids]
    assert order[0] == "hero-h"
    assert order[-1] == "about", order
    assert "Team CDHRS" in html


def test_no_personal_names_or_demo_wording_on_public_pages(client):
    banned = ["Abdullah", "Monsur", "Tahia", "Nazmoon", "Ashraful", "CSE-314", "University of Asia Pacific",
              "Demo data", "demo data", "Demo accounts", "Demo@12345", "· demo"]
    for url in PUBLIC_PAGES:
        html = client.get(url).text
        for word in banned:
            assert word not in html, f"{word!r} on {url}"


def test_hero_shows_the_how_it_works_cycle(client):
    html = client.get("/").text
    hero = html[html.index('class="hero"'):html.index('id="benefits"')]
    assert "data-cycle" in hero and "hp-img" not in hero  # the cycle replaced the photo
    # six steps, each a real button, plus a pause control
    assert len(re.findall(r'class="cy-node-btn" data-step="\d"', hero)) == 6
    assert 'data-cy-pause' in hero and 'aria-label="Pause the animation"' in hero
    # one scene visible; the rest hidden from assistive tech and focus
    assert hero.count('class="cy-scene is-active"') == 1
    assert hero.count('aria-hidden="true" inert') == 5
    for title in ("Save your documents", "Make it public or private", "A doctor asks to see it",
                  "Confirm with an SMS code", "Accept or revoke any time", "Every access is on record"):
        assert title in hero


def test_about_uses_the_doctor_photo_lazily(client):
    html = client.get("/").text
    about = html[html.index('id="about"'):]
    assert 'alt="A doctor in a white coat' in about and 'loading="lazy"' in about


def test_api_docs_scripts_carry_the_csp_nonce(client):
    for url in ("/api/docs", "/api/redoc"):
        r = client.get(url)
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
        assert "'unsafe-inline'" not in script_src  # would be ignored next to a nonce anyway
        scripts = re.findall(r"<script([^>]*)>", r.text)
        assert scripts and all(f'nonce="{nonce}"' in s for s in scripts), url
    assert client.get("/api/openapi.json").json()["info"]["title"] == "CDHRS API"
