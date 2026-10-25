"""Phase 4: doctor portal - UPI lookup, public vs private, consent + OTP end to end, emergency, edits, leaks."""
from __future__ import annotations

import io
import re
from datetime import date, timedelta

from sqlalchemy import select

from app.models import AccessLog, Consent, EmergencyAccess, MedicalInformation, Notification, Patient, User
from app.models.enums import Visibility
from app.services.common.sms.console import OUTBOX
from tests.conftest import make_client


def _patient(db, username):
    return db.scalar(select(Patient).join(User).where(User.username == username))


def _private_record(db, username):
    p = _patient(db, username)
    return db.scalar(select(MedicalInformation).where(MedicalInformation.patient_id == p.patient_id, MedicalInformation.visibility == Visibility.PRIVATE))


def _fresh(db):
    db.rollback()
    db.expire_all()


def _grant_consent(doctor_client, patient_username, upi, hours=1):
    """Doctor requests -> patient approves -> OTP -> active. Returns the consent id."""
    r = doctor_client.api("POST", f"/api/v1/doctor/patients/{upi}/access-requests", json={"purpose": "Medication review before follow-up visit"})
    assert r.status_code == 201, r.text
    pc = make_client()
    pc.login(patient_username)
    page = pc.get("/patient/consent").text
    req_id = int(re.search(r'data-request="(\d+)"', page).group(1))
    consent_id = pc.api("POST", f"/api/v1/patient/consent/requests/{req_id}/approve", json={"duration_hours": hours}).json()["consent_id"]
    code = re.search(r"is (\d{6})\.", OUTBOX[-1][1]).group(1)
    assert pc.api("POST", f"/api/v1/patient/consent/{consent_id}/verify", json={"code": code}).status_code == 200
    return consent_id, pc


def test_lookup_by_upi(client, upis):
    client.login("dr.hasan")
    assert client.api("POST", "/api/v1/doctor/patients/lookup", json={"upi": upis["patient2"].lower().replace("-", "")}).json()["redirect"] == f"/doctor/patients/{upis['patient2']}"
    bad = upis["patient2"][:-1] + ("A" if upis["patient2"][-1] != "A" else "B")
    assert client.api("POST", "/api/v1/doctor/patients/lookup", json={"upi": bad}).status_code == 422
    groups = client.get(f"/api/v1/search?q={upis['patient2']}").json()["groups"]
    assert groups[0]["label"] == "Patient"
    # names are NOT searchable by clinicians
    groups = client.get("/api/v1/search?q=Karim").json()["groups"]
    assert not any(g["label"] == "Patient" for g in groups)


def test_doctor_sees_only_public_without_consent(client, db, upis):
    client.login("dr.hasan")
    html = client.get(f"/doctor/patients/{upis['patient2']}").text
    assert "Penicillin allergy" in html          # public
    assert "Type 2 diabetes" not in html          # private
    assert "Demographics are private" in html     # patient2 profile is private
    priv = _private_record(db, "patient2")
    assert client.get(f"/doctor/patients/{upis['patient2']}/records/{priv.information_id}").status_code == 404
    assert client.get(f"/doctor/patients/{upis['patient2']}/records/{priv.information_id}/file").status_code == 404
    r = client.api("PATCH", f"/api/v1/doctor/patients/{upis['patient2']}/records/{priv.information_id}",
                   json={"title": "x" * 5, "details": "", "information_type": "diagnosis", "information_date": "2025-01-01"})
    assert r.status_code == 404


def test_record_id_from_other_patient_is_not_reachable_via_upi(client, db, upis):
    client.login("dr.hasan")
    other = _private_record(db, "patient")
    # public UPI of patient2 + record id of patient -> must not resolve
    assert client.get(f"/doctor/patients/{upis['patient2']}/records/{other.information_id}").status_code == 404


def test_consent_flow_end_to_end_and_immediate_revoke(client, db, upis):
    client.login("dr.hasan")
    consent_id, pc = _grant_consent(client, "patient2", upis["patient2"])
    html = client.get(f"/doctor/patients/{upis['patient2']}").text
    assert "Type 2 diabetes" in html and "Consent until" in html
    priv = _private_record(db, "patient2")
    assert client.get(f"/doctor/patients/{upis['patient2']}/records/{priv.information_id}").status_code == 200
    _fresh(db)
    log = db.scalars(select(AccessLog).where(AccessLog.consent_id == consent_id)).all()
    assert log, "views under consent must be logged with the consent id"
    # patient sees it in access history
    assert "Dr. Tanvir Hasan" in pc.get("/patient/access-history").text
    # revoke -> next request is public-only again
    assert pc.api("POST", f"/api/v1/patient/consent/{consent_id}/revoke").status_code == 200
    html = client.get(f"/doctor/patients/{upis['patient2']}").text
    assert "Type 2 diabetes" not in html
    assert client.get(f"/doctor/patients/{upis['patient2']}/records/{priv.information_id}").status_code == 404


