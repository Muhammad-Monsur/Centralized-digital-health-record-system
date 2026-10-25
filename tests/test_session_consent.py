"""Consent and emergency access last only for the doctor's sign-in session.

A doctor who signs out (or whose session times out) loses access, and the next
visit needs a new consent from the patient, even if the chosen duration has not run out.
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.middleware.session import SESSION_COOKIE
from app.models import AccessRequest, Consent, EmergencyAccess, Notification, Patient, User
from app.models.enums import AccessRequestStatus, ConsentStatus
from app.services.common.kvstore import kv
from app.services.common.session import session_ref
from tests.conftest import make_client
from tests.test_doctor import _fresh, _grant_consent, _private_record

PURPOSE = {"purpose": "Medication review before follow-up visit"}


def _logout(c):
    assert c.api("POST", "/api/v1/auth/logout").status_code == 200


def _expire_session(c):
    """Simulate an idle timeout: the session disappears from the store without a sign-out."""
    sid = c.cookies.get(SESSION_COOKIE)
    assert sid
    kv.delete("sess:" + session_ref(sid))


def _patient_user_id(db, username):
    return db.scalar(select(Patient.user_id).join(User).where(User.username == username))


def test_sign_out_ends_consent_and_next_session_needs_new_consent(client, db, upis):
    upi = upis["patient2"]
    priv = _private_record(db, "patient2")
    client.login("dr.hasan")
    consent_id, pc = _grant_consent(client, "patient2", upi, hours=24)
    assert client.get(f"/doctor/patients/{upi}/records/{priv.information_id}").status_code == 200

    _logout(client)
    _fresh(db)
    c = db.get(Consent, consent_id)
    assert c.status == ConsentStatus.ENDED and c.revoked_at is not None

    # Signing in again does not bring the access back, although 24 hours have not passed.
    client.login("dr.hasan")
    assert "Type 2 diabetes" not in client.get(f"/doctor/patients/{upi}").text
    assert client.get(f"/doctor/patients/{upi}/records/{priv.information_id}").status_code == 404
    # ...and the doctor can ask again.
    assert client.api("POST", f"/api/v1/doctor/patients/{upi}/access-requests", json=PURPOSE).status_code == 201

    # The patient was told, and sees why it ended.
    note = db.scalar(select(Notification).where(Notification.user_id == _patient_user_id(db, "patient2"))
                     .order_by(Notification.notification_id.desc()))
    assert "access has ended" in note.title
    assert "Doctor signed out" in pc.get("/patient/consent").text
    _logout(client)  # also closes the new waiting request
    _fresh(db)
    assert not db.scalar(select(AccessRequest).where(AccessRequest.status == AccessRequestStatus.PENDING))


def test_consent_does_not_carry_over_to_another_session_of_same_doctor(client, db, upis):
    upi = upis["patient3"]
    priv = _private_record(db, "patient3")
    client.login("dr.akter")
    consent_id, _ = _grant_consent(client, "patient3", upi)
    other_device = make_client()
    other_device.login("dr.akter")
    assert other_device.get(f"/doctor/patients/{upi}/records/{priv.information_id}").status_code == 404
    assert client.get(f"/doctor/patients/{upi}/records/{priv.information_id}").status_code == 200
    _logout(client)
    _logout(other_device)


def test_timeout_ends_consent_without_sign_out(client, db, upis):
    upi = upis["patient2"]
    client.login("dr.hasan")
    consent_id, pc = _grant_consent(client, "patient2", upi)
    _expire_session(client)
    # The patient's page no longer lists it as active.
    html = pc.get("/patient/consent").text
    _fresh(db)
    assert db.get(Consent, consent_id).status == ConsentStatus.ENDED
    assert f'data-revoke="{consent_id}"' not in html


def test_patient_cannot_approve_after_doctor_signed_out(client, db, upis):
    upi = upis["patient2"]
    client.login("dr.hasan")
    assert client.api("POST", f"/api/v1/doctor/patients/{upi}/access-requests", json=PURPOSE).status_code == 201
    _fresh(db)
    req = db.scalar(select(AccessRequest).where(AccessRequest.status == AccessRequestStatus.PENDING)
                    .order_by(AccessRequest.request_id.desc()))
    _expire_session(client)  # timed out, so no sign-out hook ran

    pc = make_client()
    pc.login("patient2")
    r = pc.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/approve", json={"duration_hours": 6})
    assert r.status_code == 409 and "signed out" in r.json()["detail"]
    _fresh(db)
    assert db.get(AccessRequest, req.request_id).status == AccessRequestStatus.CANCELLED


def test_code_step_closes_if_doctor_signs_out_meanwhile(client, db, upis):
    upi = upis["patient3"]
    client.login("dr.akter")
    assert client.api("POST", f"/api/v1/doctor/patients/{upi}/access-requests", json=PURPOSE).status_code == 201
    pc = make_client()
    pc.login("patient3")
    req_id = int(re.search(r'data-request="(\d+)"', pc.get("/patient/consent").text).group(1))
    consent_id = pc.api("POST", f"/api/v1/patient/consent/requests/{req_id}/approve", json={"duration_hours": 1}).json()["consent_id"]
    _logout(client)
    r = pc.api("POST", f"/api/v1/patient/consent/{consent_id}/verify", json={"code": "000000"})
    assert r.status_code == 409 and "signed out" in r.json()["detail"]
    _fresh(db)
    assert db.get(Consent, consent_id).status == ConsentStatus.ENDED


def test_sign_out_ends_emergency_access(client, db, upis):
    upi = upis["patient3"]
    client.login("dr.hasan")
    r = client.api("POST", f"/api/v1/doctor/patients/{upi}/emergency",
                   json={"reason": "Unconscious in emergency department after collapse", "confirm": True})
    assert r.status_code in (200, 201), r.text
    priv = _private_record(db, "patient3")
    assert client.get(f"/doctor/patients/{upi}/records/{priv.information_id}").status_code == 200
    _logout(client)
    _fresh(db)
    em = db.scalar(select(EmergencyAccess).order_by(EmergencyAccess.emergency_access_id.desc()))
    assert em.ended_at is not None
    client.login("dr.hasan")
    assert client.get(f"/doctor/patients/{upi}/records/{priv.information_id}").status_code == 404
