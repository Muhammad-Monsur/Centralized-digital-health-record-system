"""Doctor / healthcare-staff service.

Access to a patient's data is decided here, on every request, from the database:

    emergency access (active)  -> all records, flagged EMERGENCY in logs
    consent (active, unexpired) -> all records
    otherwise                   -> PUBLIC records only (and demographics only if the
                                   patient's profile is public)

Revocation and expiry therefore take effect on the very next request.
Every view, download, create and update is written to ACCESS_LOG.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.middleware.auth import CurrentUser
from app.models import (
    AccessLog,
    AccessRequest,
    Consent,
    EmergencyAccess,
    HospitalAdmin,
    MedicalInformation,
    Patient,
    User,
)
from app.models.enums import AccessRequestStatus, AccessType, ConsentStatus, NotificationKind, RecordStatus, Visibility
from app.services import consent as consent_service
from app.services import records
from app.services.common import system_settings
from app.services.common.audit import access, audit
from app.services.common.notification import notify
from app.services.common.pagination import Page, paginate
from app.services.common.permissions import P
from app.services.common.security import local_str, normalize_upi, utcnow


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 400, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.fields = fields or {}


@dataclass
class AccessContext:
    level: str  # "public" | "consent" | "emergency"
    consent: Consent | None = None
    emergency: EmergencyAccess | None = None

    @property
    def full(self) -> bool:
        return self.level in ("consent", "emergency")

    @property
    def access_type(self) -> AccessType:
        return {"emergency": AccessType.VIEW_EMERGENCY, "consent": AccessType.VIEW_PRIVATE}.get(self.level, AccessType.VIEW_PUBLIC)

    @property
    def expires_at(self):
        if self.emergency:
            return self.emergency.expires_at
        if self.consent:
            return self.consent.expires_at
        return None

    def log_kwargs(self) -> dict[str, Any]:
        return {"consent_id": self.consent.consent_id if self.consent else None,
                "emergency_access_id": self.emergency.emergency_access_id if self.emergency else None}


def find_patient(db: Session, raw_upi: str) -> Patient:
    upi = normalize_upi(raw_upi or "")
    if upi is None:
        raise ProviderError("That isn't a valid patient ID. Check for typos; the format is CDH-XXXX-XXXX-XXXX.", 422, {"upi": "Invalid patient ID."})
    patient = db.scalar(select(Patient).where(Patient.upi == upi).options(joinedload(Patient.user)))
    if patient is None:
        raise ProviderError("No patient has this ID.", 404, {"upi": "No patient has this ID."})
    return patient


def access_for(db: Session, cu: CurrentUser, patient: Patient) -> AccessContext:
    if not cu.can(P.RECORDS_PUBLIC_READ):
        raise ProviderError("You don't have permission to view patient records.", 403)
    if cu.doctor is not None and cu.can(P.RECORDS_PRIVATE_READ):
        em = consent_service.active_emergency(db, cu.doctor.doctor_id, patient.patient_id, cu.session_ref)
        if em:
            return AccessContext("emergency", emergency=em)
        c = consent_service.active_consent(db, cu.doctor.doctor_id, patient.patient_id, cu.session_ref)
        if c:
            return AccessContext("consent", consent=c)
    return AccessContext("public")


def patient_view(db: Session, cu: CurrentUser, patient: Patient, ctx: AccessContext, *, page: int, ip: str, info_type: str | None = None) -> dict[str, Any]:
    pg = records.list_records(db, patient.patient_id, page=page, per_page=10, public_only=not ctx.full, info_type=info_type)
    hidden = 0
    if not ctx.full:  # tell the doctor *that* private records exist, never what they are
        hidden = db.scalar(select(func.count()).select_from(MedicalInformation).where(
            MedicalInformation.patient_id == patient.patient_id, MedicalInformation.visibility == Visibility.PRIVATE,
            MedicalInformation.status == RecordStatus.ACTIVE)) or 0
    show_demographics = ctx.full or patient.profile_visibility == Visibility.PUBLIC
    access(db, user_id=cu.id, patient_id=patient.patient_id, access_type=AccessType.VIEW_PROFILE if show_demographics else ctx.access_type, ip=ip, **ctx.log_kwargs())
    if pg.items:
        access(db, user_id=cu.id, patient_id=patient.patient_id, access_type=ctx.access_type, ip=ip, **ctx.log_kwargs())
    db.commit()
    pending = None
    if cu.doctor is not None:
        pending = db.scalar(select(AccessRequest).outerjoin(Consent, Consent.request_id == AccessRequest.request_id).where(
            AccessRequest.doctor_id == cu.doctor.doctor_id, AccessRequest.patient_id == patient.patient_id,
            AccessRequest.status.in_([AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED]),
            (Consent.consent_id.is_(None)) | (Consent.status == ConsentStatus.PENDING_OTP)))
    return {"page": pg, "hidden_private": int(hidden), "show_demographics": show_demographics, "pending_request": pending}


def readable(cu: CurrentUser, info: MedicalInformation, ctx: AccessContext) -> bool:
    """Public, or an active consent / emergency access. Authorship grants nothing: visibility is
    the patient's decision alone, so a private record needs consent even for the doctor who wrote it."""
    return info.visibility == Visibility.PUBLIC or ctx.full


