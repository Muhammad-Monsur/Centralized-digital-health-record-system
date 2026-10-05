"""

1. "Patient Registration and Authentication" 
2. "Doctor Registration and Authentication" 
3. "Administrator Authentication"


"""

import re
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_current_user, get_db, log_audit
from ..security import SESSION_SECONDS, hash_password, sign_session, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# portal folder name (used in URLs) -> role stored in the users table

PORTAL_ROLE = {
    "patient": "patient",
    "doctor": "doctor",
    "hospital-admin": "hospital_admin",
    "system-admin": "system_admin",
}
ROLE_PORTAL = {v: k for k, v in PORTAL_ROLE.items()}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# very small in-memory brute-force guard: email -> [fail_count, first_fail_time]

_FAILS: dict[str, list] = {}


def user_to_schema(db: Session, user: models.User) -> schemas.UserOut:
    # Builds the UserOut response, pulling in role-specific extras
    patient_id = hospital_name = specialization = ""
    if user.role == "patient" and user.patient_profile:
        patient_id = user.patient_profile.upi
    if user.role == "doctor" and user.doctor_profile:
        specialization = user.doctor_profile.specialization
        if user.doctor_profile.hospital:
            hospital_name = user.doctor_profile.hospital.name
    if user.role == "hospital_admin" and user.hospital_admin_profile and user.hospital_admin_profile.hospital:
        hospital_name = user.hospital_admin_profile.hospital.name
    return schemas.UserOut(
        id=user.id, email=user.email, role=user.role, portal=ROLE_PORTAL[user.role],
        full_name=user.full_name, phone=user.phone, gender=user.gender, status=user.status,
        patient_id=patient_id, hospital_name=hospital_name, specialization=specialization,
    )



"""
    Patient self-registration ONLY . 
    Doctors/Admins never hit this endpoint 
"""
@router.post("/register")
def register(data: schemas.RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if not data.full_name.strip():
        raise HTTPException(400, "Please enter your full name.")
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if len(data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if data.password != data.confirm_password:
        raise HTTPException(400, "Passwords do not match.")
    if db.query(models.User).filter(models.User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")

    user = models.User(
        email=email, password_hash=hash_password(data.password), role="patient",
        full_name=data.full_name.strip(), phone=data.phone.strip(), gender=data.gender,
    )
    db.add(user)
    db.flush()  # assigns user.id without committing yet, so we can use it below

    # Unique Patient ID
    upi = f"P-{user.id:06d}"
    patient = models.Patient(user_id=user.id, upi=upi, date_of_birth=data.dob)
    db.add(patient)
    db.commit()
    db.refresh(user)

    token = sign_session(user.id)
    response.set_cookie("cdhrs_session", token, max_age=SESSION_SECONDS, httponly=True, samesite="lax", path="/")
    log_audit(db, user.id, "Patient self-registered", "user", user.id, upi)
    return {"ok": True, "redirect": "/patient/profile.html"}




