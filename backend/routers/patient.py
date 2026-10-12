import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db, log_audit, require_role
from ..security import generate_otp, hash_otp

router = APIRouter(prefix="/api/patient", tags=["patient"])


def _my_patient(db: Session, user: models.User) -> models.Patient:
    patient = db.query(models.Patient).filter(models.Patient.user_id == user.id).first()
    if not patient:
        raise HTTPException(404, "Patient profile not found.")
    return patient


# ---------------- profile ----------------
@router.get("/profile")
def get_profile(user: models.User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    p = _my_patient(db, user)
    return {
        "full_name": user.full_name, "email": user.email, "phone": user.phone, "gender": user.gender,
        "patient_id": p.upi, "date_of_birth": p.date_of_birth, "blood_group": p.blood_group,
        "address": p.address, "profile_visibility": p.profile_visibility,
    }


# ---------------- edit profile (SRS 3.1.3 Profile Management) ----------------
@router.patch("/profile")
def update_profile(data: schemas.ProfileUpdateIn, user: models.User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    p = _my_patient(db, user)
    if data.full_name is not None and data.full_name.strip():
        user.full_name = data.full_name.strip()
    if data.phone is not None:
        user.phone = data.phone.strip()
    if data.gender is not None:
        user.gender = data.gender
    if data.blood_group is not None:
        p.blood_group = data.blood_group.strip()
    if data.address is not None:
        p.address = data.address.strip()
    db.commit()
    log_audit(db, user.id, "Patient updated their profile", "patient", p.id)
    return {
        "full_name": user.full_name, "email": user.email, "phone": user.phone, "gender": user.gender,
        "patient_id": p.upi, "date_of_birth": p.date_of_birth, "blood_group": p.blood_group,
        "address": p.address, "profile_visibility": p.profile_visibility,
    }


# ---------------- visibility toggle (SRS 3.1.3 Data Visibility Management) ----------------
@router.patch("/visibility")
def set_visibility(data: schemas.VisibilityIn, user: models.User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    if data.profile_visibility not in ("Public", "Private"):
        raise HTTPException(400, "visibility must be 'Public' or 'Private'.")
    p = _my_patient(db, user)
    p.profile_visibility = data.profile_visibility
    db.commit()
    log_audit(db, user.id, "Changed test report visibility", "patient", p.id, data.profile_visibility)
    return {"ok": True, "profile_visibility": p.profile_visibility}


# ---------------- medical records (SRS 3.1.3 Medical Record Management) ----------------
@router.get("/records")
def list_records(user: models.User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    p = _my_patient(db, user)
    records = (
        db.query(models.MedicalInformation)
        .filter(models.MedicalInformation.patient_id == p.id)
        .order_by(models.MedicalInformation.information_date.desc())
        .all()
    )
    return [
        {
            "id": r.id, "information_type": r.information_type, "title": r.title, "details": r.details,
            "visibility": r.visibility, "information_date": r.information_date,
            "doctor_name": r.doctor.user.full_name if r.doctor else "",
        }
        for r in records
    ]


@router.post("/records")
def add_record(data: schemas.RecordCreateIn, user: models.User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    """Patient uploads their own report (SRS 3.1.7 'Upload PDFs and photos of
    paper reports'). Actual file storage (not just metadata) is planned for
    next phase - see README "Not built yet"."""
    p = _my_patient(db, user)
    record = models.MedicalInformation(
        patient_id=p.id, information_type=data.information_type, title=data.title,
        details=data.details, visibility=data.visibility,
    )
    db.add(record)
    db.commit()
    log_audit(db, user.id, "Patient added a medical record", "medical_information", record.id, data.title)
    return {"ok": True, "id": record.id}


# ---------------- consent / access requests (SRS 3.1.3 Consent Management) ----------------
@router.get("/access-requests")
def list_access_requests(user: models.User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    p = _my_patient(db, user)
    requests = (
        db.query(models.AccessRequest)
        .filter(models.AccessRequest.patient_id == p.id)
        .order_by(models.AccessRequest.requested_at.desc())
        .all()
    )
    return [
        {
            "id": r.id, "doctor_name": r.doctor.user.full_name, "purpose": r.purpose,
            "status": r.status, "requested_at": r.requested_at,
        }
        for r in requests
    ]


@router.post("/access-requests/{request_id}/decision")
def decide_access_request(
    request_id: int, data: schemas.ConsentDecisionIn,
    user: models.User = Depends(require_role("patient")), db: Session = Depends(get_db),
):
    """Patient approves or rejects a doctor's private-access request.
    Approving REQUIRES the OTP code that was generated when the Consent row
    was created (SRS 3.1.6 'OTP-Based Consent Verification')."""
    p = _my_patient(db, user)
    req = db.query(models.AccessRequest).filter(
        models.AccessRequest.id == request_id, models.AccessRequest.patient_id == p.id
    ).first()
    if not req:
        raise HTTPException(404, "Access request not found.")
    if req.status != "Pending":
        raise HTTPException(400, "This request has already been decided.")

    consent = db.query(models.Consent).filter(models.Consent.request_id == req.id).first()

    if not data.approve:
        req.status = "Rejected"
        if consent:
            consent.status = "Rejected"
        db.commit()
        log_audit(db, user.id, "Patient rejected access request", "access_request", req.id)
        return {"ok": True, "status": "Rejected"}

    # approving: verify the OTP
    if not consent or not consent.otp:
        raise HTTPException(400, "No OTP was generated for this request.")
    if consent.otp.expires_at < datetime.datetime.utcnow():
        raise HTTPException(400, "This OTP has expired. Ask the doctor to request access again.")
    if not data.otp_code or hash_otp(data.otp_code) != consent.otp.otp_hash:
        raise HTTPException(400, "Incorrect OTP code.")

    req.status = "Approved"
    consent.status = "Approved"
    consent.granted_at = datetime.datetime.utcnow()
    consent.expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=7)
    consent.otp.verified_at = datetime.datetime.utcnow()
    db.commit()
    log_audit(db, user.id, "Patient approved access request", "access_request", req.id)
    return {"ok": True, "status": "Approved"}


# ---------------- activity log (SRS 3.1.3 Access History Management) ----------------
@router.get("/activity-log")
def activity_log(user: models.User = Depends(require_role("patient")), db: Session = Depends(get_db)):
    p = _my_patient(db, user)
    logs = (
        db.query(models.AccessLog)
        .filter(models.AccessLog.patient_id == p.id)
        .order_by(models.AccessLog.accessed_at.desc())
        .limit(100)
        .all()
    )
    out = []
    for log in logs:
        actor = db.query(models.User).filter(models.User.id == log.user_id).first()
        out.append({"actor": actor.full_name if actor else "Unknown", "access_type": log.access_type, "accessed_at": log.accessed_at})
    return out