def get_record_for(db: Session, cu: CurrentUser, patient: Patient, ctx: AccessContext, information_id: int, *, ip: str, download: bool = False) -> MedicalInformation:
    info = records.get_record(db, information_id, patient.patient_id)
    # A private record without consent/emergency is reported as "not found" (no existence leak).
    if info is None or not readable(cu, info, ctx):
        raise ProviderError("Record not found, or you don't have access to it.", 404)
    access(db, user_id=cu.id, patient_id=patient.patient_id, information_id=info.information_id, ip=ip,
           access_type=AccessType.DOWNLOAD_FILE if download else ctx.access_type, **ctx.log_kwargs())
    if ctx.level == "emergency" or download:
        audit(db, action="record.downloaded" if download else "record.viewed_emergency", entity="medical_information",
              entity_id=info.information_id, user_id=cu.id, ip=ip, hospital_id=cu.hospital_id)
    db.commit()
    return info


def can_edit(cu: CurrentUser, info: MedicalInformation, ctx: AccessContext) -> bool:
    """Update = permission + the record was written at the user's hospital + they can currently read it."""
    if not cu.can(P.RECORDS_UPDATE) or cu.hospital_id is None:
        return False
    if info.hospital_id != cu.hospital_id:
        return False
    return readable(cu, info, ctx)


def create_record(db: Session, cu: CurrentUser, patient: Patient, fields: dict[str, Any], stored: Any, ip: str) -> MedicalInformation:
    if not cu.can(P.RECORDS_CREATE) or cu.hospital_id is None:
        raise ProviderError("You don't have permission to add records.", 403)
    # Always private: who may see a patient's record is the patient's decision, not the clinician's.
    info = records.create(
        db, patient_id=patient.patient_id, author_user_id=cu.id, information_type=fields["information_type"], title=fields["title"],
        details=fields["details"], information_date=fields["information_date"], visibility=Visibility.PRIVATE,
        doctor_id=cu.doctor.doctor_id if cu.doctor else None, hospital_id=cu.hospital_id, file=stored,
    )
    access(db, user_id=cu.id, patient_id=patient.patient_id, access_type=AccessType.CREATE_RECORD, information_id=info.information_id, ip=ip)
    audit(db, action="record.created", entity="medical_information", entity_id=info.information_id, user_id=cu.id, ip=ip,
          hospital_id=cu.hospital_id, details={"patient_id": patient.patient_id, "visibility": info.visibility.value})
    notify(db, patient.user_id, NotificationKind.RECORD, f"{cu.user.full_name} added a record: {info.title[:80]}",
           "It's private. You can make it public if you want any doctor to see it.", f"/patient/records/{info.information_id}")
    db.commit()
    return info


def update_record(db: Session, cu: CurrentUser, patient: Patient, ctx: AccessContext, information_id: int, data: dict[str, Any], ip: str) -> dict:
    info = records.get_record(db, information_id, patient.patient_id, with_history=False)
    if info is None or not readable(cu, info, ctx):
        raise ProviderError("Record not found, or you don't have access to it.", 404)
    if not can_edit(cu, info, ctx):
        raise ProviderError("You can only edit records created at your hospital.", 403)
    # Clinicians can't change visibility - that is the patient's decision.
    data.pop("visibility", None)
    changes = records.update(db, info, cu.id, data)
    if changes:
        access(db, user_id=cu.id, patient_id=patient.patient_id, access_type=AccessType.UPDATE_RECORD, information_id=info.information_id, ip=ip, **ctx.log_kwargs())
        audit(db, action="record.updated", entity="medical_information", entity_id=info.information_id, user_id=cu.id, ip=ip,
              hospital_id=cu.hospital_id, details={"fields": sorted(changes)})
        notify(db, patient.user_id, NotificationKind.RECORD, f"{cu.user.full_name} updated a record: {info.title[:80]}",
               "See what changed in the record's update history.", f"/patient/records/{info.information_id}")
    db.commit()
    return changes