def test_consent_expiry_takes_effect(client, db, upis):
    client.login("dr.akter")
    consent_id, _ = _grant_consent(client, "patient3", upis["patient3"])
    c = db.get(Consent, consent_id)
    c.expires_at = c.granted_at - timedelta(seconds=1)
    db.commit()
    assert "Public records only" in client.get(f"/doctor/patients/{upis['patient3']}").text


def test_duplicate_request_blocked(client, upis):
    client.login("dr.akter")
    body = {"purpose": "Reviewing records before outpatient appointment"}
    assert client.api("POST", f"/api/v1/doctor/patients/{upis['patient']}/access-requests", json=body).status_code == 201
    assert client.api("POST", f"/api/v1/doctor/patients/{upis['patient']}/access-requests", json=body).status_code == 409
    # clean up: cancel it (also exercises cancellation)
    html = client.get("/doctor/requests").text
    rid = re.search(r'data-cancel-request="(\d+)"', html).group(1)
    assert client.api("POST", f"/api/v1/doctor/access-requests/{rid}/cancel").status_code == 200
    assert client.api("POST", f"/api/v1/doctor/access-requests/{rid}/cancel").status_code == 409


def test_request_purpose_required(client, upis):
    client.login("dr.hasan")
    assert client.api("POST", f"/api/v1/doctor/patients/{upis['patient3']}/access-requests", json={"purpose": "short"}).status_code == 422


def test_emergency_access_flow(client, db, upis):
    client.login("dr.akter")
    upi = upis["patient"]
    assert client.api("POST", f"/api/v1/doctor/patients/{upi}/emergency", json={"reason": "too short", "confirm": True}).status_code == 422
    assert client.api("POST", f"/api/v1/doctor/patients/{upi}/emergency", json={"reason": "Unconscious in emergency department after collapse", "confirm": False}).status_code == 422
    sms_before = len(OUTBOX)
    r = client.api("POST", f"/api/v1/doctor/patients/{upi}/emergency", json={"reason": "Unconscious in emergency department after collapse", "confirm": True})
    assert r.status_code == 201, r.text
    html = client.get(f"/doctor/patients/{upi}").text
    assert "Emergency access until" in html and "Iron supplementation" in html  # private record visible
    _fresh(db)
    p = _patient(db, "patient")
    em = db.scalar(select(EmergencyAccess).where(EmergencyAccess.patient_id == p.patient_id).order_by(EmergencyAccess.emergency_access_id.desc()))
    assert 55 <= (em.expires_at - em.accessed_at).total_seconds() / 60 <= 61
    assert db.scalar(select(AccessLog).where(AccessLog.emergency_access_id == em.emergency_access_id))
    # patient notified in-app and by SMS; hospital admin of that hospital notified
    assert db.scalar(select(Notification).where(Notification.user_id == p.user_id, Notification.kind == "emergency"))
    assert len(OUTBOX) > sms_before and "Emergency access" in OUTBOX[-1][1]
    hadmin2 = db.scalar(select(User).where(User.username == "hadmin2"))
    assert db.scalar(select(Notification).where(Notification.user_id == hadmin2.user_id, Notification.kind == "emergency"))
    # patient sees it flagged
    pc = make_client()
    pc.login("patient")
    hist = pc.get("/patient/access-history?emergency=1").text
    assert "Emergency" in hist and "Unconscious in emergency department" in hist
    # doctor ends it -> public only again
    assert client.api("POST", f"/api/v1/doctor/emergency/{em.emergency_access_id}/end").status_code == 200
    assert "Iron supplementation" not in client.get(f"/doctor/patients/{upi}").text


def test_staff_has_public_only_and_no_consent_or_emergency(client, db, upis):
    client.login("staff.lab")
    assert client.get(f"/doctor/patients/{upis['patient2']}").status_code == 200
    assert client.api("POST", f"/api/v1/doctor/patients/{upis['patient2']}/access-requests", json={"purpose": "Lab work needs history please"}).status_code == 403
    assert client.api("POST", f"/api/v1/doctor/patients/{upis['patient2']}/emergency", json={"reason": "Lab staff should never be able to do this", "confirm": True}).status_code == 403
    # but staff can add a lab result
    r = client.api("POST", f"/api/v1/doctor/patients/{upis['patient2']}/records",
                   data={"title": "HbA1c result", "details": "HbA1c 7.2%", "information_type": "lab_report", "information_date": date.today().isoformat(), "visibility": "private"})
    assert r.status_code == 201, r.text


