"""Phase 3: patient portal - registration, records, uploads, isolation, consent/OTP (patient side)."""
from __future__ import annotations

import io
import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import AccessRequest, Doctor, MedicalInformation, MedicalInformationHistory, OtpVerification, Patient, User
from app.models.enums import ConsentStatus
from app.services.common.security import normalize_upi
from app.services.common.sms.console import OUTBOX
from tests.conftest import make_client

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _reg(**over):
    data = {"full_name": "Test Person", "username": "tester1", "email": "tester1@example.com", "phone": "01811111111",
            "password": "Strong#Pass99", "confirm_password": "Strong#Pass99", "date_of_birth": "1990-05-05",
            "gender": "female", "blood_group": "A+", "address": "Somewhere", "accept_terms": True}
    data.update(over)
    return data


# ---------------------------------------------------------------- registration

def test_register_creates_patient_with_valid_upi(client, db):
    r = client.api("POST", "/api/v1/patients/register", json=_reg())
    assert r.status_code == 201, r.text
    p = db.scalar(select(Patient).join(User).where(User.username == "tester1"))
    assert normalize_upi(p.upi) == p.upi
    assert p.profile_visibility.value == "private"  # private by default
    assert p.user.phone == "+8801811111111"


def test_register_rejects_future_dob(client):
    future = (date.today() + timedelta(days=1)).isoformat()
    r = client.api("POST", "/api/v1/patients/register", json=_reg(username="t2", email="t2@example.com", date_of_birth=future))
    assert r.status_code == 422
    assert "future" in r.json()["fields"]["date_of_birth"]


def test_register_accepts_today_dob(client):
    r = client.api("POST", "/api/v1/patients/register", json=_reg(username="newborn", email="nb@example.com", date_of_birth=date.today().isoformat()))
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("field,value", [("password", "weakpassword"), ("phone", "12345"), ("email", "not-an-email"), ("accept_terms", False), ("username", "a b")])
def test_register_validation(client, field, value):
    data = {"username": "valid9", "email": "valid9@example.com"}
    data[field] = value
    r = client.api("POST", "/api/v1/patients/register", json=_reg(**data))
    assert r.status_code == 422
    assert field in r.json()["fields"]


def test_register_duplicate(client):
    r = client.api("POST", "/api/v1/patients/register", json=_reg(username="patient", email="other@example.com"))
    assert r.status_code == 409 and "username" in r.json()["fields"]


def test_register_rejects_extra_fields(client):
    r = client.api("POST", "/api/v1/patients/register", json=_reg(username="sneaky", email="s@example.com", status="active"))
    assert r.status_code == 422


# ---------------------------------------------------------------- portal access

