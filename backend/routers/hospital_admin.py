"""
==========================
Hospital and System Administration Portal - the Hospital Admin's half
(SRS section 3.3):
  - 3.3.3 Hospital and User Management  -> POST  /api/hospital-admin/doctors
                                            GET   /api/hospital-admin/doctors
                                            PATCH /api/hospital-admin/doctors/{id}/status
  - 3.3.3 Audit, System Monitoring      -> GET   /api/hospital-admin/audit-log
  - 3.3.3 overview stats                -> GET   /api/hospital-admin/overview

THIS IS THE KEY BLOCKER FEATURE: doctors cannot self-register (SRS 3.2.1 /
3.4.2), so a doctor account must be created here before that doctor can sign
in at all. Every Hospital Admin is tied to exactly one Hospital (their
`hospital_id`), and can only manage doctors within that hospital.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_db, log_audit, require_role
from ..security import hash_password

router = APIRouter(prefix="/api/hospital-admin", tags=["hospital-admin"])


def get_current_admin(user: models.User = Depends(require_role("hospital_admin")), db: Session = Depends(get_db)) -> models.HospitalAdminProfile:
    admin = db.query(models.HospitalAdminProfile).filter(models.HospitalAdminProfile.user_id == user.id).first()
    if not admin:
        raise HTTPException(404, "Hospital admin profile not found.")
    return admin



# create / list / block doctors (SRS 3.3.3 Hospital and User Management) 

@router.post("/doctors")
def create_doctor(
    data: schemas.DoctorCreateIn,
    admin: models.HospitalAdminProfile = Depends(get_current_admin),
    user: models.User = Depends(require_role("hospital_admin")),
    db: Session = Depends(get_db),
):
    
    """THE feature that unblocks doctor login. Hospital Admin fills in the
    doctor's details and a temporary password; the doctor can sign in with
    those credentials right away at /doctor/login.html."""

    email = data.email.strip().lower()
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")
    if len(data.temp_password) < 8:
        raise HTTPException(400, "Temporary password must be at least 8 characters.")

    doctor_user = models.User(
        email=email, password_hash=hash_password(data.temp_password), role="doctor",
        full_name=data.full_name.strip(), phone=data.phone.strip(), gender=data.gender,
    )
    db.add(doctor_user)
    db.flush()

    doctor = models.Doctor(user_id=doctor_user.id, hospital_id=admin.hospital_id, specialization=data.specialization)
    db.add(doctor)
    db.commit()
    db.refresh(doctor)

    log_audit(db, user.id, "Hospital Admin created a doctor account", "doctor", doctor.id, doctor_user.email)
    return {"ok": True, "doctor_id": doctor.id, "email": doctor_user.email}