def test_pending_doctor_has_no_clinical_access(client, upis):
    client.login("dr.pending")
    assert "waiting for verification" in client.get("/doctor").text
    assert client.get(f"/doctor/patients/{upis['patient']}").status_code == 403
    assert client.api("POST", "/api/v1/doctor/patients/lookup", json={"upi": upis["patient"]}).status_code == 403


def test_doctor_create_and_update_record_with_history(client, db, upis):
    client.login("dr.hasan")
    upi = upis["patient3"]
    pdf = b"%PDF-1.4\n" + b"0" * 100
    r = client.api("POST", f"/api/v1/doctor/patients/{upi}/records",
                   data={"title": "Discharge summary", "details": "Stable at discharge.", "information_type": "clinical_note",
                         "information_date": date.today().isoformat(), "visibility": "public"},
                   files={"file": ("summary.pdf", io.BytesIO(pdf), "application/pdf")})
    assert r.status_code == 201, r.text
    rid = int(r.json()["redirect"].split("added=")[1])
    # Saved private (doctors can't choose visibility). Even the author needs consent now.
    amend = {"title": "Discharge summary (amended)", "details": "Stable at discharge. Review in 2 weeks.", "information_type": "clinical_note", "information_date": date.today().isoformat()}
    assert client.get(f"/doctor/patients/{upi}/records/{rid}").status_code == 404
    assert client.api("PATCH", f"/api/v1/doctor/patients/{upi}/records/{rid}", json=amend).status_code == 404
    consent_id, patient_client = _grant_consent(client, "patient3", upi)
    r = client.api("PATCH", f"/api/v1/doctor/patients/{upi}/records/{rid}", json=amend)
    assert r.status_code == 200, r.text
    page = client.get(f"/doctor/patients/{upi}/records/{rid}").text
    assert "Discharge summary (amended)" in page and "Updated" in page
    # visibility can't be changed by the clinician
    r = client.api("PATCH", f"/api/v1/doctor/patients/{upi}/records/{rid}",
                   json={"title": "x" * 5, "details": "", "information_type": "clinical_note", "information_date": date.today().isoformat(), "visibility": "private"})
    assert r.status_code == 422  # extra field forbidden
    # Clinician-created records are always private (the "public" choice above was ignored):
    # another doctor without consent can neither read nor edit it; the author still can.
    _fresh(db)
    assert db.get(MedicalInformation, rid).visibility == Visibility.PRIVATE
    other = make_client()
    other.login("dr.akter")
    assert other.get(f"/doctor/patients/{upi}/records/{rid}").status_code == 404
    r = other.api("PATCH", f"/api/v1/doctor/patients/{upi}/records/{rid}",
                  json={"title": "Tampered", "details": "", "information_type": "clinical_note", "information_date": date.today().isoformat()})
    assert r.status_code == 404
    # download is logged
    assert client.get(f"/doctor/patients/{upi}/records/{rid}/file").content == pdf
    _fresh(db)
    assert db.scalar(select(AccessLog).where(AccessLog.information_id == rid, AccessLog.access_type == "download_file"))
    # revoke -> the author is locked out of their own private record again
    assert patient_client.api("POST", f"/api/v1/patient/consent/{consent_id}/revoke").status_code == 200
    assert client.get(f"/doctor/patients/{upi}/records/{rid}").status_code == 404


def test_patient_cannot_use_doctor_api(client, upis):
    client.login("patient")
    assert client.get(f"/doctor/patients/{upis['patient2']}").status_code == 403
    assert client.api("POST", f"/api/v1/doctor/patients/{upis['patient2']}/emergency", json={"reason": "I am not a doctor at all, honestly", "confirm": True}).status_code == 403


def test_doctor_pages_load(client):
    client.login("dr.hasan")
    for path in ("/doctor", "/doctor/search", "/doctor/requests", "/doctor/emergency", "/doctor/profile", "/doctor/notifications"):
        assert client.get(path).status_code == 200, path


def test_anonymous_doctor_redirect(client):
    assert client.get("/doctor").headers["location"].startswith("/doctor/login?next=")