def test_patient_pages_load(client):
    client.login("patient")
    for path in ("/patient", "/patient/records", "/patient/records/new", "/patient/consent", "/patient/access-history", "/patient/profile", "/patient/notifications"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"].startswith("no-store") or "no-store" in r.headers["cache-control"], path


def test_doctor_cannot_use_patient_portal(client):
    client.login("dr.hasan")
    assert client.get("/patient").status_code == 403
    assert client.get("/api/v1/patient/records").status_code == 403


def _first_record_of(db, username):
    return db.scalar(select(MedicalInformation).join(Patient).join(User).where(User.username == username).order_by(MedicalInformation.information_id))


def test_patient_cannot_read_another_patients_record(client, db):
    other = _first_record_of(db, "patient2")
    client.login("patient")
    assert client.get(f"/patient/records/{other.information_id}").status_code == 404
    assert client.get(f"/patient/records/{other.information_id}/file").status_code == 404
    r = client.api("PATCH", f"/api/v1/patient/records/{other.information_id}/visibility", json={"visibility": "public"})
    assert r.status_code == 404
    r = client.api("DELETE", f"/api/v1/patient/records/{other.information_id}")
    assert r.status_code == 404
    ids = [i["id"] for i in client.get("/api/v1/patient/records?per_page=50").json()["items"]]
    assert other.information_id not in ids


# ---------------------------------------------------------------- uploads

def _upload(client, content, name, **fields):
    data = {"title": "Lab report", "information_type": "lab_report", "information_date": date.today().isoformat(), "visibility": "private", "details": ""}
    data.update(fields)
    return client.api("POST", "/api/v1/patient/records", data=data, files={"file": (name, io.BytesIO(content), "application/octet-stream")})


def test_upload_pdf_and_download(client, db):
    client.login("patient3")
    r = _upload(client, PDF, "../../etc/passwd<script>.pdf")
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    info = db.get(MedicalInformation, rid)
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", info.file_path)   # random stored name
    assert "/" not in info.file_original_name and "<" not in info.file_original_name
    d = client.get(f"/patient/records/{rid}/file")
    assert d.status_code == 200 and d.content == PDF
    assert d.headers["cache-control"] == "private, no-store"
    assert "attachment" in d.headers["content-disposition"]
    hist = db.scalars(select(MedicalInformationHistory).where(MedicalInformationHistory.information_id == rid)).all()
    assert [h.change_type.value for h in hist] == ["created"]


def test_upload_rejects_disguised_file(client):
    client.login("patient3")
    r = _upload(client, b"MZ\x90\x00 this is an exe" + b"0" * 50, "report.pdf")
    assert r.status_code == 422 and "file" in r.json()["fields"]
    r = _upload(client, PNG, "photo.pdf")  # PNG content named .pdf
    assert r.status_code == 422
    r = _upload(client, PDF, "script.html")
    assert r.status_code == 422


def test_upload_rejects_oversize(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_mb", 1)
    client.login("patient3")
    r = _upload(client, PDF + b"0" * (1024 * 1024 + 10), "big.pdf")
    assert r.status_code == 422 and "MB" in r.json()["detail"]


def test_upload_validates_fields(client):
    client.login("patient3")
    future = (date.today() + timedelta(days=3)).isoformat()
    r = _upload(client, PDF, "a.pdf", title="", information_date=future, information_type="bogus")
    assert r.status_code == 422
    assert {"title", "information_date", "information_type"} <= set(r.json()["fields"])


def test_visibility_change_writes_history(client, db):
    client.login("patient3")
    rid = _upload(client, PNG, "scan.png", title="Knee scan").json()["id"]
    r = client.api("PATCH", f"/api/v1/patient/records/{rid}/visibility", json={"visibility": "public"})
    assert r.status_code == 200 and r.json()["visibility"] == "public"
    db.rollback(); db.expire_all()  # fresh snapshot + drop cached objects
    hist = db.scalars(select(MedicalInformationHistory).where(MedicalInformationHistory.information_id == rid).order_by(MedicalInformationHistory.history_id)).all()
    assert hist[-1].change_type.value == "visibility_changed"
    assert hist[-1].changes["visibility"] == {"old": "private", "new": "public"}
    info = db.get(MedicalInformation, rid)
    assert info.updated_by_user_id is not None
    page = client.get(f"/patient/records/{rid}")
    assert "Visibility changed" in page.text and "Last updated" in page.text


def test_patient_can_delete_only_own_uploads(client, db):
    client.login("patient")
    doctor_record = db.scalar(select(MedicalInformation).join(Patient).join(User).where(User.username == "patient", MedicalInformation.doctor_id.is_not(None)))
    r = client.api("DELETE", f"/api/v1/patient/records/{doctor_record.information_id}")
    assert r.status_code == 403
    rid = _upload(client, PDF, "mine.pdf", title="Mine").json()["id"]
    assert client.api("DELETE", f"/api/v1/patient/records/{rid}").status_code == 200
    assert client.get(f"/patient/records/{rid}").status_code == 404


def test_records_api_filters_and_pagination(client):
    client.login("patient")
    data = client.get("/api/v1/patient/records?per_page=2").json()
    assert data["per_page"] == 2 and len(data["items"]) == 2 and data["total"] >= 5
    pub = client.get("/api/v1/patient/records?visibility=public&per_page=50").json()["items"]
    assert pub and all(i["visibility"] == "public" for i in pub)
    q = client.get("/api/v1/patient/records?q=blood").json()["items"]
    assert any("blood" in i["title"].lower() for i in q)
    assert client.get("/api/v1/patient/records?per_page=500").status_code == 422


# ---------------------------------------------------------------- consent / OTP (patient side)

def _new_request(db, doctor_username="dr.hasan", patient_username="patient2"):
    from app.services import consent as cs
    from app.services.common.session import create_session, session_ref

    doctor = db.scalar(select(Doctor).join(User).where(User.username == doctor_username))
    patient = db.scalar(select(Patient).join(User).where(User.username == patient_username))
    sid, _ = create_session(doctor.user_id, "t")  # the doctor's live sign-in session
    req = cs.request_access(db, doctor=doctor, patient=patient, purpose="Follow-up for diabetes medication review", ip="t",
                            session_ref=session_ref(sid))
    db.commit()
    return req


def _last_code():
    return re.search(r"code to .* is (\d{6})", OUTBOX[-1][1]).group(1)


def test_consent_full_flow_with_otp_and_revoke(client, db):
    req = _new_request(db)
    client.login("patient2")
    assert "diabetes medication" in client.get("/patient/consent").text
    r = client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/approve", json={"duration_hours": 6})
    assert r.status_code == 200, r.text
    consent_id = r.json()["consent_id"]
    code = _last_code()
    otp = db.scalar(select(OtpVerification).where(OtpVerification.consent_id == consent_id))
    assert code not in otp.otp_hash and len(otp.otp_hash) == 64   # stored hashed
    wrong = "000000" if code != "000000" else "111111"
    assert client.api("POST", f"/api/v1/patient/consent/{consent_id}/verify", json={"code": wrong}).status_code == 400
    r = client.api("POST", f"/api/v1/patient/consent/{consent_id}/verify", json={"code": code})
    assert r.status_code == 200, r.text
    # single use
    assert client.api("POST", f"/api/v1/patient/consent/{consent_id}/verify", json={"code": code}).status_code == 409
    from app.models import Consent

    db.rollback(); db.expire_all()  # fresh snapshot + drop cached objects
    c = db.get(Consent, consent_id)
    assert c.status == ConsentStatus.ACTIVE and 5.9 < (c.expires_at - c.granted_at).total_seconds() / 3600 <= 6
    r = client.api("POST", f"/api/v1/patient/consent/{consent_id}/revoke")
    assert r.status_code == 200
    db.rollback(); db.expire_all()  # fresh snapshot + drop cached objects
    assert db.get(Consent, consent_id).status == ConsentStatus.REVOKED


def test_otp_attempt_limit_burns_code(client, db):
    req = _new_request(db, "dr.akter", "patient2")
    client.login("patient2")
    consent_id = client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/approve", json={"duration_hours": 1}).json()["consent_id"]
    code = _last_code()
    wrong = "000000" if code != "000000" else "111111"
    statuses = [client.api("POST", f"/api/v1/patient/consent/{consent_id}/verify", json={"code": wrong}).status_code for _ in range(5)]
    assert statuses[-1] == 429
    # even the right code no longer works
    assert client.api("POST", f"/api/v1/patient/consent/{consent_id}/verify", json={"code": code}).status_code == 410
    # reject to clean up
    client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/reject")


def test_otp_expiry(client, db):
    req = _new_request(db, "dr.hasan", "patient3")
    client.login("patient3")
    consent_id = client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/approve", json={"duration_hours": 1}).json()["consent_id"]
    code = _last_code()
    otp = db.scalar(select(OtpVerification).where(OtpVerification.consent_id == consent_id))
    otp.expires_at = otp.generated_at - timedelta(seconds=1)
    db.commit()
    assert client.api("POST", f"/api/v1/patient/consent/{consent_id}/verify", json={"code": code}).status_code == 410
    client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/reject")


def test_otp_resend_cooldown(client, db):
    req = _new_request(db, "dr.akter", "patient3")
    client.login("patient3")
    consent_id = client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/approve", json={"duration_hours": 1}).json()["consent_id"]
    assert client.api("POST", f"/api/v1/patient/consent/{consent_id}/resend").status_code == 429
    client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/reject")


def test_patient_cannot_act_on_others_requests(client, db):
    req = _new_request(db, "dr.hasan", "patient")
    other = make_client()
    other.login("patient3")
    assert other.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/approve", json={"duration_hours": 1}).status_code == 404
    assert other.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/reject").status_code == 404
    client.login("patient")
    assert client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/reject").status_code == 200
    db.rollback(); db.expire_all()  # fresh snapshot + drop cached objects
    assert db.get(AccessRequest, req.request_id).status.value == "rejected"


def test_invalid_duration_rejected(client, db):
    req = _new_request(db, "dr.akter", "patient")
    client.login("patient")
    assert client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/approve", json={"duration_hours": 9999}).status_code == 422
    client.api("POST", f"/api/v1/patient/consent/requests/{req.request_id}/reject")


# ---------------------------------------------------------------- search / misc

def test_search_is_scoped_to_own_records(client):
    client.login("patient2")
    groups = client.get("/api/v1/search?q=blood").json()["groups"]
    titles = [i["title"] for g in groups if g["label"] == "My records" for i in g["items"]]
    assert "Complete blood count" not in titles  # belongs to patient, not patient2
    groups = client.get("/api/v1/search?q=lipid").json()["groups"]
    assert any(i["title"] == "Lipid profile" for g in groups for i in g["items"])


def test_patient_search_cannot_find_other_patients_by_upi(client, upis):
    client.login("patient")
    groups = client.get(f"/api/v1/search?q={upis['patient2']}").json()["groups"]
    assert not any(g["label"] == "Patient" for g in groups)


def test_profile_update(client, db):
    client.login("patient3")
    p = db.scalar(select(Patient).join(User).where(User.username == "patient3"))
    body = {"full_name": "Mitu Das", "email": "patient3@cdhrs.example.com", "phone": "01700000033", "date_of_birth": p.date_of_birth.isoformat(),
            "gender": "female", "blood_group": "A+", "address": "New address", "profile_visibility": "public"}
    assert client.api("PUT", "/api/v1/patient/profile", json=body).status_code == 200
    body["date_of_birth"] = (date.today() + timedelta(days=2)).isoformat()
    assert client.api("PUT", "/api/v1/patient/profile", json=body).status_code == 422
    body["date_of_birth"] = p.date_of_birth.isoformat()
    body["email"] = "patient@cdhrs.example.com"  # someone else's
    assert client.api("PUT", "/api/v1/patient/profile", json=body).status_code == 409


def test_newsletter_and_contact(client):
    assert client.api("POST", "/api/v1/newsletter", json={"email": "News@Example.com"}).status_code == 201
    assert client.api("POST", "/api/v1/newsletter", json={"email": "news@example.com"}).status_code == 409
    assert client.api("POST", "/api/v1/newsletter", json={"email": "bad"}).status_code == 422
    r = client.api("POST", "/api/v1/contact", json={"name": "Ana", "email": "a@example.com", "subject": "Question", "message": "How do I share my UPI?"})
    assert r.status_code == 201


def test_faq_etag(client):
    r = client.get("/api/v1/faq")
    assert r.headers["cache-control"] == "public, max-age=300"
    assert client.get("/api/v1/faq", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_uploaded_by_label_shows_real_names(client, upis):
    """Every record says who uploaded it: the patient's own name or the doctor's name."""
    client.login("patient3")
    rid = _upload(client, PDF, "own.pdf", title="My own scan", visibility="public").json()["id"]
    page = client.get(f"/patient/records/{rid}").text
    assert "Uploaded by Mitu Das (patient)" in page and ">You<" not in page
    item = next(i for i in client.get("/api/v1/patient/records?q=own scan").json()["items"] if i["id"] == rid)
    assert item["author"] == "Mitu Das (patient)"
    d = make_client()
    d.login("dr.hasan")
    assert "Uploaded by Mitu Das (patient)" in d.get(f"/doctor/patients/{upis['patient3']}/records/{rid}").text
    # a doctor-written record shows the doctor's name and hospital
    client2 = make_client()
    client2.login("patient")
    assert "Uploaded by Dr. Tanvir Hasan (doctor, Lakeview General Hospital)" in client2.get("/patient/records?q=blood").text


def test_register_form_attributes_are_real_html(client):
    """Regression: the field macro escaped its extra attributes, so the browser saw
    pattern="&#34;...&#34;" and rejected every username."""
    html = client.get("/register").text
    assert 'pattern="[A-Za-z0-9][A-Za-z0-9._\\-]{2,49}"' in html
    assert 'minlength="3" maxlength="50"' in html
    assert "&#34;" not in html


def test_register_accepts_simple_usernames(client):
    body = {"full_name": "Md. Monsur", "username": "Monsur123", "email": "monsur123@cdhrs.example.com",
            "phone": "01712345699", "password": "Strong#Pass2026x", "confirm_password": "Strong#Pass2026x",
            "date_of_birth": "2001-05-04", "gender": "male", "blood_group": "B+", "accept_terms": True}
    r = client.api("POST", "/api/v1/patients/register", json=body)
    assert r.status_code in (200, 201), r.text
