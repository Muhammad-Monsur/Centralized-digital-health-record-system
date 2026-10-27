"""The consent journey across two browsers at once: a doctor and a patient (Selenium).

Doctor asks -> patient approves and types the SMS code -> doctor sees private records ->
patient revokes (or the doctor signs out) -> private records are hidden again.
"""
from __future__ import annotations

from tests.ui.helpers import Browser, confirm_dialog, last_sms_code, login, logout

PRIVATE_TITLE = "Type 2 diabetes"  # a private record of demo patient2 (Karim Uddin)


def _request_access(doctor: Browser, upi: str, purpose: str) -> None:
    doctor.go(f"/doctor/patients/{upi}")
    assert PRIVATE_TITLE not in doctor.text()
    doctor.press("Request access")
    doctor.fill("#purpose", purpose)
    doctor.press("Send request")
    doctor.wait_text("body", "Request sent")


def _approve_with_sms_code(patient: Browser) -> None:
    patient.go("/patient/consent")
    patient.wait_text("body", "Dr. Tanvir Hasan")
    patient.click("[data-approve]")
    form = patient.wait(lambda d: next((f for f in patient.all("[data-otp-step]") if f.is_displayed()), False))
    form.find_element("css selector", 'input[name="code"]').send_keys(last_sms_code())
    next(b for b in form.find_elements("css selector", "button") if b.text.strip() == "Confirm access").click()
    patient.wait_url(r"granted=1")  # after a correct code the page moves on by itself
    patient.go("/patient/consent")
    patient.visible("[data-revoke]")


def test_consent_with_sms_code_then_revoke(new_browser, upis):
    doctor, patient = new_browser(), new_browser()
    login(doctor, "dr.hasan@cdhrs.example.com")
    login(patient, "patient2")
    _request_access(doctor, upis["patient2"], "Reviewing diabetes medication before tomorrow's follow-up visit.")
    _approve_with_sms_code(patient)

    doctor.reload()
    doctor.wait_text("body", PRIVATE_TITLE)
    doctor.wait_text(".access-pill.consent", "until you sign out")

    # the patient sees the doctor's view in their access history
    patient.go("/patient/access-history")
    patient.wait_text("body", "Dr. Tanvir Hasan")

    # revoke: immediate
    patient.go("/patient/consent")
    patient.click("[data-revoke]")
    confirm_dialog(patient, "Revoke access")
    patient.wait(lambda d: not patient.all("[data-revoke]"))
    doctor.reload()
    doctor.wait_no_text("body", PRIVATE_TITLE)


def test_doctor_signing_out_ends_consent(new_browser, upis):
    doctor, patient = new_browser(), new_browser()
    login(doctor, "dr.hasan@cdhrs.example.com")
    login(patient, "patient2")
    _request_access(doctor, upis["patient2"], "Reviewing diabetes medication before tomorrow's follow-up visit.")
    _approve_with_sms_code(patient)
    doctor.reload()
    doctor.wait_text("body", PRIVATE_TITLE)

    logout(doctor)
    login(doctor, "dr.hasan@cdhrs.example.com")
    doctor.go(f"/doctor/patients/{upis['patient2']}")
    assert PRIVATE_TITLE not in doctor.text()  # a new session needs new consent

    patient.go("/patient/consent")
    patient.wait_text("body", "Doctor signed out")


def test_patient_can_decline_a_request(new_browser, upis):
    doctor, patient = new_browser(), new_browser()
    login(doctor, "dr.akter@cdhrs.example.com")
    login(patient, "patient3")
    doctor.go(f"/doctor/patients/{upis['patient3']}")
    doctor.press("Request access")
    doctor.fill("#purpose", "Checking previous prescriptions before outpatient visit.")
    doctor.press("Send request")
    doctor.wait_text("body", "Request sent")

    patient.go("/patient/consent")
    patient.click("[data-reject]")
    confirm_dialog(patient, "Decline request")
    patient.wait(lambda d: not patient.all("[data-reject]"))


def test_emergency_access_needs_confirmation_and_is_announced(new_browser, upis):
    doctor = new_browser()
    login(doctor, "dr.akter@cdhrs.example.com")
    doctor.go(f"/doctor/patients/{upis['patient3']}")
    doctor.press("Emergency access")
    doctor.visible("#emergency-modal")
    doctor.fill("#reason", "Unconscious in the emergency department after a road accident.")
    doctor.press("Open records now", within="#emergency-modal")
    doctor.wait(lambda d: any(e.is_displayed() and e.text.strip() for e in doctor.all("#emergency-modal .error")))
    doctor.click('#emergency-modal input[name="confirm"]')
    doctor.press("Open records now", within="#emergency-modal")
    doctor.visible(".alert-emergency")
    logout(doctor)  # also ends the emergency access
