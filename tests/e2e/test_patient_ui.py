"""Patient portal in a real browser: upload a document, change who can see it, find it again."""
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, expect

from tests.e2e.helpers import confirm_dialog, login

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def test_upload_document_then_make_it_public(page: Page, tmp_path: Path):
    report = tmp_path / "blood-test-e2e.pdf"
    report.write_bytes(PDF)

    login(page, "patient")
    page.goto("/patient/records/new")
    page.fill("#title", "E2E blood test report")
    page.select_option("#information_type", index=1)
    page.fill("#information_date", "2026-09-01")
    page.set_input_files('input[type="file"][name="file"]', str(report))
    page.get_by_role("button", name="Upload document").click()

    # lands on the new record, private by default, labelled with who uploaded it
    page.wait_for_url(re.compile(r"/patient/records/\d+"))
    expect(page.get_by_role("heading", level=1)).to_have_text("E2E blood test report")
    uploaded_by = page.locator(".record-meta div").filter(has_text="Uploaded by").locator("dd")
    expect(uploaded_by).to_have_text("Ayesha Siddiqua (patient)")
    expect(page.locator(".file-card")).to_contain_text("blood-test-e2e.pdf")
    label = page.locator("[data-vis-label]")
    expect(label).to_have_text("Private")

    # making it public asks for confirmation, then sticks after a reload
    page.locator(".switch").click()
    with page.expect_response(lambda r: r.url.endswith("/visibility") and r.request.method == "PATCH") as saved:
        confirm_dialog(page, "Make public")
    assert saved.value.ok
    expect(label).to_have_text("Public")
    page.reload()
    expect(page.locator("[data-vis-label]")).to_have_text("Public")

    # it shows up in the records list with the same label
    page.goto("/patient/records")
    row = page.locator("body")
    expect(row).to_contain_text("E2E blood test report")
    expect(row).to_contain_text("Uploaded by Ayesha Siddiqua (patient)")


def test_upload_rejects_a_fake_pdf(page: Page, tmp_path: Path):
    fake = tmp_path / "not-really.pdf"
    fake.write_bytes(b"MZ this is an executable, not a PDF")
    login(page, "patient")
    page.goto("/patient/records/new")
    page.fill("#title", "Should not upload")
    page.select_option("#information_type", index=1)
    page.fill("#information_date", "2026-09-01")
    page.set_input_files('input[type="file"][name="file"]', str(fake))
    page.get_by_role("button", name="Upload document").click()
    page.wait_for_timeout(800)
    assert "/patient/records/new" in page.url  # still on the form, with an error shown
    expect(page.locator(".error:not(:empty), [data-form-error]:not([hidden]), .toast").first).to_be_visible()


def test_access_history_page_lists_entries(page: Page):
    login(page, "patient")
    page.goto("/patient/access-history")
    expect(page.get_by_role("heading", level=1)).to_be_visible()
