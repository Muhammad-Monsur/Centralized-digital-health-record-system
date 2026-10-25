"""Patient service: registration, profile, own records, access history, dashboard.

Every function takes the *current patient* and filters by ``patient_id`` in the
query itself, so a patient can never reach another patient's rows (no "load by
id then compare" pattern that could be forgotten).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import UploadFile
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import AccessLog, AccessRequest, Consent, Doctor, EmergencyAccess, MedicalInformation, Patient, Role, User, UserRole
from app.models.enums import (
    NotificationKind,
    AccessRequestStatus,
    AccessType,
    ConsentStatus,
    HistoryChangeType,
    RecordStatus,
    RoleName,
    UserStatus,
    Visibility,
)
from app.schemas.patient import PatientRegisterIn, ProfileUpdateIn
from app.services import records
from app.services.common import file as file_service
from app.services.common import system_settings
from app.services.common.audit import audit
from app.services.common.pagination import Page, paginate
from app.services.common.notification import notify
from app.services.common.security import generate_upi, hash_password, utcnow, verify_password


class PatientError(Exception):
    def __init__(self, message: str, status_code: int = 400, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.fields = fields or {}


# ---------------------------------------------------------------- registration

def _unique_upi(db: Session) -> str:
    for _ in range(10):
        upi = generate_upi()
        if db.scalar(select(Patient.patient_id).where(Patient.upi == upi)) is None:
            return upi
    raise PatientError("Couldn't create your patient ID. Try again.", 500)


def register(db: Session, data: PatientRegisterIn, ip: str) -> Patient:
    if not system_settings.flag(db, "allow_patient_registration"):
        raise PatientError("New patient registration is paused. Try again later.", 403)
    taken: dict[str, str] = {}
    if db.scalar(select(User.user_id).where(func.lower(User.username) == data.username)):
        taken["username"] = "That username is taken."
    if db.scalar(select(User.user_id).where(func.lower(User.email) == data.email)):
        taken["email"] = "An account with this email already exists. Try signing in."
    if taken:
        raise PatientError(next(iter(taken.values())), 409, taken)

    role = db.scalar(select(Role).where(Role.role_name == RoleName.PATIENT.value))
    if role is None:
        raise PatientError("Registration is not available right now.", 503)
    user = User(username=data.username, email=data.email, full_name=data.full_name, phone=data.phone,
                password_hash=hash_password(data.password), status=UserStatus.ACTIVE)
    db.add(user)
    try:
        db.flush()
        db.add(UserRole(user_id=user.user_id, role_id=role.role_id))
        # UPI: random + unique index. A collision (astronomically unlikely) retries on IntegrityError.
        for attempt in range(3):
            patient = Patient(user_id=user.user_id, upi=_unique_upi(db), date_of_birth=data.date_of_birth, gender=data.gender,
                              blood_group=data.blood_group, address=data.address, profile_visibility=Visibility.PRIVATE)
            db.add(patient)
            try:
                with db.begin_nested():
                    db.flush()
                break
            except IntegrityError:
                db.expunge(patient)
                if attempt == 2:
                    raise
        audit(db, action="patient.registered", entity="patient", entity_id=patient.patient_id, user_id=user.user_id, ip=ip)
        db.commit()
    except IntegrityError as e:  # race on username/email between check and insert
        db.rollback()
        raise PatientError("That username or email was just taken. Choose another.", 409) from e
    return patient


# ---------------------------------------------------------------- profile

def update_profile(db: Session, patient: Patient, data: ProfileUpdateIn, ip: str) -> dict[str, Any]:
    user = patient.user
    if data.email != user.email and db.scalar(select(User.user_id).where(func.lower(User.email) == data.email, User.user_id != user.user_id)):
        raise PatientError("Another account already uses this email.", 409, {"email": "Another account already uses this email."})
    contact_changed = data.phone != user.phone or data.email != user.email
    if contact_changed and not verify_password(user.password_hash, data.current_password or ""):
        msg = "Enter your current password to change your mobile number or email."
        raise PatientError(msg, 403, {"current_password": msg})
    old_phone = user.phone
    changed: dict[str, Any] = {}
    for obj, fields in ((user, ("full_name", "email", "phone")),
                        (patient, ("date_of_birth", "gender", "blood_group", "address", "profile_visibility"))):
        for f in fields:
            new = getattr(data, f)
            if getattr(obj, f) != new:
                changed[f] = True
                setattr(obj, f, new)
    if changed:
        # field names only - never the values (they are personal data)
        audit(db, action="patient.profile_updated", entity="patient", entity_id=patient.patient_id, user_id=user.user_id, ip=ip,
              details={"fields": sorted(changed)})
    if "phone" in changed and old_phone:
        # Tell the OLD number, so a hijacker can't silently redirect consent codes.
        from app.services.common.sms import get_sms_provider

        get_sms_provider().send(old_phone, "CDHRS: the mobile number on your account was changed. If this wasn't you, contact support now.")
    if contact_changed:
        notify(db, user.user_id, NotificationKind.ACCOUNT, "Your contact details changed",
               "Your mobile number or email was updated. If this wasn't you, change your password now.", "/patient/profile")
    db.commit()
    return changed


# ---------------------------------------------------------------- records

def get_own_record(db: Session, patient: Patient, information_id: int) -> MedicalInformation:
    info = records.get_record(db, information_id, patient.patient_id)
    if info is None:
        raise PatientError("Record not found.", 404)
    return info


async def upload_record(db: Session, patient: Patient, fields: dict[str, Any], upload: UploadFile | None, ip: str) -> MedicalInformation:
    stored = None
    if upload is not None and upload.filename:
        try:
            stored = await file_service.save_upload(upload)
        except file_service.FileError as e:
            raise PatientError(e.message, 422, {"file": e.message}) from e
    elif not fields["details"]:
        raise PatientError("Add a file or write some notes.", 422, {"file": "Add a file or write some notes."})
    try:
        info = records.create(
            db, patient_id=patient.patient_id, author_user_id=patient.user_id, information_type=fields["information_type"],
            title=fields["title"], details=fields["details"], information_date=fields["information_date"],
            visibility=fields["visibility"], file=stored,
        )
        audit(db, action="record.uploaded", entity="medical_information", entity_id=info.information_id, user_id=patient.user_id, ip=ip,
              details={"has_file": stored is not None})
        db.commit()
    except Exception:
        db.rollback()
        if stored:
            file_service.delete_quietly(stored.stored_name)
        raise
    return info


def set_visibility(db: Session, patient: Patient, information_id: int, visibility: Visibility, ip: str) -> MedicalInformation:
    info = get_own_record(db, patient, information_id)
    changes = records.update(db, info, patient.user_id, {"visibility": visibility})
    if changes:
        audit(db, action="record.visibility_changed", entity="medical_information", entity_id=info.information_id,
              user_id=patient.user_id, ip=ip, details={"visibility": visibility.value})
    db.commit()
    return info


def archive_own_upload(db: Session, patient: Patient, information_id: int, ip: str) -> None:
    info = get_own_record(db, patient, information_id, )
    if info.created_by_user_id != patient.user_id or info.doctor_id is not None:
        # Clinical records are part of the medical-legal record: the patient can hide them (private)
        # but not delete them.
        raise PatientError("Only documents you uploaded yourself can be deleted. You can make this record private instead.", 403)
    records.archive(db, info, patient.user_id)
    audit(db, action="record.archived", entity="medical_information", entity_id=info.information_id, user_id=patient.user_id, ip=ip)
    db.commit()


# ---------------------------------------------------------------- access history

def access_history(db: Session, patient: Patient, page: int = 1, per_page: int = 15, only_emergency: bool = False) -> Page:
    stmt = (
        select(AccessLog)
        .where(AccessLog.patient_id == patient.patient_id)
        .options(joinedload(AccessLog.user).joinedload(User.doctor).joinedload(Doctor.hospital),
                 joinedload(AccessLog.user).joinedload(User.staff))
        .order_by(AccessLog.accessed_at.desc(), AccessLog.access_log_id.desc())
    )
    if only_emergency:
        stmt = stmt.where(AccessLog.emergency_access_id.is_not(None))
    return paginate(db, stmt, page, per_page)


def record_titles(db: Session, patient: Patient, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = db.execute(select(MedicalInformation.information_id, MedicalInformation.title)
                      .where(MedicalInformation.patient_id == patient.patient_id, MedicalInformation.information_id.in_(ids)))
    return dict(rows.tuples().all())


def emergency_events(db: Session, patient: Patient, limit: int = 20) -> list[EmergencyAccess]:
    return list(db.scalars(
        select(EmergencyAccess).where(EmergencyAccess.patient_id == patient.patient_id)
        .options(joinedload(EmergencyAccess.doctor).joinedload(Doctor.user), joinedload(EmergencyAccess.hospital))
        .order_by(EmergencyAccess.accessed_at.desc()).limit(limit)
    ).unique())


# ---------------------------------------------------------------- dashboard

@dataclass
class Dashboard:
    total: int
    public: int
    private: int
    pending_requests: int
    active_consents: int
    accesses_30d: int
    emergency_30d: int
    recent_records: list[MedicalInformation]
    recent_access: list[AccessLog]


def dashboard(db: Session, patient: Patient) -> Dashboard:
    from datetime import timedelta

    from app.services.consent import expire_stale

    expire_stale(db)
    db.commit()
    since = utcnow() - timedelta(days=30)
    pid = patient.patient_id
    # One aggregate query for the record counters.
    total, public = db.execute(
        select(func.count(), func.coalesce(func.sum(case((MedicalInformation.visibility == Visibility.PUBLIC, 1), else_=0)), 0))
        .where(MedicalInformation.patient_id == pid, MedicalInformation.status == RecordStatus.ACTIVE)
    ).one()
    pending = db.scalar(select(func.count()).select_from(AccessRequest).outerjoin(Consent, Consent.request_id == AccessRequest.request_id).where(
        AccessRequest.patient_id == pid, AccessRequest.status.in_([AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED]),
        or_(Consent.consent_id.is_(None), Consent.status == ConsentStatus.PENDING_OTP))) or 0
    active = db.scalar(select(func.count()).select_from(Consent).where(
        Consent.patient_id == pid, Consent.status == ConsentStatus.ACTIVE, Consent.expires_at > utcnow())) or 0
    acc30, em30 = db.execute(
        select(func.count(), func.coalesce(func.sum(case((AccessLog.emergency_access_id.is_not(None), 1), else_=0)), 0))
        .where(AccessLog.patient_id == pid, AccessLog.accessed_at >= since, AccessLog.user_id != patient.user_id)
    ).one()
    recent = records.list_records(db, pid, page=1, per_page=5).items
    recent_access = list(db.scalars(
        select(AccessLog).where(AccessLog.patient_id == pid, AccessLog.user_id != patient.user_id)
        .options(joinedload(AccessLog.user).joinedload(User.doctor).joinedload(Doctor.hospital))
        .order_by(AccessLog.accessed_at.desc()).limit(5)
    ).unique())
    return Dashboard(total=int(total), public=int(public), private=int(total) - int(public), pending_requests=int(pending),
                     active_consents=int(active), accesses_30d=int(acc30), emergency_30d=int(em30),
                     recent_records=recent, recent_access=recent_access)


ACCESS_LABELS = {
    AccessType.VIEW_PROFILE: "Viewed your profile",
    AccessType.VIEW_PUBLIC: "Viewed public records",
    AccessType.VIEW_PRIVATE: "Viewed private records (with your consent)",
    AccessType.VIEW_EMERGENCY: "Viewed records under EMERGENCY access",
    AccessType.DOWNLOAD_FILE: "Downloaded a document",
    AccessType.CREATE_RECORD: "Added a record",
    AccessType.UPDATE_RECORD: "Updated a record",
}

HISTORY_LABELS = {
    HistoryChangeType.CREATED: "Created",
    HistoryChangeType.UPDATED: "Updated",
    HistoryChangeType.VISIBILITY_CHANGED: "Visibility changed",
    HistoryChangeType.FILE_ATTACHED: "File attached",
    HistoryChangeType.ARCHIVED: "Deleted",
}
