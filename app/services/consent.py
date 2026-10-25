"""Consent lifecycle for private records.

Doctor requests (with purpose) -> patient approves and picks a duration ->
OTP sent to the patient's phone -> patient enters OTP -> consent ACTIVE until
``expires_at`` -> patient may revoke at any time (effective immediately, because
every private read re-checks ``active_consent`` against the DB).

Consent is also bound to the doctor's sign-in session (``session_ref``): it only
works in the session the request came from, and ends when that session ends
(sign-out, timeout, password change). A later visit needs a new consent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import AccessRequest, Consent, Doctor, EmergencyAccess, Patient
from app.models.enums import AccessRequestStatus, ConsentStatus, NotificationKind
from app.services.common import otp as otp_service
from app.services.common.audit import audit
from app.services.common.notification import notify
from app.services.common.security import local_str, utcnow
from app.services.common.session import session_ref_alive


class ConsentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


ALLOWED_DURATIONS = (1, 6, 24, 72, 168)  # hours offered to the patient


def expire_stale(db: Session) -> None:
    """Flip time-expired rows to EXPIRED (cheap, indexed). Reads never rely on this alone."""
    now = utcnow()
    db.execute(update(Consent).where(Consent.status == ConsentStatus.ACTIVE, Consent.expires_at <= now).values(status=ConsentStatus.EXPIRED))
    db.execute(update(AccessRequest).where(AccessRequest.status == AccessRequestStatus.PENDING, AccessRequest.expires_at <= now).values(status=AccessRequestStatus.EXPIRED))


def active_consent(db: Session, doctor_id: int, patient_id: int, session_ref: str | None) -> Consent | None:
    """Active, unexpired consent granted to *this* sign-in session of the doctor."""
    if not session_ref:
        return None
    now = utcnow()
    return db.scalar(
        select(Consent).where(
            Consent.doctor_id == doctor_id, Consent.patient_id == patient_id,
            Consent.status == ConsentStatus.ACTIVE, Consent.expires_at > now, Consent.session_ref == session_ref,
        ).order_by(Consent.expires_at.desc()).limit(1)
    )


def active_emergency(db: Session, doctor_id: int, patient_id: int, session_ref: str | None) -> EmergencyAccess | None:
    if not session_ref:
        return None
    now = utcnow()
    return db.scalar(
        select(EmergencyAccess).where(
            EmergencyAccess.doctor_id == doctor_id, EmergencyAccess.patient_id == patient_id,
            EmergencyAccess.expires_at > now, EmergencyAccess.ended_at.is_(None), EmergencyAccess.session_ref == session_ref,
        ).order_by(EmergencyAccess.expires_at.desc()).limit(1)
    )


# ---------------------------------------------------------------- session-bound lifetime

SESSION_ENDED_MSG = "The doctor has signed out since asking, so this request has closed. They will need to ask again."


def _end_consent(db: Session, c: Consent, now, reason: str) -> None:
    was_active = c.status == ConsentStatus.ACTIVE
    c.status = ConsentStatus.ENDED
    c.revoked_at = now
    audit(db, action="consent.session_ended", entity="consent", entity_id=c.consent_id, user_id=c.doctor.user_id,
          details={"patient_id": c.patient_id, "reason": reason}, hospital_id=c.doctor.hospital_id)
    if was_active:
        notify(db, c.patient.user_id, NotificationKind.CONSENT, f"{c.doctor.user.full_name}'s access has ended",
               "Their access to your private records ended when they signed out. They need your consent again next time.",
               "/patient/consent")


def _end_request(db: Session, req: AccessRequest, reason: str) -> None:
    req.status = AccessRequestStatus.CANCELLED
    audit(db, action="consent.request_session_ended", entity="access_request", entity_id=req.request_id,
          user_id=req.doctor.user_id, details={"patient_id": req.patient_id, "reason": reason}, hospital_id=req.doctor.hospital_id)


def _end_emergency(db: Session, em: EmergencyAccess, now, reason: str) -> None:
    em.ended_at = now
    audit(db, action="emergency.session_ended", entity="emergency_access", entity_id=em.emergency_access_id,
          user_id=em.doctor.user_id, details={"patient_id": em.patient_id, "reason": reason}, hospital_id=em.hospital_id)


def _open_items(db: Session, *conds_by_model):
    now = utcnow()
    c_conds, r_conds, e_conds = conds_by_model
    doc = joinedload(Consent.doctor).joinedload(Doctor.user)
    consents = list(db.scalars(select(Consent).where(Consent.status.in_([ConsentStatus.ACTIVE, ConsentStatus.PENDING_OTP]), *c_conds)
                               .options(doc, joinedload(Consent.patient).joinedload(Patient.user)).with_for_update()).unique())
    requests = list(db.scalars(select(AccessRequest).where(AccessRequest.status == AccessRequestStatus.PENDING, *r_conds)
                               .options(joinedload(AccessRequest.doctor).joinedload(Doctor.user)).with_for_update()).unique())
    emergencies = list(db.scalars(select(EmergencyAccess).where(EmergencyAccess.ended_at.is_(None), EmergencyAccess.expires_at > now, *e_conds)
                                  .options(joinedload(EmergencyAccess.doctor).joinedload(Doctor.user)).with_for_update()).unique())
    return now, consents, requests, emergencies


def end_for_session(db: Session, session_ref: str | None, reason: str = "signed_out") -> int:
    """End every consent, waiting request and emergency access tied to one doctor session."""
    if not session_ref:
        return 0
    now, consents, requests, emergencies = _open_items(
        db, (Consent.session_ref == session_ref,), (AccessRequest.session_ref == session_ref,), (EmergencyAccess.session_ref == session_ref,))
    for c in consents:
        _end_consent(db, c, now, reason)
    for r in requests:
        _end_request(db, r, reason)
    for e in emergencies:
        _end_emergency(db, e, now, reason)
    return len(consents) + len(requests) + len(emergencies)


def sweep_dead_sessions(db: Session, *, patient_id: int | None = None, doctor_id: int | None = None) -> None:
    """End items whose doctor session has gone away without a sign-out (timeout, password change,
    deactivation). Access never depends on this sweep, since reads match the live session, but it
    keeps what patients and doctors see accurate."""
    if patient_id is not None:
        conds = ((Consent.patient_id == patient_id,), (AccessRequest.patient_id == patient_id,), (EmergencyAccess.patient_id == patient_id,))
    elif doctor_id is not None:
        conds = ((Consent.doctor_id == doctor_id,), (AccessRequest.doctor_id == doctor_id,), (EmergencyAccess.doctor_id == doctor_id,))
    else:
        conds = ((), (), ())
    now, consents, requests, emergencies = _open_items(db, *conds)
    alive: dict[str | None, bool] = {}

    def dead(ref: str | None) -> bool:
        if ref not in alive:
            alive[ref] = session_ref_alive(ref)
        return not alive[ref]

    for c in consents:
        if dead(c.session_ref):
            _end_consent(db, c, now, "session_expired")
    for r in requests:
        if dead(r.session_ref):
            _end_request(db, r, "session_expired")
    for e in emergencies:
        if dead(e.session_ref):
            _end_emergency(db, e, now, "session_expired")


# ---------------------------------------------------------------- doctor side

def request_access(db: Session, *, doctor: Doctor, patient: Patient, purpose: str, ip: str, session_ref: str | None) -> AccessRequest:
    if not session_ref:
        raise ConsentError("Sign in again to request access.", 401)
    expire_stale(db)
    sweep_dead_sessions(db, doctor_id=doctor.doctor_id)
    if active_consent(db, doctor.doctor_id, patient.patient_id, session_ref):
        raise ConsentError("You already have active consent for this patient.", 409)
    pending = db.scalar(select(AccessRequest).where(
        AccessRequest.doctor_id == doctor.doctor_id, AccessRequest.patient_id == patient.patient_id,
        AccessRequest.status.in_([AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED]),
    ).join(Consent, Consent.request_id == AccessRequest.request_id, isouter=True).where(
        (Consent.consent_id.is_(None)) | (Consent.status == ConsentStatus.PENDING_OTP)
    ))
    if pending:
        raise ConsentError("A request to this patient is already waiting for their answer.", 409)
    now = utcnow()
    req = AccessRequest(patient_id=patient.patient_id, doctor_id=doctor.doctor_id, purpose=purpose, requested_at=now,
                        status=AccessRequestStatus.PENDING, session_ref=session_ref, expires_at=now + timedelta(hours=settings.access_request_ttl_hours))
    db.add(req)
    db.flush()
    audit(db, action="consent.requested", entity="access_request", entity_id=req.request_id, user_id=doctor.user_id, ip=ip,
          details={"patient_id": patient.patient_id}, hospital_id=doctor.hospital_id)
    notify(db, patient.user_id, NotificationKind.ACCESS_REQUEST, f"{doctor.user.full_name} asked to see your private records",
           f"Purpose: {purpose[:300]}", "/patient/consent")
    return req


def cancel_request(db: Session, *, doctor: Doctor, request_id: int, ip: str) -> None:
    req = db.scalar(select(AccessRequest).where(AccessRequest.request_id == request_id, AccessRequest.doctor_id == doctor.doctor_id).with_for_update())
    if req is None:
        raise ConsentError("Request not found.", 404)
    if req.status != AccessRequestStatus.PENDING:
        raise ConsentError("Only a waiting request can be cancelled.", 409)
    req.status = AccessRequestStatus.CANCELLED
    audit(db, action="consent.request_cancelled", entity="access_request", entity_id=request_id, user_id=doctor.user_id, ip=ip, hospital_id=doctor.hospital_id)


# ---------------------------------------------------------------- patient side

def _own_request(db: Session, patient: Patient, request_id: int) -> AccessRequest:
    req = db.scalar(
        select(AccessRequest).where(AccessRequest.request_id == request_id, AccessRequest.patient_id == patient.patient_id)
        .options(joinedload(AccessRequest.doctor).joinedload(Doctor.user)).with_for_update()
    )
    if req is None:  # also covers "belongs to another patient" - same answer, no leak
        raise ConsentError("Request not found.", 404)
    return req


@dataclass
class ApprovalStarted:
    consent_id: int
    expires_in: int
    sent_to: str


def approve(db: Session, *, patient: Patient, request_id: int, duration_hours: int, ip: str) -> ApprovalStarted:
    expire_stale(db)
    if duration_hours not in ALLOWED_DURATIONS or duration_hours > settings.consent_max_hours:
        raise ConsentError("Choose one of the offered durations.", 422)
    req = _own_request(db, patient, request_id)
    consent = db.scalar(select(Consent).where(Consent.request_id == req.request_id))
    if req.status in (AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED) and not session_ref_alive(req.session_ref):
        sweep_dead_sessions(db, patient_id=patient.patient_id)
        db.commit()
        raise ConsentError(SESSION_ENDED_MSG, 409)
    if req.status == AccessRequestStatus.APPROVED and consent and consent.status == ConsentStatus.PENDING_OTP:
        consent.duration_hours = duration_hours  # patient re-opened the OTP step
    elif req.status != AccessRequestStatus.PENDING:
        raise ConsentError("This request has already been answered or has expired.", 409)
    else:
        req.status = AccessRequestStatus.APPROVED
        req.responded_at = utcnow()
        consent = Consent(request_id=req.request_id, patient_id=patient.patient_id, doctor_id=req.doctor_id,
                          status=ConsentStatus.PENDING_OTP, duration_hours=duration_hours, session_ref=req.session_ref)
        db.add(consent)
        db.flush()
    issued = otp_service.issue(db, consent.consent_id, patient.user.phone, context="approve record access")
    audit(db, action="consent.approved_pending_otp", entity="consent", entity_id=consent.consent_id, user_id=patient.user_id, ip=ip,
          details={"doctor_id": req.doctor_id, "duration_hours": duration_hours})
    return ApprovalStarted(consent_id=consent.consent_id, expires_in=issued.expires_in, sent_to=issued.sent_to)


def _own_consent(db: Session, patient: Patient, consent_id: int) -> Consent:
    c = db.scalar(select(Consent).where(Consent.consent_id == consent_id, Consent.patient_id == patient.patient_id)
                  .options(joinedload(Consent.doctor).joinedload(Doctor.user)).with_for_update())
    if c is None:
        raise ConsentError("Consent not found.", 404)
    return c


def _check_doctor_session(db: Session, patient: Patient, c: Consent) -> None:
    if c.status == ConsentStatus.ENDED or (c.status == ConsentStatus.PENDING_OTP and not session_ref_alive(c.session_ref)):
        sweep_dead_sessions(db, patient_id=patient.patient_id)
        db.commit()
        raise ConsentError(SESSION_ENDED_MSG, 409)


def resend_otp(db: Session, *, patient: Patient, consent_id: int, ip: str):
    c = _own_consent(db, patient, consent_id)
    _check_doctor_session(db, patient, c)
    if c.status != ConsentStatus.PENDING_OTP:
        raise ConsentError("This consent doesn't need a code.", 409)
    issued = otp_service.issue(db, c.consent_id, patient.user.phone, context="approve record access")
    audit(db, action="consent.otp_resent", entity="consent", entity_id=c.consent_id, user_id=patient.user_id, ip=ip)
    return issued


def verify_otp(db: Session, *, patient: Patient, consent_id: int, code: str, ip: str) -> Consent:
    c = _own_consent(db, patient, consent_id)
    _check_doctor_session(db, patient, c)
    if c.status != ConsentStatus.PENDING_OTP:
        raise ConsentError("This consent is not waiting for a code.", 409)
    try:
        otp_service.verify(db, c.consent_id, code)
    except otp_service.OtpError as e:
        audit(db, action="consent.otp_failed", entity="consent", entity_id=c.consent_id, user_id=patient.user_id, ip=ip)
        db.commit()  # keep the attempt counter even though we raise
        raise ConsentError(e.message, e.status_code) from e
    now = utcnow()
    c.status = ConsentStatus.ACTIVE
    c.granted_at = now
    c.expires_at = now + timedelta(hours=c.duration_hours)
    audit(db, action="consent.granted", entity="consent", entity_id=c.consent_id, user_id=patient.user_id, ip=ip,
          details={"doctor_id": c.doctor_id, "expires_at": c.expires_at.isoformat()}, hospital_id=c.doctor.hospital_id)
    notify(db, c.doctor.user_id, NotificationKind.CONSENT, f"{patient.user.full_name} approved your access request",
           f"Access to private records until {local_str(c.expires_at)} or until you sign out, whichever comes first.",
           f"/doctor/patients/{patient.upi}")
    return c


def reject(db: Session, *, patient: Patient, request_id: int, ip: str) -> None:
    req = _own_request(db, patient, request_id)
    if req.status not in (AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED):
        raise ConsentError("This request has already been answered or has expired.", 409)
    consent = db.scalar(select(Consent).where(Consent.request_id == req.request_id))
    if consent and consent.status != ConsentStatus.PENDING_OTP:
        raise ConsentError("This request was already approved; revoke the consent instead.", 409)
    if consent:
        consent.status = ConsentStatus.REVOKED
        consent.revoked_at = utcnow()
    req.status = AccessRequestStatus.REJECTED
    req.responded_at = utcnow()
    audit(db, action="consent.rejected", entity="access_request", entity_id=req.request_id, user_id=patient.user_id, ip=ip,
          details={"doctor_id": req.doctor_id})
    notify(db, req.doctor.user_id, NotificationKind.CONSENT, f"{patient.user.full_name} declined your access request",
           "You can still see records the patient has made public.", f"/doctor/patients/{patient.upi}")


def revoke(db: Session, *, patient: Patient, consent_id: int, ip: str) -> None:
    c = _own_consent(db, patient, consent_id)
    if c.status not in (ConsentStatus.ACTIVE, ConsentStatus.PENDING_OTP):
        raise ConsentError("This consent is no longer active.", 409)
    c.status = ConsentStatus.REVOKED
    c.revoked_at = utcnow()
    audit(db, action="consent.revoked", entity="consent", entity_id=c.consent_id, user_id=patient.user_id, ip=ip,
          details={"doctor_id": c.doctor_id}, hospital_id=c.doctor.hospital_id)
    notify(db, c.doctor.user_id, NotificationKind.CONSENT, f"{patient.user.full_name} revoked your access",
           "Private records are no longer available to you.", None)


def patient_overview(db: Session, patient_id: int) -> dict[str, list]:
    """Everything the patient's consent page shows, eager-loaded in a few queries."""
    expire_stale(db)
    sweep_dead_sessions(db, patient_id=patient_id)
    db.commit()
    doc_opts = joinedload(AccessRequest.doctor).joinedload(Doctor.user)
    pending = list(db.scalars(
        select(AccessRequest).outerjoin(Consent, Consent.request_id == AccessRequest.request_id)
        .where(AccessRequest.patient_id == patient_id, and_(
            AccessRequest.status.in_([AccessRequestStatus.PENDING, AccessRequestStatus.APPROVED]),
            (Consent.consent_id.is_(None)) | (Consent.status == ConsentStatus.PENDING_OTP),
        ))
        .options(doc_opts, joinedload(AccessRequest.doctor).joinedload(Doctor.hospital))
        .order_by(AccessRequest.requested_at.desc())
    ).unique())
    pending_consents = {c.request_id: c for c in db.scalars(select(Consent).where(
        Consent.patient_id == patient_id, Consent.status == ConsentStatus.PENDING_OTP))}
    consents = list(db.scalars(
        select(Consent).where(Consent.patient_id == patient_id, Consent.status != ConsentStatus.PENDING_OTP)
        .options(joinedload(Consent.doctor).joinedload(Doctor.user), joinedload(Consent.doctor).joinedload(Doctor.hospital),
                 joinedload(Consent.request))
        .order_by(Consent.granted_at.desc()).limit(100)
    ).unique())
    closed = list(db.scalars(
        select(AccessRequest).where(AccessRequest.patient_id == patient_id,
                                    AccessRequest.status.in_([AccessRequestStatus.REJECTED, AccessRequestStatus.EXPIRED, AccessRequestStatus.CANCELLED]))
        .options(doc_opts).order_by(AccessRequest.requested_at.desc()).limit(50)
    ).unique())
    return {"pending": pending, "pending_consents": pending_consents, "consents": consents, "closed": closed}
