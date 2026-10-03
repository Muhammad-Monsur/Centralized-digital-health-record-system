"""
routers/doctor.py
==================
Doctor / Healthcare Provider Portal (SRS section 3.2):
  - 3.2.3 Patient Search and Identification  -> GET  /api/doctor/patients/{upi}
  - 3.2.3 Private Record Access and Consent  -> POST /api/doctor/access-requests
  - 3.2.3 Medical Record Management          -> POST /api/doctor/prescriptions
  - 3.2.3 Emergency Access Management        -> POST /api/doctor/emergency-access

Every endpoint requires a signed-in, non-blocked DOCTOR account
(require_role("doctor")). Doctor accounts can only be created by a Hospital
Admin - see routers/hospital_admin.py.
"""

import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db, log_audit, require_role
from ..security import generate_otp, hash_otp

router = APIRouter(prefix="/api/doctor", tags=["doctor"])


def _my_doctor(db: Session, user: models.User) -> models.Doctor:
    doctor = db.query(models.Doctor).filter(models.Doctor.user_id == user.id).first()
    if not doctor:
        raise HTTPException(404, "Doctor profile not found.")
    return doctor


def _find_patient(db: Session, upi: str) -> models.Patient:
    patient = db.query(models.Patient).filter(models.Patient.upi == upi).first()
    if not patient:
        raise HTTPException(404, "No patient found with that ID.")
    return patient


def get_current_doctor(user: models.User = Depends(require_role("doctor")), db: Session = Depends(get_db)) -> models.Doctor:
    """Dependency: resolves the signed-in user straight to their Doctor row,
    so every route below just asks for `doctor: models.Doctor = Depends(get_current_doctor)`."""
    return _my_doctor(db, user)


# ---------------- patient search (SRS 3.2.3 Patient Search and Identification) ----------------
@router.get("/patients/{upi}")
def search_patient(upi: str, doctor: models.Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    patient = _find_patient(db, upi)
    user = patient.user

    # Record that this doctor viewed the patient's public info (SRS 3.1.3 Access History)
    db.add(models.AccessLog(user_id=doctor.user_id, patient_id=patient.id, access_type="viewed_public"))
    db.commit()

    public_records = [
        {"id": r.id, "information_type": r.information_type, "title": r.title, "information_date": r.information_date}
        for r in patient.records if r.visibility == "Public"
    ]
    # Is there an already-approved, not-yet-expired consent for THIS doctor + patient?
    approved = (
        db.query(models.Consent)
        .filter(
            models.Consent.patient_id == patient.id, models.Consent.doctor_id == doctor.id,
            models.Consent.status == "Approved", models.Consent.expires_at > datetime.datetime.utcnow(),
        )
        .first()
    )
    return {
        "patient_id": patient.upi, "full_name": user.full_name, "gender": user.gender,
        "date_of_birth": patient.date_of_birth, "blood_group": patient.blood_group,
        "profile_visibility": patient.profile_visibility,
        "public_records": public_records,
        "private_access_approved": bool(approved),
        "private_records": (
            [
                {"id": r.id, "information_type": r.information_type, "title": r.title, "details": r.details}
                for r in patient.records if r.visibility == "Private"
            ]
            if approved else []
        ),
    }


# ---------------- request private access + OTP (SRS 3.2.3 Private Record Access and Consent) ----------------
@router.post("/access-requests")
def request_access(data: schemas.AccessRequestIn, user: models.User = Depends(require_role("doctor")), db: Session = Depends(get_db)):
    doctor = _my_doctor(db, user)
    patient = _find_patient(db, data.patient_upi)

    req = models.AccessRequest(patient_id=patient.id, doctor_id=doctor.id, purpose=data.purpose)
    db.add(req)
    db.flush()

    consent = models.Consent(request_id=req.id, patient_id=patient.id, doctor_id=doctor.id, status="Pending")
    db.add(consent)
    db.flush()

    otp_code = generate_otp()
    otp = models.OTPVerification(
        consent_id=consent.id, otp_hash=hash_otp(otp_code),
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=10),
    )
    db.add(otp)
    db.commit()

    log_audit(db, user.id, "Doctor requested private record access", "access_request", req.id, patient.upi)
    return {
        "ok": True, "request_id": req.id,
        # DEMO ONLY: normally this OTP would be sent to the patient by SMS, not
        # returned here. No SMS provider is configured yet (see README).
        "demo_otp_for_patient": otp_code,
    }


# ---------------- prescriptions / medical records (SRS 3.2.3 Medical Record Management) ----------------
@router.post("/prescriptions")
def add_prescription(data: schemas.PrescriptionIn, user: models.User = Depends(require_role("doctor")), db: Session = Depends(get_db)):
    doctor = _my_doctor(db, user)
    patient = _find_patient(db, data.patient_upi)

    details = f"Diagnosis: {data.diagnosis}\nMedicine: {data.medicine}\nDosage: {data.dosage}\nDuration: {data.duration}"
    record = models.MedicalInformation(
        patient_id=patient.id, doctor_id=doctor.id, hospital_id=doctor.hospital_id,
        information_type="prescription", title=f"Prescription - {data.diagnosis}"[:150],
        details=details, visibility="Private",
    )
    db.add(record)
    db.commit()
    log_audit(db, user.id, "Doctor added a prescription", "medical_information", record.id, patient.upi)
    return {"ok": True, "id": record.id}


# ---------------- emergency access (SRS 3.2.3 Emergency Access Management) ----------------
@router.post("/emergency-access")
def emergency_access(data: schemas.EmergencyAccessIn, user: models.User = Depends(require_role("doctor")), db: Session = Depends(get_db)):
    if not data.reason.strip():
        raise HTTPException(400, "A justification is required for emergency access.")
    doctor = _my_doctor(db, user)
    patient = _find_patient(db, data.patient_upi)

    record = models.EmergencyAccess(patient_id=patient.id, doctor_id=doctor.id, hospital_id=doctor.hospital_id, reason=data.reason)
    db.add(record)
    db.add(models.AccessLog(user_id=user.id, patient_id=patient.id, access_type="emergency"))
    db.commit()

    log_audit(db, user.id, "EMERGENCY access override used", "emergency_access", record.id, f"{patient.upi}: {data.reason[:100]}")
    private_records = [
        {"id": r.id, "information_type": r.information_type, "title": r.title, "details": r.details}
        for r in patient.records
    ]
    return {"ok": True, "records": private_records}


# ---------------- doctor's own activity log (SRS 3.1.3 Access History, applied to the doctor's actions) ----------------
@router.get("/activity-log")
def my_activity_log(doctor: models.Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    logs = (
        db.query(models.AccessLog)
        .filter(models.AccessLog.user_id == doctor.user_id)
        .order_by(models.AccessLog.accessed_at.desc())
        .limit(100)
        .all()
    )
    out = []
    for log in logs:
        patient = db.query(models.Patient).filter(models.Patient.id == log.patient_id).first()
        out.append({"patient_id": patient.upi if patient else "—", "access_type": log.access_type, "accessed_at": log.accessed_at})
    return out
