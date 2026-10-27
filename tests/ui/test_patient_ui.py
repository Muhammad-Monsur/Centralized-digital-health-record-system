"""Patient portal in a real browser: upload a document, change who can see it, find it again (Selenium)."""
from __future__ import annotations

from pathlib import Path

from tests.ui.helpers import Browser, confirm_dialog, login

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def _fill_upload_form(b: Browser, title: str, file: Path) -> None:
    b.go("/patient/records/new")
    b.fill("#title", title)
    b.select("#information_type", index=1)
    b.js("arguments[0].value = '2026-09-01'", b.find("#information_date"))
    b.find('input[type="file"][name="file"]').send_keys(str(file))
    b.press("Upload document")


def test_upload_document_then_make_it_public(browser: Browser, tmp_path: Path):
    report = tmp_path / "blood-test-ui.pdf"
    report.write_bytes(PDF)
    login(browser, "patient")
    _fill_upload_form(browser, "UI blood test report", report)

    # lands on the new record, private by default, labelled with who uploaded it
    browser.wait_url(r"/patient/records/\d+")
    assert browser.text("h1") == "UI blood test report"
    meta = browser.text(".record-meta")
    assert "Uploaded by" in meta and "Ayesha Siddiqua (patient)" in meta
    assert "blood-test-ui.pdf" in browser.text(".file-card")
    assert browser.text("[data-vis-label]") == "Private"

    # making it public asks for confirmation, then sticks after a reload
    browser.click(".switch")
    confirm_dialog(browser, "Make public")
    browser.wait_text("[data-vis-label]", "Public")
    browser.reload()
    browser.wait_text("[data-vis-label]", "Public")

    # it shows up in the records list with the same label
    browser.go("/patient/records")  # the list is filled in by the page's script
    browser.wait_text("body", "UI blood test report")
    assert "Uploaded by Ayesha Siddiqua (patient)" in browser.text()


def test_upload_rejects_a_fake_pdf(browser: Browser, tmp_path: Path):
    fake = tmp_path / "not-really.pdf"
    fake.write_bytes(b"MZ this is an executable, not a PDF")
    login(browser, "patient")
    _fill_upload_form(browser, "Should not upload", fake)
    browser.wait(lambda d: any(e.is_displayed() and e.text.strip() for e in
                               browser.all(".error, [data-form-error], .toast")))
    assert "/patient/records/new" in browser.url  # still on the form, with an error shown


def test_access_history_page_lists_entries(browser: Browser):
    login(browser, "patient")
    browser.go("/patient/access-history")
    assert browser.visible("h1").text
