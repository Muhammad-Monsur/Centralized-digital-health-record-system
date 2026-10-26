from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e.helpers import confirm_dialog, last_sms_code, login, logout

PRIVATE_TITLE = "Type 2 diabetes"  # a private record of demo patient2 (Karim Uddin)


def _request_access(doctor: Page, upi: str) -> None:
    doctor.goto(f"/doctor/patients/{upi}")
    expect(doctor.locator("body")).not_to_contain_text(PRIVATE_TITLE)
    doctor.get_by_role("button", name="Request access").click()
    doctor.fill("#purpose", "Reviewing diabetes medication before tomorrow's follow-up visit.")
    with doctor.expect_response(lambda r: r.url.endswith("/access-requests")) as sent:
        doctor.get_by_role("button", name="Send request").click()
    assert sent.value.status == 201, sent.value.text()


def _approve_with_sms_code(patient: Page) -> None:
    patient.goto("/patient/consent")
    expect(patient.locator("body")).to_contain_text("Dr. Tanvir Hasan")
    with patient.expect_response(lambda r: r.url.endswith("/approve")) as approved:
        patient.locator("[data-approve]").first.click()
    assert approved.value.ok, approved.value.text()
    otp_form = patient.locator("[data-otp-step]:visible").first
    expect(otp_form).to_be_visible()
    otp_form.locator('input[name="code"]').fill(last_sms_code())
    with patient.expect_navigation():  # after a correct code the page moves on by itself
        with patient.expect_response(lambda r: r.url.endswith("/verify")) as verified:
            otp_form.get_by_role("button", name="Confirm access").click()
    assert verified.value.ok, verified.value.text()
    patient.goto("/patient/consent")
    expect(patient.locator("[data-revoke]").first).to_be_visible()


def test_consent_with_sms_code_then_revoke(new_page, upis):
    doctor, patient = new_page(), new_page()
    login(doctor, "dr.hasan@cdhrs.example.com")
    login(patient, "patient2")

    _request_access(doctor, upis["patient2"])
    _approve_with_sms_code(patient)

    doctor.reload()
    expect(doctor.locator("body")).to_contain_text(PRIVATE_TITLE)
    expect(doctor.locator(".access-pill.consent")).to_contain_text("until you sign out")

    # the patient sees the doctor's view in their access history
    patient.goto("/patient/access-history")
    expect(patient.locator("body")).to_contain_text("Dr. Tanvir Hasan")

    # revoke: immediate
    patient.goto("/patient/consent")
    patient.locator("[data-revoke]").first.click()
    with patient.expect_navigation():  # the page refreshes itself after revoking
        with patient.expect_response(lambda r: r.url.endswith("/revoke")) as revoked:
            confirm_dialog(patient, "Revoke access")
    assert revoked.value.ok
    doctor.reload()
    expect(doctor.locator("body")).not_to_contain_text(PRIVATE_TITLE)


def test_doctor_signing_out_ends_consent(new_page, upis):
    doctor, patient = new_page(), new_page()
    login(doctor, "dr.hasan@cdhrs.example.com")
    login(patient, "patient2")
    _request_access(doctor, upis["patient2"])
    _approve_with_sms_code(patient)
    doctor.reload()
    expect(doctor.locator("body")).to_contain_text(PRIVATE_TITLE)

    logout(doctor)
    login(doctor, "dr.hasan@cdhrs.example.com")
    doctor.goto(f"/doctor/patients/{upis['patient2']}")
    expect(doctor.locator("body")).not_to_contain_text(PRIVATE_TITLE)  # a new session needs new consent

    patient.goto("/patient/consent")
    expect(patient.locator("body")).to_contain_text("Doctor signed out")


def test_patient_can_decline_a_request(new_page, upis):
    doctor, patient = new_page(), new_page()
    login(doctor, "dr.akter@cdhrs.example.com")
    login(patient, "patient3")
    doctor.goto(f"/doctor/patients/{upis['patient3']}")
    doctor.get_by_role("button", name="Request access").click()
    doctor.fill("#purpose", "Checking previous prescriptions before outpatient visit.")
    with doctor.expect_response(lambda r: r.url.endswith("/access-requests")) as sent:
        doctor.get_by_role("button", name="Send request").click()
    assert sent.value.status == 201

    patient.goto("/patient/consent")
    patient.locator("[data-reject]").first.click()
    with patient.expect_navigation():  # the page refreshes itself after declining
        with patient.expect_response(lambda r: r.url.endswith("/reject")) as declined:
            confirm_dialog(patient, "Decline request")
    assert declined.value.ok
    expect(patient.locator("[data-reject]")).to_have_count(0)


def test_emergency_access_needs_confirmation_and_is_announced(new_page, upis):
    doctor = new_page()
    login(doctor, "dr.akter@cdhrs.example.com")
    doctor.goto(f"/doctor/patients/{upis['patient3']}")
    doctor.get_by_role("button", name="Emergency access").click()
    modal = doctor.locator("#emergency-modal")
    doctor.fill("#reason", "Unconscious in the emergency department after a road accident.")
    modal.get_by_role("button", name="Open records now").click()
    expect(modal.locator(".error:not(:empty)").first).to_be_visible()  # the confirmation box is required
    modal.locator('input[name="confirm"]').check()
    modal.get_by_role("button", name="Open records now").click()
    expect(doctor.locator(".alert-emergency").first).to_be_visible()
    logout(doctor)  # also ends the emergency access
