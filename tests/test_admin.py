"""Phase 5: admin portal - two admin types, scoping, doctor accounts by hospital admins, RBAC, audit, settings, backups."""
from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog, Doctor, Hospital, MedicalInformation, Role, User
from app.models.enums import RoleName
from app.services.common.permissions import DEFAULT_ROLES
from tests.conftest import make_client

DOC = {"kind": "doctor", "full_name": "Dr. Sadia Karim", "email": "sadia.karim@example.com", "password": "Welcome#2026x",
       "designation": "Consultant", "license_number": "BMDC-A-99001", "specialization": "Neurology"}


def _uid(db, username):
    return db.scalar(select(User.user_id).where(User.username == username))


def _fresh(db):
    db.rollback()
    db.expire_all()


# ---------------------------------------------------------------- access to the portal

def test_non_admins_blocked(client):
    for user in ("patient", "dr.hasan", "staff.lab"):
        c = make_client()
        c.login(user)
        assert c.get("/admin").status_code == 403, user
        assert c.api("POST", "/api/v1/admin/users", json=DOC).status_code == 403, user


def test_admin_pages_load_for_both_admin_types(client):
    for user, paths in (("sysadmin", ["/admin", "/admin/users", "/admin/hospitals", "/admin/roles", "/admin/access", "/admin/emergency",
                                      "/admin/emergency?tab=inter", "/admin/audit", "/admin/system", "/admin/backups", "/admin/profile"]),
                        ("hadmin", ["/admin", "/admin/users", "/admin/hospitals", "/admin/access", "/admin/emergency", "/admin/audit", "/admin/profile"])):
        c = make_client()
        c.login(user)
        for p in paths:
            assert c.get(p).status_code == 200, (user, p)


def test_hospital_admin_cannot_reach_system_admin_areas(client):
    client.login("hadmin")
    for p in ("/admin/roles", "/admin/system", "/admin/backups"):
        assert client.get(p).status_code == 403, p
    assert client.api("POST", "/api/v1/admin/hospitals", json={"name": "X Hospital", "registration_number": "HX-1", "address": "Somewhere 1", "phone": "01711111111"}).status_code == 403
    assert client.api("POST", "/api/v1/admin/backups").status_code == 403


# ---------------------------------------------------------------- doctor accounts (hospital admin)

def test_hospital_admin_creates_doctor_who_can_sign_in_and_change_password(client, db):
    client.login("hadmin")
    r = client.api("POST", "/api/v1/admin/users", json={**DOC, "hospital_id": 2})  # tries another hospital
    assert r.status_code == 201, r.text
    _fresh(db)
    doc = db.scalar(select(Doctor).join(User).where(User.email == DOC["email"]))
    hadmin_hospital = db.scalar(select(Hospital).where(Hospital.registration_number == "HOSP-DHK-1042"))
    assert doc.hospital_id == hadmin_hospital.hospital_id          # forced to the admin's own hospital
    assert doc.designation == "Consultant" and doc.verification_status.value == "verified"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.doctor_created", AuditLog.entity_id == str(doc.user_id)))

    d = make_client()
    assert d.api("POST", "/api/v1/auth/login", json={"identifier": DOC["email"], "password": DOC["password"], "portal": "patient"}).status_code == 401
    # The admin chose this password, so the doctor must replace it before anything else works.
    assert d.login(DOC["email"], DOC["password"], portal="doctor").json()["redirect"] == "/account/change-password"
    assert d.get("/doctor").headers["location"] == "/account/change-password"
    assert d.get("/api/v1/patient/records").status_code == 403
    assert d.get("/account/change-password").status_code == 200
    r = d.api("POST", "/api/v1/auth/password", json={"current_password": DOC["password"], "new_password": "MyOwn#Secret77"})
    assert r.status_code == 200 and r.json()["portal"] == "/doctor"
    assert d.get("/doctor").status_code == 200
    d2 = make_client()
    assert d2.login(DOC["email"], "MyOwn#Secret77", portal="doctor").json()["redirect"] == "/doctor"


def test_doctor_creation_validation(client):
    client.login("hadmin")
    missing = {**DOC, "email": "x1@example.com", "designation": "", "license_number": ""}
    r = client.api("POST", "/api/v1/admin/users", json=missing)
    assert r.status_code == 422 and {"designation", "license_number"} <= set(r.json()["fields"])
    weak = {**DOC, "email": "x2@example.com", "license_number": "BMDC-A-99002", "password": "password"}
    assert client.api("POST", "/api/v1/admin/users", json=weak).status_code == 422
    dup_email = {**DOC, "email": "dr.hasan@cdhrs.example.com", "license_number": "BMDC-A-99003"}
    assert "email" in client.api("POST", "/api/v1/admin/users", json=dup_email).json()["fields"]
    dup_lic = {**DOC, "email": "x3@example.com", "license_number": "BMDC-A-58213"}
    assert "license_number" in client.api("POST", "/api/v1/admin/users", json=dup_lic).json()["fields"]