# ---------------------------------------------------------------- emergency

def start_emergency(db: Session, cu: CurrentUser, patient: Patient, reason: str, ip: str) -> EmergencyAccess:
    """System verifies role + verification + active hospital (via permissions), logs, notifies."""
    if not cu.can(P.EMERGENCY_ACCESS) or cu.doctor is None:
        raise ProviderError("Only verified doctors can use emergency access.", 403)
    if not cu.session_ref:
        raise ProviderError("Sign in again to use emergency access.", 401)
    reason = (reason or "").strip()
    if len(reason) < 20:
        raise ProviderError("Describe the emergency in at least 20 characters.", 422, {"reason": "At least 20 characters."})
    existing = consent_service.active_emergency(db, cu.doctor.doctor_id, patient.patient_id, cu.session_ref)
    if existing:
        return existing
    minutes = int(system_settings.get(db, "emergency_access_minutes", str(settings.emergency_access_minutes)) or settings.emergency_access_minutes)
    now = utcnow()
    em = EmergencyAccess(patient_id=patient.patient_id, doctor_id=cu.doctor.doctor_id, hospital_id=cu.doctor.hospital_id,
                         reason=reason[:2000], accessed_at=now, expires_at=now + timedelta(minutes=minutes),
                         session_ref=cu.session_ref)
    db.add(em)
    db.flush()
    audit(db, action="emergency.access_granted", entity="emergency_access", entity_id=em.emergency_access_id, user_id=cu.id, ip=ip,
          hospital_id=cu.doctor.hospital_id, details={"patient_id": patient.patient_id, "minutes": minutes})
    access(db, user_id=cu.id, patient_id=patient.patient_id, access_type=AccessType.VIEW_EMERGENCY, emergency_access_id=em.emergency_access_id, ip=ip)
    hospital_name = cu.doctor.hospital.name
    notify(db, patient.user_id, NotificationKind.EMERGENCY, f"Emergency access by {cu.user.full_name}",
           f"{hospital_name}. Reason: {reason[:300]}. Access ends {local_str(em.expires_at)} or when they sign out.", "/patient/access-history?emergency=1", sms=True)
    for (admin_user_id,) in db.execute(select(HospitalAdmin.user_id).where(HospitalAdmin.hospital_id == cu.doctor.hospital_id)):
        notify(db, admin_user_id, NotificationKind.EMERGENCY, f"{cu.user.full_name} used emergency access",
               f"Patient {patient.upi}. Reason: {reason[:300]}", "/admin/emergency")
    db.commit()
    return em


def end_emergency(db: Session, cu: CurrentUser, emergency_access_id: int, ip: str) -> None:
    em = db.scalar(select(EmergencyAccess).where(EmergencyAccess.emergency_access_id == emergency_access_id, EmergencyAccess.doctor_id == (cu.doctor.doctor_id if cu.doctor else -1)))
    if em is None:
        raise ProviderError("Emergency access not found.", 404)
    if em.ended_at is None and em.expires_at > utcnow():
        em.ended_at = utcnow()
        audit(db, action="emergency.access_ended", entity="emergency_access", entity_id=em.emergency_access_id, user_id=cu.id, ip=ip, hospital_id=em.hospital_id)
        db.commit()


# ---------------------------------------------------------------- lists for the doctor

def my_requests(db: Session, cu: CurrentUser, page: int = 1) -> Page:
    consent_service.expire_stale(db)
    consent_service.sweep_dead_sessions(db, doctor_id=cu.doctor.doctor_id)
    db.commit()
    stmt = (select(AccessRequest).where(AccessRequest.doctor_id == cu.doctor.doctor_id)
            .options(joinedload(AccessRequest.patient).joinedload(Patient.user)).order_by(AccessRequest.requested_at.desc()))
    return paginate(db, stmt, page, 15)


def consents_by_request(db: Session, request_ids: list[int]) -> dict[int, Consent]:
    if not request_ids:
        return {}
    return {c.request_id: c for c in db.scalars(select(Consent).where(Consent.request_id.in_(request_ids)))}


