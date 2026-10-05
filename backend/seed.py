
from sqlalchemy.orm import Session

from . import models
from .database import SessionLocal
from .security import hash_password

ROLES = [
    ("Super Admin", "Full system access"),
    ("Hospital Admin", "Hospital Management"),
    ("Doctor", "Patient Records, Lab Orders"),
    ("Nurse", "Patient View, Lab Orders"),
    ("Patient", "Patient Registration"),
]
PERMISSIONS = [
    "manage_users", "manage_hospitals", "manage_roles", "view_patient_records",
    "edit_patient_records", "request_private_access", "emergency_access", "manage_backups",
]


def run():
    db: Session = SessionLocal()
    try:
        if db.query(models.User).count() > 0:
            return  # already seeded

        role_objs = {}
        for name, desc in ROLES:
            r = models.Role(name=name, description=desc)
            db.add(r)
            db.flush()
            role_objs[name] = r
        perm_objs = {}
        for name in PERMISSIONS:
            p = models.Permission(name=name)
            db.add(p)
            db.flush()
            perm_objs[name] = p
        # a few sensible role -> permission links for the RBAC screen to display
        links = {
            "Super Admin": PERMISSIONS,
            "Hospital Admin": ["manage_users", "manage_hospitals"],
            "Doctor": ["view_patient_records", "edit_patient_records", "request_private_access", "emergency_access"],
            "Nurse": ["view_patient_records", "request_private_access"],
            "Patient": [],
        }
        for role_name, perm_names in links.items():
            for perm_name in perm_names:
                db.add(models.RolePermission(role_id=role_objs[role_name].id, permission_id=perm_objs[perm_name].id))

        # --- Hospital ---
        hospital = models.Hospital(name="Dhaka Medical Center", address="Dhaka, Bangladesh", status="Active")
        db.add(hospital)
        db.flush()

        # --- System Admin ---
        sysadmin_user = models.User(
            email="sysadmin@cdhrs.bd", password_hash=hash_password("SysAdmin@12345"),
            role="system_admin", full_name="System Admin",
        )
        db.add(sysadmin_user)
        db.flush()
        db.add(models.SystemAdminProfile(user_id=sysadmin_user.id))
        db.add(models.UserRole(user_id=sysadmin_user.id, role_id=role_objs["Super Admin"].id))

        # --- Hospital Admin ---
        admin_user = models.User(
            email="admin@cdhrs.bd", password_hash=hash_password("Admin@12345"),
            role="hospital_admin", full_name="Hospital Admin",
        )
        db.add(admin_user)
        db.flush()
        db.add(models.HospitalAdminProfile(user_id=admin_user.id, hospital_id=hospital.id))
        db.add(models.UserRole(user_id=admin_user.id, role_id=role_objs["Hospital Admin"].id))

        # --- Doctor (created by the Hospital Admin, matching the SRS rule) ---
        doctor_user = models.User(
            email="dr.farhana@cdhrs.bd", password_hash=hash_password("Doctor@12345"),
            role="doctor", full_name="Dr. Farhana Akter", gender="Female", phone="+880 1711 000003",
        )
        db.add(doctor_user)
        db.flush()
        db.add(models.Doctor(user_id=doctor_user.id, hospital_id=hospital.id, specialization="Cardiology"))
        db.add(models.UserRole(user_id=doctor_user.id, role_id=role_objs["Doctor"].id))

        # --- Patient (self-registered) ---
        patient_user = models.User(
            email="rahim@email.com", password_hash=hash_password("Patient@12345"),
            role="patient", full_name="Rahim Ahmed", gender="Male", phone="+880 1712 345678",
        )
        db.add(patient_user)
        db.flush()
        db.add(models.Patient(
            user_id=patient_user.id, upi=f"P-{patient_user.id:06d}",
            date_of_birth="2003-12-18", blood_group="B+", address="House 12, Road 5, Dhanmondi, Dhaka",
        ))
        db.add(models.UserRole(user_id=patient_user.id, role_id=role_objs["Patient"].id))

        db.commit()
        print("[seed] demo data created: sysadmin, hospital admin, doctor, patient.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