def test_hospital_admin_cannot_create_hospital_admins(client):
    client.login("hadmin")
    r = client.api("POST", "/api/v1/admin/users", json={**DOC, "kind": "hospital_admin", "email": "ha@example.com"})
    assert r.status_code == 403


def test_hospital_admin_scope_isolation(client, db):
    client.login("hadmin")  # Lakeview
    other_doctor = _uid(db, "dr.akter")   # Riverside
    patient = _uid(db, "patient")
    sysadmin = _uid(db, "sysadmin")
    for uid in (other_doctor, patient, sysadmin):
        assert client.get(f"/admin/users/{uid}").status_code == 404
        assert client.api("POST", f"/api/v1/admin/users/{uid}/status", json={"status": "inactive"}).status_code == 404
    listed = client.get("/admin/users").text
    assert "Dr. Nusrat Akter" not in listed and "Ayesha Siddiqua" not in listed
    assert client.get("/admin/hospitals/2").status_code == 404


def test_deactivate_doctor_signs_out_and_blocks(client, db):
    staff_id = _uid(db, "staff.lab")
    s = make_client()
    s.login("staff.lab")
    client.login("hadmin")
    assert client.api("POST", f"/api/v1/admin/users/{staff_id}/status", json={"status": "inactive"}).status_code == 200
    assert s.get("/api/v1/session/status").json()["authenticated"] is False
    r = s.api("POST", "/api/v1/auth/login", json={"identifier": "staff.lab", "password": "Demo@12345", "portal": "doctor"})
    assert r.status_code == 403
    assert client.api("POST", f"/api/v1/admin/users/{staff_id}/status", json={"status": "active"}).status_code == 200


def test_admin_cannot_deactivate_self(client, db):
    client.login("hadmin")
    assert client.api("POST", f"/api/v1/admin/users/{_uid(db, 'hadmin')}/status", json={"status": "inactive"}).status_code in (403, 404)


def test_reject_and_verify_doctor(client, db, upis):
    client.login("hadmin")
    uid = _uid(db, "dr.hasan")
    assert client.api("POST", f"/api/v1/admin/users/{uid}/verify", json={"status": "rejected", "note": "Licence expired"}).status_code == 200
    d = make_client()
    d.login("dr.hasan")
    assert d.get(f"/doctor/patients/{upis['patient']}").status_code == 403
    assert client.api("POST", f"/api/v1/admin/users/{uid}/verify", json={"status": "verified"}).status_code == 200
    assert d.get(f"/doctor/patients/{upis['patient']}").status_code == 200


def test_admin_password_reset(client, db):
    client.login("hadmin")
    uid = _uid(db, "staff.lab")
    assert client.api("POST", f"/api/v1/admin/users/{uid}/password", json={"password": "weak"}).status_code == 422
    assert client.api("POST", f"/api/v1/admin/users/{uid}/password", json={"password": "Reset#Pass2026"}).status_code == 200
    s = make_client()
    assert s.login("staff.lab", "Reset#Pass2026").json()["redirect"] == "/account/change-password"
    assert s.get("/doctor").status_code == 303  # blocked until they choose their own
    # restore the demo account for other tests
    assert client.api("POST", f"/api/v1/admin/users/{uid}/password", json={"password": "Demo@12345"}).status_code == 200
    _fresh(db)  # new transaction: otherwise the stale snapshot says False and no UPDATE is sent
    u = db.get(User, uid)
    u.must_change_password = False
    db.commit()


# ---------------------------------------------------------------- system admin

def test_system_admin_creates_hospital_and_its_admin(client, db):
    client.login("sysadmin")
    r = client.api("POST", "/api/v1/admin/hospitals", json={"name": "Northgate Clinic", "registration_number": "hosp-syl-3001", "address": "8 Hill Road, Sylhet", "phone": "01722222222"})
    assert r.status_code == 201, r.text
    _fresh(db)
    h = db.scalar(select(Hospital).where(Hospital.registration_number == "HOSP-SYL-3001"))
    r = client.api("POST", "/api/v1/admin/users", json={"kind": "hospital_admin", "full_name": "Nadia Islam", "email": "nadia@example.com",
                                                         "password": "Admin#Pass2026", "hospital_id": h.hospital_id})
    assert r.status_code == 201, r.text
    ha = make_client()
    ha.first_login("nadia@example.com", "Admin#Pass2026", portal="hospital-admin")
    assert "Northgate Clinic" in ha.get("/admin").text
    # duplicate registration number
    assert client.api("POST", "/api/v1/admin/hospitals", json={"name": "Dup", "registration_number": "HOSP-SYL-3001", "address": "Somewhere 2", "phone": "01722222222"}).status_code == 409


