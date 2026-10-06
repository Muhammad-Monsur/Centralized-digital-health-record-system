"""
Hospital and System Administration Portal :
  -  Hospital and User Management  
  -  Audit, System Monitoring      
  - overview stats              

THIS IS THE KEY BLOCKER FEATURE: 
doctors cannot self-register , so a doctor account 
must be created here before that doctor can sign in at all. 
Every Hospital Admin is tied to exactly one Hospital (their
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



# create / list / status of doctors  

@router.post("/doctors")
def create_doctor(
    data: schemas.DoctorCreateIn,
    admin: models.HospitalAdminProfile = Depends(get_current_admin),
    user: models.User = Depends(require_role("hospital_admin")),
    db: Session = Depends(get_db),
):
    
    # THE feature that unblocks doctor login. Hospital Admin fills in the doctor's details and a temporary password.
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


@router.get("/doctors")
def list_doctors(admin: models.HospitalAdminProfile = Depends(get_current_admin), db: Session = Depends(get_db)):
    doctors = db.query(models.Doctor).filter(models.Doctor.hospital_id == admin.hospital_id).all()
    return [
        {
            "id": d.id, "user_id": d.user_id, "full_name": d.user.full_name, "email": d.user.email,
            "specialization": d.specialization, "status": d.verification_status,
        }
        for d in doctors
    ]


@router.patch("/doctors/{doctor_id}/status")
def set_doctor_status(
    doctor_id: int, status: str,
    admin: models.HospitalAdminProfile = Depends(get_current_admin),
    user: models.User = Depends(require_role("hospital_admin")),
    db: Session = Depends(get_db),
):
    # Block or re-activate a doctor 
    
    if status not in ("Active", "Blocked"):
        raise HTTPException(400, "status must be 'Active' or 'Blocked'.")
    doctor = db.query(models.Doctor).filter(models.Doctor.id == doctor_id, models.Doctor.hospital_id == admin.hospital_id).first()
    if not doctor:
        raise HTTPException(404, "Doctor not found at your hospital.")

    doctor.verification_status = status
    doctor.user.status = status
    db.commit()
    log_audit(db, user.id, f"Hospital Admin set doctor status to {status}", "doctor", doctor.id, doctor.user.email)
    return {"ok": True, "status": status}


# Dashboard overview

@router.get("/overview")
def overview(admin: models.HospitalAdminProfile = Depends(get_current_admin), db: Session = Depends(get_db)):
    total_doctors = db.query(models.Doctor).filter(models.Doctor.hospital_id == admin.hospital_id).count()
    total_patients = db.query(models.Patient).count()  # patients aren't tied to one hospital yet
    return {"hospital_name": admin.hospital.name, "total_doctors": total_doctors, "total_patients": total_patients}



#  Department Management 

@router.get("/departments")
def departments(admin: models.HospitalAdminProfile = Depends(get_current_admin), db: Session = Depends(get_db)):
    doctors = db.query(models.Doctor).filter(models.Doctor.hospital_id == admin.hospital_id).all()
    counts: dict[str, int] = {}
    for d in doctors:
        key = d.specialization or "General"
        counts[key] = counts.get(key, 0) + 1
    demo_staff = {"Cardiology": (12, 8), "Medicine": (20, 12), "Orthopedics": (16, 10), "Pediatrics": (10, 8), "Radiology": (8, 6), "General": (6, 4)}
    return [
        {"department": name, "doctors": count, "nurses": demo_staff.get(name, (8, 6))[0], "staff": demo_staff.get(name, (8, 6))[1]}
        for name, count in (counts.items() if counts else [("No departments yet", 0)])
    ]


# Patient admissions 

@router.get("/admissions")
def admissions(admin: models.HospitalAdminProfile = Depends(get_current_admin)):
    
    return [
        {"patient_id": "P-000178", "name": "Tahia Raisa", "ward": "General Ward", "admitted_on": "2026-09-10", "status": "Admitted"},
        {"patient_id": "P-000182", "name": "Kamal Hossain", "ward": "ICU", "admitted_on": "2026-09-14", "status": "Admitted"},
        {"patient_id": "P-000150", "name": "Nusrat Jahan", "ward": "Maternity", "admitted_on": "2026-09-01", "status": "Discharged"},
    ]


# System Monitoring (audit log) 

@router.get("/audit-log")
def audit_log(admin: models.HospitalAdminProfile = Depends(get_current_admin), db: Session = Depends(get_db)):
    logs = db.query(models.AuditLog).order_by(models.AuditLog.timestamp.desc()).limit(50).all()
    out = []
    for log in logs:
        actor = db.query(models.User).filter(models.User.id == log.user_id).first() if log.user_id else None
        out.append({"timestamp": log.timestamp, "user": actor.full_name if actor else "System", "action": log.action, "details": log.details})
    return out
