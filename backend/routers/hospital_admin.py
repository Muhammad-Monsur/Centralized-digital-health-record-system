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
import datetime
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

    doctor = models.Doctor(user_id=doctor_user.id, hospital_id=admin.hospital_id, specialization=data.specialization , department_id=data.department_id)
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
            "department_id": d.department_id, "department_name": d.department.name if d.department else "Unassigned",
        }
        for d in doctors
    ]

@router.post("/doctors/{doctor_id}/role")
def assign_role(
    doctor_id: int, data: schemas.RoleAssignIn,
    admin: models.HospitalAdminProfile = Depends(get_current_admin),
    user: models.User = Depends(require_role("hospital_admin")),
    db: Session = Depends(get_db),
):
   
    doctor = db.query(models.Doctor).filter(models.Doctor.id == doctor_id, models.Doctor.hospital_id == admin.hospital_id).first()
    if not doctor:
        raise HTTPException(404, "Doctor not found at your hospital.")
    role = db.query(models.Role).filter(models.Role.id == data.role_id).first()
    if not role:
        raise HTTPException(404, "Role not found.")
    existing = db.query(models.UserRole).filter(models.UserRole.user_id == doctor.user_id, models.UserRole.role_id == role.id).first()
    if not existing:
        db.add(models.UserRole(user_id=doctor.user_id, role_id=role.id))
        db.commit()
    log_audit(db, user.id, f"Assigned role '{role.name}' to doctor", "doctor", doctor.id, doctor.user.email)
    return {"ok": True}


# add role , hospital details 



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
    
    depts = db.query(models.Department).filter(models.Department.hospital_id == admin.hospital_id).all()
    return [
        {
            "id": d.id, "department": d.name, "doctors": len(d.doctors),
            "nurses": d.nurse_count, "staff": d.staff_count,
        }
        for d in depts
    ]

# create dept 



@router.patch("/departments/{department_id}")
def update_department(
    department_id: int, data: schemas.DepartmentIn, admin: models.HospitalAdminProfile = Depends(get_current_admin),
    user: models.User = Depends(require_role("hospital_admin")), db: Session = Depends(get_db),
):
    dept = db.query(models.Department).filter(models.Department.id == department_id, models.Department.hospital_id == admin.hospital_id).first()
    if not dept:
        raise HTTPException(404, "Department not found at your hospital.")
    dept.name = data.name.strip() or dept.name
    dept.nurse_count = data.nurse_count
    dept.staff_count = data.staff_count
    db.commit()
    log_audit(db, user.id, "Hospital Admin updated a department", "department", dept.id, dept.name)
    return {"ok": True}




# Patient admissions 

@router.get("/admissions")
def admissions(admin: models.HospitalAdminProfile = Depends(get_current_admin), db: Session = Depends(get_db)):
    rows = db.query(models.Admission).filter(models.Admission.hospital_id == admin.hospital_id).order_by(models.Admission.admitted_on.desc()).all()
    return [
        {
            "id": a.id, "patient_id": a.patient.upi, "name": a.patient.user.full_name, "ward": a.ward,
            "admitted_on": a.admitted_on, "discharged_on": a.discharged_on, "status": a.status,
        }
        for a in rows
    ]


@router.post("/admissions")
def admit_patient(
    data: schemas.AdmissionIn, admin: models.HospitalAdminProfile = Depends(get_current_admin),
    user: models.User = Depends(require_role("hospital_admin")), db: Session = Depends(get_db),
):
    patient = db.query(models.Patient).filter(models.Patient.upi == data.patient_upi).first()
    if not patient:
        raise HTTPException(404, "No patient found with that ID.")
    admission = models.Admission(patient_id=patient.id, hospital_id=admin.hospital_id, ward=data.ward)
    db.add(admission)
    db.commit()
    log_audit(db, user.id, "Hospital Admin admitted a patient", "admission", admission.id, f"{patient.upi} -> {data.ward}")
    return {"ok": True, "id": admission.id}


@router.patch("/admissions/{admission_id}/discharge")
def discharge_patient(
    admission_id: int, admin: models.HospitalAdminProfile = Depends(get_current_admin),
    user: models.User = Depends(require_role("hospital_admin")), db: Session = Depends(get_db),
):
    admission = db.query(models.Admission).filter(models.Admission.id == admission_id, models.Admission.hospital_id == admin.hospital_id).first()
    if not admission:
        raise HTTPException(404, "Admission record not found at your hospital.")
    admission.status = "Discharged"
    admission.discharged_on = datetime.datetime.utcnow()
    db.commit()
    log_audit(db, user.id, "Hospital Admin discharged a patient", "admission", admission.id)
    return {"ok": True}



# System Monitoring (audit log) 

@router.get("/audit-log")
def audit_log(admin: models.HospitalAdminProfile = Depends(get_current_admin), db: Session = Depends(get_db)):
    logs = db.query(models.AuditLog).order_by(models.AuditLog.timestamp.desc()).limit(50).all()
    out = []
    for log in logs:
        actor = db.query(models.User).filter(models.User.id == log.user_id).first() if log.user_id else None
        out.append({"timestamp": log.timestamp, "user": actor.full_name if actor else "System", "action": log.action, "details": log.details})
    return out