def test_deactivated_hospital_disables_clinicians(client, db, upis):
    client.login("sysadmin")
    h = db.scalar(select(Hospital).where(Hospital.registration_number == "HOSP-CTG-2087"))
    assert client.api("POST", f"/api/v1/admin/hospitals/{h.hospital_id}/status", json={"status": "inactive"}).status_code == 200
    d = make_client()
    d.login("dr.akter")
    assert d.get(f"/doctor/patients/{upis['patient']}").status_code == 403
    assert client.api("POST", f"/api/v1/admin/hospitals/{h.hospital_id}/status", json={"status": "active"}).status_code == 200
    assert d.get(f"/doctor/patients/{upis['patient']}").status_code == 200


def test_rbac_edit_takes_effect_immediately(client, db, upis):
    client.login("sysadmin")
    role = db.scalar(select(Role).where(Role.role_name == RoleName.DOCTOR.value))
    without_search = [p for p in DEFAULT_ROLES["doctor"][1] if p != "clinical.patient.search"]
    r = client.api("PUT", f"/api/v1/admin/roles/{role.role_id}/permissions", json={"permissions": without_search})
    assert r.status_code == 200 and r.json()["removed"] == ["clinical.patient.search"]
    d = make_client()
    d.login("dr.hasan")
    assert d.get(f"/doctor/patients/{upis['patient']}").status_code == 403
    assert client.api("POST", f"/api/v1/admin/roles/{role.role_id}/reset").status_code == 200
    assert d.get(f"/doctor/patients/{upis['patient']}").status_code == 200
    assert client.api("PUT", f"/api/v1/admin/roles/{role.role_id}/permissions", json={"permissions": ["no.such.permission"]}).status_code == 422


def test_system_admin_role_guard_rail(client, db):
    client.login("sysadmin")
    role = db.scalar(select(Role).where(Role.role_name == RoleName.SYSTEM_ADMIN.value))
    assert client.api("PUT", f"/api/v1/admin/roles/{role.role_id}/permissions", json={"permissions": []}).status_code == 422
    assert client.api("POST", f"/api/v1/admin/roles/{role.role_id}/status", json={"status": "inactive"}).status_code == 422


def test_custom_role_create(client):
    client.login("sysadmin")
    assert client.api("POST", "/api/v1/admin/roles", json={"role_name": "records_auditor", "description": "Reads audit"}).status_code == 201
    assert client.api("POST", "/api/v1/admin/roles", json={"role_name": "records_auditor"}).status_code == 409
    assert client.api("POST", "/api/v1/admin/roles", json={"role_name": "Bad Name"}).status_code == 422


# ---------------------------------------------------------------- audit

def test_audit_scoping_and_export(client, db):
    # an event at Riverside (hospital 2) that Lakeview's admin must not see
    a = make_client()
    a.login("hadmin2")
    a.api("POST", f"/api/v1/admin/users/{_uid(db, 'dr.akter')}/unlock")
    client.login("hadmin")
    page = client.get("/admin/audit?action=admin.").text
    assert "admin.user_unlocked" not in page
    s = make_client()
    s.login("sysadmin")
    assert "admin.user_unlocked" in s.get("/admin/audit?action=admin.").text
    csv_resp = s.get("/admin/audit/export.csv?action=auth.")
    assert csv_resp.status_code == 200 and csv_resp.headers["content-type"].startswith("text/csv")
    assert csv_resp.text.splitlines()[0].startswith("audit_id,timestamp_utc")
    assert "private, no-store" in csv_resp.headers["cache-control"]
    _fresh(db)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "admin.audit_exported"))


def test_csv_injection_is_neutralised(client, db):
    from app.services.common.audit import audit

    audit(db, action="contact.received", entity="=HYPERLINK(\"http://evil\")", user_id=None, ip="1.2.3.4")
    db.commit()
    client.login("sysadmin")
    body = client.get("/admin/audit/export.csv?action=contact.").text
    assert "'=HYPERLINK" in body


# ---------------------------------------------------------------- settings