def my_emergencies(db: Session, cu: CurrentUser, page: int = 1) -> Page:
    stmt = (select(EmergencyAccess).where(EmergencyAccess.doctor_id == cu.doctor.doctor_id)
            .options(joinedload(EmergencyAccess.patient).joinedload(Patient.user)).order_by(EmergencyAccess.accessed_at.desc()))
    return paginate(db, stmt, page, 15)


@dataclass
class DoctorDashboard:
    active_consents: int
    pending_requests: int
    emergencies_30d: int
    records_created: int
    patients_seen_30d: int
    recent: list[dict[str, Any]]
    active_access: list[dict[str, Any]]


def dashboard(db: Session, cu: CurrentUser) -> DoctorDashboard:
    consent_service.expire_stale(db)
    if cu.doctor:
        consent_service.sweep_dead_sessions(db, doctor_id=cu.doctor.doctor_id)
    db.commit()
    now = utcnow()
    since = now - timedelta(days=30)
    did = cu.doctor.doctor_id if cu.doctor else None
    active = pending = em30 = 0
    active_access: list[dict[str, Any]] = []
    if did:
        active = db.scalar(select(func.count()).select_from(Consent).where(Consent.doctor_id == did, Consent.status == ConsentStatus.ACTIVE, Consent.expires_at > now,
                                                                   Consent.session_ref == cu.session_ref)) or 0
        pending = db.scalar(select(func.count()).select_from(AccessRequest).where(AccessRequest.doctor_id == did, AccessRequest.status == AccessRequestStatus.PENDING)) or 0
        em30 = db.scalar(select(func.count()).select_from(EmergencyAccess).where(EmergencyAccess.doctor_id == did, EmergencyAccess.accessed_at >= since)) or 0
        for c in db.scalars(select(Consent).where(Consent.doctor_id == did, Consent.status == ConsentStatus.ACTIVE, Consent.expires_at > now,
                                                  Consent.session_ref == cu.session_ref)
                            .options(joinedload(Consent.patient).joinedload(Patient.user)).order_by(Consent.expires_at).limit(8)).unique():
            active_access.append({"kind": "consent", "upi": c.patient.upi, "name": c.patient.user.full_name, "until": c.expires_at})
        for e in db.scalars(select(EmergencyAccess).where(EmergencyAccess.doctor_id == did, EmergencyAccess.expires_at > now, EmergencyAccess.ended_at.is_(None),
                                                          EmergencyAccess.session_ref == cu.session_ref)
                            .options(joinedload(EmergencyAccess.patient).joinedload(Patient.user)).limit(8)).unique():
            active_access.insert(0, {"kind": "emergency", "upi": e.patient.upi, "name": e.patient.user.full_name, "until": e.expires_at, "id": e.emergency_access_id})
    created = db.scalar(select(func.count()).select_from(MedicalInformation).where(MedicalInformation.created_by_user_id == cu.id)) or 0
    seen = db.scalar(select(func.count(func.distinct(AccessLog.patient_id))).where(AccessLog.user_id == cu.id, AccessLog.accessed_at >= since)) or 0
    # Recently opened patients: one grouped query + one lookup (no N+1).
    rows = db.execute(select(AccessLog.patient_id, func.max(AccessLog.accessed_at).label("last"))
                      .where(AccessLog.user_id == cu.id).group_by(AccessLog.patient_id).order_by(func.max(AccessLog.accessed_at).desc()).limit(6)).all()
    pats = {p.patient_id: p for p in db.scalars(select(Patient).where(Patient.patient_id.in_([r.patient_id for r in rows])).options(joinedload(Patient.user)))} if rows else {}
    recent = [{"upi": pats[r.patient_id].upi, "name": pats[r.patient_id].user.full_name, "last": r.last} for r in rows if r.patient_id in pats]
    return DoctorDashboard(int(active), int(pending), int(em30), int(created), int(seen), recent, active_access)


def update_own_profile(db: Session, cu: CurrentUser, data: dict[str, Any], ip: str) -> None:
    user: User = cu.user
    if data.get("phone") is not None:
        user.phone = data["phone"] or None
    if cu.doctor is not None and data.get("specialization"):
        cu.doctor.specialization = data["specialization"]
    audit(db, action="provider.profile_updated", entity="user", entity_id=user.user_id, user_id=user.user_id, ip=ip, hospital_id=cu.hospital_id)
    db.commit()

