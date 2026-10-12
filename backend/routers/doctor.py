import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db, log_audit, require_role
from ..mailer import send_email
from ..security import generate_otp, hash_otp

router = APIRouter(prefix="/api/doctor", tags=["doctor"])
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"


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
    return _my_doctor(db, user)


# ---------------- patient search ----------------
@router.get("/patients/{upi}")
def search_patient(upi: str, doctor: models.Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    patient = _find_patient(db, upi)
    user = patient.user

    db.add(models.AccessLog(user_id=doctor.user_id, patient_id=patient.id, access_type="viewed_public"))
    db.commit()

    public_records = [
        {"id": r.id, "information_type": r.information_type, "title": r.title, "information_date": r.information_date, "has_file": bool(r.file_path)}
        for r in patient.records if r.visibility == "Public"
    ]
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
                {"id": r.id, "information_type": r.information_type, "title": r.title, "details": r.details, "has_file": bool(r.file_path)}
                for r in patient.records if r.visibility == "Private"
            ]
            if approved else []
        ),
    }


@router.get("/records/{record_id}/file")
def get_record_file(record_id: int, doctor: models.Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    record = db.query(models.MedicalInformation).filter(models.MedicalInformation.id == record_id).first()
    if not record or not record.file_path:
        raise HTTPException(404, "No file attached to this record.")
    if record.visibility == "Private":
        approved = (
            db.query(models.Consent)
            .filter(
                models.Consent.patient_id == record.patient_id, models.Consent.doctor_id == doctor.id,
                models.Consent.status == "Approved", models.Consent.expires_at > datetime.datetime.utcnow(),
            )
            .first()
        )
        if not approved:
            raise HTTPException(403, "You do not have approved access to this private record.")
    return FileResponse(UPLOAD_DIR / record.file_path)


# ---------------- request private access + OTP ----------------
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

    sent = send_email(
        patient.user.email, "CDHRS: a doctor wants to see your private records",
        f"{user.full_name} asked to view your private records ({data.purpose}).\n"
        f"To approve, open the Consent and Privacy tab and enter this code: {otp_code}\n"
        "The code expires in 10 minutes. If you do not recognise this request, choose Reject.",
    )
    return {"ok": True, "request_id": req.id, "emailed": sent, "demo_otp_for_patient": None if sent else otp_code}


# ---------------- prescriptions / medical records ----------------
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


# ---------------- emergency access ----------------
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

# ---------------- doctor's own activity log ----------------
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