def test_settings_validation_and_effect(client):
    client.login("sysadmin")
    assert client.api("PUT", "/api/v1/admin/settings", json={"values": {"emergency_access_minutes": "9999"}}).status_code == 422
    assert client.api("PUT", "/api/v1/admin/settings", json={"values": {"unknown_key": "1"}}).status_code == 422
    assert client.api("PUT", "/api/v1/admin/settings", json={"values": {"allow_patient_registration": "false", "maintenance_banner": "Maintenance tonight 10 PM"}}).status_code == 200
    anon = make_client()
    r = anon.api("POST", "/api/v1/patients/register", json={"full_name": "Blocked User", "username": "blocked1", "email": "blocked@example.com", "phone": "01812121212",
                                                            "password": "Strong#Pass99", "confirm_password": "Strong#Pass99", "date_of_birth": "1990-01-01",
                                                            "gender": "male", "accept_terms": True})
    assert r.status_code == 403
    assert "Maintenance tonight" in client.get("/admin").text
    assert client.api("PUT", "/api/v1/admin/settings", json={"values": {"allow_patient_registration": "true", "maintenance_banner": ""}}).status_code == 200


def test_health_endpoint(client):
    client.login("sysadmin")
    h = client.get("/api/v1/admin/health").json()
    assert h["db_ok"] is True and h["migration"]  # schema built by Alembic -> revision present


# ---------------------------------------------------------------- oversight

def test_admin_can_end_emergency_in_scope(client, db, upis):
    d = make_client()
    d.login("dr.hasan")  # Lakeview
    assert d.api("POST", f"/api/v1/doctor/patients/{upis['patient3']}/emergency", json={"reason": "Severe anaphylaxis on arrival, needs allergy history", "confirm": True}).status_code == 201
    from app.models import EmergencyAccess

    _fresh(db)
    em = db.scalar(select(EmergencyAccess).order_by(EmergencyAccess.emergency_access_id.desc()))
    other = make_client()
    other.login("hadmin2")  # Riverside: out of scope
    assert other.api("POST", f"/api/v1/admin/emergency/{em.emergency_access_id}/end").status_code == 404
    client.login("hadmin")
    assert "Severe anaphylaxis" in client.get("/admin/emergency").text
    assert client.api("POST", f"/api/v1/admin/emergency/{em.emergency_access_id}/end").status_code == 200
    assert "Emergency access until" not in d.get(f"/doctor/patients/{upis['patient3']}").text


# ---------------------------------------------------------------- backups (keep last: restore resets data)

def test_backup_and_restore_round_trip(client, db):
    client.login("sysadmin")
    r = client.api("POST", "/api/v1/admin/backups")
    assert r.status_code == 201, r.text
    name = r.json()["name"]
    assert name in client.get("/admin/backups").text
    _fresh(db)
    before = db.scalar(select(MedicalInformation).order_by(MedicalInformation.information_id))
    original_title = before.title
    before.title = "CHANGED AFTER BACKUP"
    db.commit()
    assert client.api("POST", f"/api/v1/admin/backups/{name}/restore", json={"confirm": "nope"}).status_code == 422
    assert client.api("POST", "/api/v1/admin/backups/../../etc/passwd/restore", json={"confirm": "RESTORE"}).status_code in (404, 422)
    r = client.api("POST", f"/api/v1/admin/backups/{name}/restore", json={"confirm": "RESTORE"})
    assert r.status_code == 200, r.text
    _fresh(db)
    assert db.get(MedicalInformation, before.information_id).title == original_title
    # everyone signed out after restore
    assert client.get("/api/v1/session/status").json()["authenticated"] is False


def test_tampered_backup_rejected(client, tmp_path):
    import io
    import tarfile

    from app.config import settings

    client.login("sysadmin")
    name = client.api("POST", "/api/v1/admin/backups").json()["name"]
    src = settings.backup_dir / name
    bad = settings.backup_dir / (name[:-7] + "-x.tar.gz")
    with tarfile.open(src, "r:gz") as t_in, tarfile.open(bad, "w:gz") as t_out:
        for m in t_in.getmembers():
            data = t_in.extractfile(m).read()
            if m.name == "data.json":
                data = data.replace(b"Seasonal", b"Tampered")
            info = tarfile.TarInfo(m.name)
            info.size = len(data)
            t_out.addfile(info, io.BytesIO(data))
    r = client.api("POST", f"/api/v1/admin/backups/{bad.name}/restore", json={"confirm": "RESTORE"})
    assert r.status_code == 422 and "integrity" in r.json()["detail"]
    bad.unlink()
