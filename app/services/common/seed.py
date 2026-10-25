"""Idempotent seeding: RBAC catalogue, system settings and (optionally) demo data.

Demo data is entirely fictional. Running the seed twice never duplicates rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Doctor,
    HealthcareStaff,
    Hospital,
    HospitalAdmin,
    MedicalInformation,
    MedicalInformationHistory,
    Patient,
    Permission,
    Role,
    RolePermission,
    SystemAdmin,
    SystemSetting,
    User,
    UserRole,
)
from app.models.enums import (
    BloodGroup,
    Gender,
    HistoryChangeType,
    HospitalStatus,
    InformationType,
    RoleName,
    UserStatus,
    VerificationStatus,
    Visibility,
)
from app.services.common.permissions import DEFAULT_ROLES, PERMISSION_DESCRIPTIONS
from app.services.common.security import generate_upi, hash_password

DEMO_PASSWORD = "Demo@12345"  # development only; documented in README

DEFAULT_SETTINGS: dict[str, tuple[str, str]] = {
    "maintenance_banner": ("", "Message shown at the top of every portal page (empty = hidden)"),
    "allow_patient_registration": ("true", "Allow new patients to register"),
    "allow_doctor_registration": ("true", "Allow new doctors to register"),
    "consent_default_hours": ("24", "Default consent duration offered to patients (hours)"),
    "emergency_access_minutes": ("60", "How long emergency access lasts (minutes)"),
}


def seed_rbac(db: Session) -> None:
    perms = {p.permission_name: p for p in db.scalars(select(Permission))}
    for name, desc in PERMISSION_DESCRIPTIONS.items():
        if name not in perms:
            perms[name] = Permission(permission_name=name, description=desc)
            db.add(perms[name])
    db.flush()

    for role_name, (desc, perm_names) in DEFAULT_ROLES.items():
        role = db.scalar(select(Role).where(Role.role_name == role_name))
        if role is None:
            role = Role(role_name=role_name, description=desc)
            db.add(role)
            db.flush()
            # Only grant defaults to a *new* role: later edits made in the RBAC editor win.
            for pn in perm_names:
                db.add(RolePermission(role_id=role.role_id, permission_id=perms[pn].permission_id))
    db.flush()


def seed_settings(db: Session) -> None:
    existing = set(db.scalars(select(SystemSetting.setting_key)))
    for key, (value, desc) in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.add(SystemSetting(setting_key=key, setting_value=value, description=desc))
    db.flush()


def _role(db: Session, name: RoleName) -> Role:
    role = db.scalar(select(Role).where(Role.role_name == name.value))
    assert role is not None, f"role {name} missing; run seed_rbac first"
    return role


def _user(db: Session, *, username: str, full_name: str, email: str, phone: str, role: RoleName, status: UserStatus = UserStatus.ACTIVE) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.username == username))
    if user is not None:
        return user, False
    user = User(username=username, full_name=full_name, email=email, phone=phone, status=status, password_hash=hash_password(DEMO_PASSWORD))
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.user_id, role_id=_role(db, role).role_id))
    db.flush()
    return user, True


def _hospital(db: Session, name: str, reg: str, address: str, phone: str) -> Hospital:
    h = db.scalar(select(Hospital).where(Hospital.registration_number == reg))
    if h is None:
        h = Hospital(name=name, registration_number=reg, address=address, phone=phone, status=HospitalStatus.ACTIVE)
        db.add(h)
        db.flush()
    return h


@dataclass
class DemoSummary:
    created: list[str]
    upis: dict[str, str]


def seed_demo(db: Session) -> DemoSummary:
    created: list[str] = []
    h1 = _hospital(db, "Lakeview General Hospital", "HOSP-DHK-1042", "12 Lake Road, Dhanmondi, Dhaka 1209", "+8802223344551")
    h2 = _hospital(db, "Riverside Medical Centre", "HOSP-CTG-2087", "45 Port Avenue, Agrabad, Chattogram 4100", "+8803167788990")

    u, new = _user(db, username="sysadmin", full_name="Farhana Kabir", email="sysadmin@cdhrs.example.com", phone="+8801700000001", role=RoleName.SYSTEM_ADMIN)
    if new:
        db.add(SystemAdmin(user_id=u.user_id)); created.append("sysadmin")

    u, new = _user(db, username="hadmin", full_name="Rafiq Chowdhury", email="hadmin@cdhrs.example.com", phone="+8801700000002", role=RoleName.HOSPITAL_ADMIN)
    if new:
        db.add(HospitalAdmin(user_id=u.user_id, hospital_id=h1.hospital_id)); created.append("hadmin")

    u, new = _user(db, username="hadmin2", full_name="Sumaiya Rahman", email="hadmin2@cdhrs.example.com", phone="+8801700000003", role=RoleName.HOSPITAL_ADMIN)
    if new:
        db.add(HospitalAdmin(user_id=u.user_id, hospital_id=h2.hospital_id)); created.append("hadmin2")

    u, new = _user(db, username="dr.hasan", full_name="Dr. Tanvir Hasan", email="dr.hasan@cdhrs.example.com", phone="+8801700000011", role=RoleName.DOCTOR)
    if new:
        db.add(Doctor(user_id=u.user_id, hospital_id=h1.hospital_id, license_number="BMDC-A-58213", specialization="Internal Medicine", designation="Consultant", verification_status=VerificationStatus.VERIFIED)); created.append("dr.hasan")

    u, new = _user(db, username="dr.akter", full_name="Dr. Nusrat Akter", email="dr.akter@cdhrs.example.com", phone="+8801700000012", role=RoleName.DOCTOR)
    if new:
        db.add(Doctor(user_id=u.user_id, hospital_id=h2.hospital_id, license_number="BMDC-A-61007", specialization="Cardiology", designation="Associate Professor", verification_status=VerificationStatus.VERIFIED)); created.append("dr.akter")

    u, new = _user(db, username="dr.pending", full_name="Dr. Imran Siddique", email="dr.pending@cdhrs.example.com", phone="+8801700000013", role=RoleName.DOCTOR, status=UserStatus.PENDING)
    if new:
        db.add(Doctor(user_id=u.user_id, hospital_id=h1.hospital_id, license_number="BMDC-A-70311", specialization="Paediatrics", designation="Medical Officer", verification_status=VerificationStatus.PENDING)); created.append("dr.pending")

    u, new = _user(db, username="staff.lab", full_name="Jannatul Ferdous", email="staff.lab@cdhrs.example.com", phone="+8801700000021", role=RoleName.STAFF)
    if new:
        db.add(HealthcareStaff(user_id=u.user_id, hospital_id=h1.hospital_id, position="Laboratory Technologist")); created.append("staff.lab")

    patients = [
        ("patient", "Ayesha Siddiqua", "patient@cdhrs.example.com", "+8801700000031", date(1994, 3, 14), Gender.FEMALE, BloodGroup.B_POS, "House 7, Road 3, Mirpur 10, Dhaka", Visibility.PUBLIC),
        ("patient2", "Karim Uddin", "patient2@cdhrs.example.com", "+8801700000032", date(1968, 11, 2), Gender.MALE, BloodGroup.O_NEG, "22 Station Road, Sylhet", Visibility.PRIVATE),
        ("patient3", "Mitu Das", "patient3@cdhrs.example.com", "+8801700000033", date(2001, 7, 25), Gender.FEMALE, BloodGroup.A_POS, "Block C, Uttara Sector 4, Dhaka", Visibility.PUBLIC),
    ]
    upis: dict[str, str] = {}
    for username, name, email, phone, dob, gender, bg, addr, vis in patients:
        u, new = _user(db, username=username, full_name=name, email=email, phone=phone, role=RoleName.PATIENT)
        if new:
            p = Patient(user_id=u.user_id, upi=_unique_upi(db), date_of_birth=dob, gender=gender, blood_group=bg, address=addr, profile_visibility=vis)
            db.add(p)
            db.flush()
            created.append(username)
        p = db.scalar(select(Patient).where(Patient.user_id == u.user_id))
        assert p is not None
        upis[username] = p.upi

    db.flush()
    _seed_records(db, upis)
    return DemoSummary(created=created, upis=upis)


def _unique_upi(db: Session) -> str:
    for _ in range(10):
        upi = generate_upi()
        if db.scalar(select(Patient.patient_id).where(Patient.upi == upi)) is None:
            return upi
    raise RuntimeError("Could not generate a unique UPI")  # practically impossible (55-bit space)


def _seed_records(db: Session, upis: dict[str, str]) -> None:
    doc = db.scalar(select(Doctor).join(User).where(User.username == "dr.hasan"))
    doc2 = db.scalar(select(Doctor).join(User).where(User.username == "dr.akter"))
    assert doc and doc2
    today = date.today()
    plan = {
        "patient": [
            (doc, InformationType.DIAGNOSIS, "Seasonal allergic rhinitis", "Recurrent sneezing and nasal congestion in spring. Prescribed antihistamine as needed. Review in 6 months.", 210, Visibility.PUBLIC),
            (doc, InformationType.LAB_REPORT, "Complete blood count", "Hb 12.6 g/dL, WBC 6.8 x10^9/L, platelets 245 x10^9/L. All within reference range.", 95, Visibility.PUBLIC),
            (doc2, InformationType.CLINICAL_NOTE, "Cardiology consultation", "Palpitations on exertion. ECG normal sinus rhythm. Advised Holter monitoring and reduced caffeine.", 40, Visibility.PRIVATE),
            (None, InformationType.VACCINATION, "COVID-19 booster", "Booster dose administered at community centre. No adverse reaction.", 300, Visibility.PUBLIC),
            (doc, InformationType.PRESCRIPTION, "Iron supplementation", "Ferrous sulfate 200 mg once daily for 3 months; take with orange juice.", 12, Visibility.PRIVATE),
        ],
        "patient2": [
            (doc2, InformationType.DIAGNOSIS, "Type 2 diabetes mellitus", "HbA1c 7.9%. Started metformin 500 mg twice daily. Diet counselling given.", 400, Visibility.PRIVATE),
            (doc2, InformationType.ALLERGY, "Penicillin allergy", "Generalised urticaria after amoxicillin in 2015. Avoid all penicillins.", 380, Visibility.PUBLIC),
            (doc, InformationType.LAB_REPORT, "Lipid profile", "Total cholesterol 228 mg/dL, LDL 151 mg/dL, HDL 38 mg/dL, TG 196 mg/dL.", 60, Visibility.PRIVATE),
        ],
        "patient3": [
            (doc, InformationType.IMAGING, "Chest X-ray (PA view)", "Clear lung fields. No cardiomegaly. No acute abnormality.", 30, Visibility.PUBLIC),
        ],
    }
    for username, rows in plan.items():
        patient = db.scalar(select(Patient).where(Patient.upi == upis[username]))
        assert patient is not None
        if db.scalar(select(MedicalInformation.information_id).where(MedicalInformation.patient_id == patient.patient_id).limit(1)):
            continue  # already seeded
        for d, itype, title, details, days_ago, vis in rows:
            author_id = d.user_id if d else patient.user_id
            info = MedicalInformation(
                patient_id=patient.patient_id,
                doctor_id=d.doctor_id if d else None,
                hospital_id=d.hospital_id if d else None,
                information_type=itype, title=title, details=details,
                information_date=today - timedelta(days=days_ago), visibility=vis,
                created_by_user_id=author_id,
            )
            db.add(info)
            db.flush()
            db.add(MedicalInformationHistory(
                information_id=info.information_id, changed_by_user_id=author_id,
                change_type=HistoryChangeType.CREATED,
                changes={"title": {"old": None, "new": title}, "visibility": {"old": None, "new": vis.value}},
            ))
    db.flush()
