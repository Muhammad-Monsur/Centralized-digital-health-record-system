"""Administration service.

Two admin types:
* Hospital admin - scope = their own hospital. Creates and manages doctor and staff
  accounts there, verifies licences, edits their hospital's contact details, and sees
  consent / emergency / audit activity involving their hospital.
* System admin - scope = everything. Creates hospitals and hospital admins, edits RBAC,
  system settings and backups.

Scope is enforced in every query here (``_scope``), not only by hiding UI.
"""
from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from app.middleware.auth import CurrentUser
from app.models import (
    AccessLog,
    AccessRequest,
    AuditLog,
    Consent,
    Doctor,
    EmergencyAccess,
    HealthcareStaff,
    Hospital,
    HospitalAdmin,
    MedicalInformation,
    Patient,
    Permission,
    Role,
    RolePermission,
    SystemSetting,
    User,
    UserRole,
)
from app.models.enums import (
    AccessRequestStatus,
    ConsentStatus,
    HospitalStatus,
    NotificationKind,
    RoleName,
    RoleStatus,
    UserStatus,
    VerificationStatus,
)
from app.schemas.admin import AccountCreateIn, AccountUpdateIn, HospitalIn, HospitalUpdateIn
from app.services.common import cache, system_settings
from app.services.common.audit import audit
from app.services.common.notification import notify
from app.services.common.pagination import Page, paginate
from app.services.common.permissions import DEFAULT_ROLES, P
from app.services.common.security import hash_password, utcnow
from app.services.common.session import destroy_user_sessions


class AdminError(Exception):
    def __init__(self, message: str, status_code: int = 400, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.fields = fields or {}


BUILTIN_ROLES = {r.value for r in RoleName}


def _scope(cu: CurrentUser) -> int | None:
    """None = system-wide; otherwise the only hospital this admin may touch."""
    if cu.is_system_admin and cu.can(P.HOSPITAL_MANAGE_ALL):
        return None
    if cu.hospital_admin is None:
        raise AdminError("You don't have an administration scope.", 403)
    return cu.hospital_admin.hospital_id


# ================================================================ users

def _user_query() -> Select:
    return select(User).options(
        selectinload(User.roles), joinedload(User.doctor).joinedload(Doctor.hospital), joinedload(User.staff).joinedload(HealthcareStaff.hospital),
        joinedload(User.hospital_admin).joinedload(HospitalAdmin.hospital), joinedload(User.patient), joinedload(User.system_admin),
    )


def _in_hospital(hid: int):
    return or_(
        User.user_id.in_(select(Doctor.user_id).where(Doctor.hospital_id == hid)),
        User.user_id.in_(select(HealthcareStaff.user_id).where(HealthcareStaff.hospital_id == hid)),
        User.user_id.in_(select(HospitalAdmin.user_id).where(HospitalAdmin.hospital_id == hid)),
    )


def list_users(db: Session, cu: CurrentUser, *, role: str | None, status: str | None, q: str | None, verification: str | None,
               page: int, per_page: int = 15) -> Page[User]:
    hid = _scope(cu)
    stmt = _user_query()
    if hid is not None:
        stmt = stmt.where(_in_hospital(hid))
    if role:
        stmt = stmt.where(User.user_id.in_(select(UserRole.user_id).join(Role).where(Role.role_name == role)))
    if status in UserStatus._value2member_map_:
        stmt = stmt.where(User.status == UserStatus(status))
    if verification in VerificationStatus._value2member_map_:
        stmt = stmt.where(User.user_id.in_(select(Doctor.user_id).where(Doctor.verification_status == VerificationStatus(verification))))
    if q:
        esc = q.strip()[:80].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        stmt = stmt.where(or_(User.full_name.like(like), User.email.like(like), User.username.like(like)))
    return paginate(db, stmt.order_by(User.created_at.desc(), User.user_id.desc()), page, per_page)


def get_user(db: Session, cu: CurrentUser, user_id: int) -> User:
    hid = _scope(cu)
    stmt = _user_query().where(User.user_id == user_id)
    if hid is not None:
        stmt = stmt.where(_in_hospital(hid))
    user = db.scalar(stmt)
    if user is None:
        raise AdminError("User not found.", 404)
    return user


def _assert_manageable(cu: CurrentUser, target: User) -> None:
    """Hospital admins manage doctors and staff of their hospital; only system admins manage admins/patients."""
    if target.user_id == cu.id:
        raise AdminError("You can't change your own account here. Use Profile & security.", 403)
    if cu.is_system_admin:
        if target.system_admin is not None:
            raise AdminError("System administrator accounts can't be changed from the portal.", 403)
        return
    if target.doctor is None and target.staff is None:
        raise AdminError("Hospital administrators can manage doctor and staff accounts only.", 403)


def _username_from_email(db: Session, email: str) -> str:
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower())[:40] or "user"
    if len(base) < 3:
        base = f"{base}usr"
    candidate, n = base, 1
    while db.scalar(select(User.user_id).where(User.username == candidate)):
        n += 1
        candidate = f"{base}{n}"
    return candidate


def create_account(db: Session, cu: CurrentUser, data: AccountCreateIn, ip: str) -> User:
    hid = _scope(cu)
    if data.kind == "hospital_admin" and hid is not None:
        raise AdminError("Only the system administrator can create hospital administrators.", 403)
    hospital_id = hid if hid is not None else data.hospital_id
    errors: dict[str, str] = {}
    if hospital_id is None:
        errors["hospital_id"] = "Choose a hospital."
    hospital = db.get(Hospital, hospital_id) if hospital_id else None
    if hospital_id and hospital is None:
        errors["hospital_id"] = "Hospital not found."
    elif hospital is not None and hospital.status != HospitalStatus.ACTIVE:
        errors["hospital_id"] = "This hospital is inactive."
    if data.kind == "doctor":
        if not data.designation:
            errors["designation"] = "Enter the doctor's designation."
        if not data.license_number:
            errors["license_number"] = "Enter the licence number."
        elif db.scalar(select(Doctor.doctor_id).where(Doctor.license_number == data.license_number)):
            errors["license_number"] = "A doctor with this licence number already exists."
    if data.kind == "staff" and not data.position:
        errors["position"] = "Enter the staff member's position."
    if db.scalar(select(User.user_id).where(func.lower(User.email) == data.email)):
        errors["email"] = "An account with this email already exists."
    if errors:
        raise AdminError(next(iter(errors.values())), 422, errors)

    role_name = {"doctor": RoleName.DOCTOR, "staff": RoleName.STAFF, "hospital_admin": RoleName.HOSPITAL_ADMIN}[data.kind].value
    role = db.scalar(select(Role).where(Role.role_name == role_name))
    assert role is not None and hospital is not None
    user = User(username=_username_from_email(db, data.email), email=data.email, full_name=data.full_name, phone=data.phone,
                password_hash=hash_password(data.password), status=UserStatus.ACTIVE,
                must_change_password=True)  # the admin knows this password; the user must replace it
    db.add(user)
    try:
        db.flush()
        db.add(UserRole(user_id=user.user_id, role_id=role.role_id))
        if data.kind == "doctor":
            # Created by an administrator who vouches for the licence -> verified.
            db.add(Doctor(user_id=user.user_id, hospital_id=hospital.hospital_id, license_number=data.license_number or "",
                          designation=data.designation or "", specialization=data.specialization or "General practice",
                          verification_status=VerificationStatus.VERIFIED))
        elif data.kind == "staff":
            db.add(HealthcareStaff(user_id=user.user_id, hospital_id=hospital.hospital_id, position=data.position or ""))
        else:
            db.add(HospitalAdmin(user_id=user.user_id, hospital_id=hospital.hospital_id))
        db.flush()
        audit(db, action=f"admin.{data.kind}_created", entity="user", entity_id=user.user_id, user_id=cu.id, ip=ip,
              hospital_id=hospital.hospital_id, details={"email": user.email, "kind": data.kind})
        notify(db, user.user_id, NotificationKind.ACCOUNT, "Welcome to CDHRS",
               f"Your account at {hospital.name} was created by {cu.user.full_name}. Please change your password.", None)
        db.commit()
        cache.invalidate_prefix("admin:")
    except IntegrityError as e:
        db.rollback()
        raise AdminError("That email or licence number was just used by another account.", 409) from e
    return user


def update_account(db: Session, cu: CurrentUser, user_id: int, data: AccountUpdateIn, ip: str) -> None:
    target = get_user(db, cu, user_id)
    _assert_manageable(cu, target)
    if data.email != target.email and db.scalar(select(User.user_id).where(func.lower(User.email) == data.email, User.user_id != user_id)):
        raise AdminError("Another account uses this email.", 409, {"email": "Another account uses this email."})
    if target.doctor and data.license_number and data.license_number != target.doctor.license_number and \
            db.scalar(select(Doctor.doctor_id).where(Doctor.license_number == data.license_number)):
        raise AdminError("Another doctor has this licence number.", 409, {"license_number": "Already in use."})
    target.full_name, target.email, target.phone = data.full_name, data.email, data.phone
    if target.doctor:
        target.doctor.designation = data.designation or target.doctor.designation
        target.doctor.specialization = data.specialization or target.doctor.specialization
        target.doctor.license_number = (data.license_number or target.doctor.license_number).upper()
    if target.staff and data.position:
        target.staff.position = data.position
    audit(db, action="admin.user_updated", entity="user", entity_id=user_id, user_id=cu.id, ip=ip, hospital_id=_target_hospital(target))
    db.commit()


def _target_hospital(u: User) -> int | None:
    for link in (u.doctor, u.staff, u.hospital_admin):
        if link is not None:
            return link.hospital_id
    return None


def set_user_status(db: Session, cu: CurrentUser, user_id: int, status: str, ip: str) -> None:
    target = get_user(db, cu, user_id)
    _assert_manageable(cu, target)
    target.status = UserStatus.ACTIVE if status == "active" else UserStatus.INACTIVE
    if target.status == UserStatus.ACTIVE:
        target.locked_until = None
        target.failed_login_count = 0
    audit(db, action="admin.user_activated" if status == "active" else "admin.user_deactivated", entity="user", entity_id=user_id,
          user_id=cu.id, ip=ip, hospital_id=_target_hospital(target))
    db.commit()
    if target.status != UserStatus.ACTIVE:
        destroy_user_sessions(target.user_id)  # signed out everywhere, immediately


def unlock_user(db: Session, cu: CurrentUser, user_id: int, ip: str) -> None:
    target = get_user(db, cu, user_id)
    _assert_manageable(cu, target)
    target.locked_until = None
    target.failed_login_count = 0
    audit(db, action="admin.user_unlocked", entity="user", entity_id=user_id, user_id=cu.id, ip=ip, hospital_id=_target_hospital(target))
    db.commit()


def reset_password(db: Session, cu: CurrentUser, user_id: int, password: str, ip: str) -> None:
    target = get_user(db, cu, user_id)
    _assert_manageable(cu, target)
    target.password_hash = hash_password(password)
    target.must_change_password = True
    target.locked_until = None
    target.failed_login_count = 0
    audit(db, action="admin.password_reset", entity="user", entity_id=user_id, user_id=cu.id, ip=ip, hospital_id=_target_hospital(target))
    notify(db, target.user_id, NotificationKind.ACCOUNT, "Your password was reset by an administrator", "Change it from Profile & security.", None)
    db.commit()
    destroy_user_sessions(target.user_id)


def verify_doctor(db: Session, cu: CurrentUser, user_id: int, status: VerificationStatus, note: str | None, ip: str) -> None:
    if not cu.can(P.DOCTOR_VERIFY):
        raise AdminError("You can't verify doctors.", 403)
    target = get_user(db, cu, user_id)
    _assert_manageable(cu, target)
    if target.doctor is None:
        raise AdminError("This account isn't a doctor.", 400)
    target.doctor.verification_status = status
    target.doctor.verification_note = note
    if status == VerificationStatus.VERIFIED and target.status == UserStatus.PENDING:
        target.status = UserStatus.ACTIVE
    audit(db, action=f"admin.doctor_{status.value}", entity="doctor", entity_id=target.doctor.doctor_id, user_id=cu.id, ip=ip,
          hospital_id=target.doctor.hospital_id)
    notify(db, target.user_id, NotificationKind.ACCOUNT, f"Your licence verification: {status.value}", note or "", "/doctor")
    db.commit()
    cache.invalidate_prefix("admin:")


# ================================================================ hospitals

def list_hospitals(db: Session, cu: CurrentUser) -> list[dict[str, Any]]:
    hid = _scope(cu)
    stmt = select(Hospital).order_by(Hospital.name)
    if hid is not None:
        stmt = stmt.where(Hospital.hospital_id == hid)
    hospitals = list(db.scalars(stmt))
    ids = [h.hospital_id for h in hospitals]
    # counts in 3 grouped queries (not 3 per hospital)
    docs = dict(db.execute(select(Doctor.hospital_id, func.count()).where(Doctor.hospital_id.in_(ids)).group_by(Doctor.hospital_id)).tuples().all()) if ids else {}
    staff = dict(db.execute(select(HealthcareStaff.hospital_id, func.count()).where(HealthcareStaff.hospital_id.in_(ids)).group_by(HealthcareStaff.hospital_id)).tuples().all()) if ids else {}
    admins = {}
    if ids:
        for hid_, name in db.execute(select(HospitalAdmin.hospital_id, User.full_name).join(User, User.user_id == HospitalAdmin.user_id).where(HospitalAdmin.hospital_id.in_(ids))):
            admins.setdefault(hid_, []).append(name)
    return [{"h": h, "doctors": docs.get(h.hospital_id, 0), "staff": staff.get(h.hospital_id, 0), "admins": admins.get(h.hospital_id, [])} for h in hospitals]


def get_hospital(db: Session, cu: CurrentUser, hospital_id: int) -> Hospital:
    hid = _scope(cu)
    if hid is not None and hid != hospital_id:
        raise AdminError("Hospital not found.", 404)
    h = db.get(Hospital, hospital_id)
    if h is None:
        raise AdminError("Hospital not found.", 404)
    return h


def create_hospital(db: Session, cu: CurrentUser, data: HospitalIn, ip: str) -> Hospital:
    if not cu.can(P.HOSPITAL_MANAGE_ALL):
        raise AdminError("Only the system administrator can add hospitals.", 403)
    reg = data.registration_number.upper()
    if db.scalar(select(Hospital.hospital_id).where(Hospital.registration_number == reg)):
        raise AdminError("A hospital with this registration number exists.", 409, {"registration_number": "Already registered."})
    h = Hospital(name=data.name, registration_number=reg, address=data.address, phone=data.phone, status=HospitalStatus.ACTIVE)
    db.add(h)
    db.flush()
    audit(db, action="admin.hospital_created", entity="hospital", entity_id=h.hospital_id, user_id=cu.id, ip=ip, hospital_id=h.hospital_id)
    db.commit()
    cache.invalidate_prefix("admin:")
    return h


def update_hospital(db: Session, cu: CurrentUser, hospital_id: int, data: HospitalUpdateIn, ip: str) -> None:
    h = get_hospital(db, cu, hospital_id)
    h.name, h.address, h.phone = data.name, data.address, data.phone
    audit(db, action="admin.hospital_updated", entity="hospital", entity_id=hospital_id, user_id=cu.id, ip=ip, hospital_id=hospital_id)
    db.commit()


def set_hospital_status(db: Session, cu: CurrentUser, hospital_id: int, status: HospitalStatus, ip: str) -> None:
    if not cu.can(P.HOSPITAL_MANAGE_ALL):
        raise AdminError("Only the system administrator can activate or deactivate hospitals.", 403)
    h = get_hospital(db, cu, hospital_id)
    h.status = status
    audit(db, action=f"admin.hospital_{status.value}", entity="hospital", entity_id=hospital_id, user_id=cu.id, ip=ip, hospital_id=hospital_id)
    db.commit()
    cache.invalidate_prefix("admin:")


# ================================================================ roles & permissions

def roles_matrix(db: Session) -> dict[str, Any]:
    roles = list(db.scalars(select(Role).order_by(Role.role_id).options(selectinload(Role.permissions).joinedload(RolePermission.permission))))
    perms = list(db.scalars(select(Permission).order_by(Permission.permission_name)))
    counts = dict(db.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id)).tuples().all())
    granted = {r.role_id: {rp.permission.permission_name for rp in r.permissions} for r in roles}
    groups: dict[str, list[Permission]] = {}
    for p in perms:
        groups.setdefault(p.permission_name.split(".")[0], []).append(p)
    return {"roles": roles, "groups": groups, "granted": granted, "counts": counts, "builtin": BUILTIN_ROLES}


def create_role(db: Session, cu: CurrentUser, name: str, description: str, ip: str) -> Role:
    if db.scalar(select(Role.role_id).where(Role.role_name == name)):
        raise AdminError("A role with this name exists.", 409, {"role_name": "Already exists."})
    role = Role(role_name=name, description=description or "", status=RoleStatus.ACTIVE)
    db.add(role)
    db.flush()
    audit(db, action="admin.role_created", entity="role", entity_id=role.role_id, user_id=cu.id, ip=ip, details={"role": name})
    db.commit()
    return role


def set_role_permissions(db: Session, cu: CurrentUser, role_id: int, names: list[str], ip: str) -> dict[str, list[str]]:
    role = db.get(Role, role_id)
    if role is None:
        raise AdminError("Role not found.", 404)
    wanted = set(names)
    perms = {p.permission_name: p for p in db.scalars(select(Permission))}
    unknown = wanted - set(perms)
    if unknown:
        raise AdminError(f"Unknown permission: {sorted(unknown)[0]}", 422)
    if role.role_name == RoleName.SYSTEM_ADMIN.value:
        # Guard rail: the system admin can't lock everyone out of RBAC/admin.
        missing = {P.ROLE_MANAGE, P.ADMIN_DASHBOARD} - wanted
        if missing:
            raise AdminError("The system administrator role must keep 'admin.role.manage' and 'admin.dashboard.view'.", 422)
    current = {rp.permission.permission_name: rp for rp in db.scalars(select(RolePermission).where(RolePermission.role_id == role_id).options(joinedload(RolePermission.permission)))}
    added = sorted(wanted - set(current))
    removed = sorted(set(current) - wanted)
    for n in removed:
        db.delete(current[n])
    for n in added:
        db.add(RolePermission(role_id=role_id, permission_id=perms[n].permission_id))
    if added or removed:
        audit(db, action="admin.role_permissions_changed", entity="role", entity_id=role_id, user_id=cu.id, ip=ip,
              details={"role": role.role_name, "added": added, "removed": removed})
    db.commit()
    return {"added": added, "removed": removed}


def set_role_status(db: Session, cu: CurrentUser, role_id: int, status: str, ip: str) -> None:
    role = db.get(Role, role_id)
    if role is None:
        raise AdminError("Role not found.", 404)
    if role.role_name in BUILTIN_ROLES:
        raise AdminError("Built-in roles can't be deactivated; edit their permissions instead.", 422)
    role.status = RoleStatus(status)
    audit(db, action=f"admin.role_{status}", entity="role", entity_id=role_id, user_id=cu.id, ip=ip)
    db.commit()


def reset_role_defaults(db: Session, cu: CurrentUser, role_id: int, ip: str) -> None:
    role = db.get(Role, role_id)
    if role is None or role.role_name not in DEFAULT_ROLES:
        raise AdminError("Only built-in roles have defaults.", 422)
    set_role_permissions(db, cu, role_id, DEFAULT_ROLES[role.role_name][1], ip)


# ================================================================ monitoring

def _doctor_ids_of(hid: int):
    return select(Doctor.doctor_id).where(Doctor.hospital_id == hid)


def list_consents(db: Session, cu: CurrentUser, *, status: str | None, page: int) -> Page:
    hid = _scope(cu)
    stmt = (select(AccessRequest)
            .options(joinedload(AccessRequest.doctor).joinedload(Doctor.user), joinedload(AccessRequest.doctor).joinedload(Doctor.hospital),
                     joinedload(AccessRequest.patient).joinedload(Patient.user))
            .order_by(AccessRequest.requested_at.desc()))
    if hid is not None:
        stmt = stmt.where(AccessRequest.doctor_id.in_(_doctor_ids_of(hid)))
    if status in AccessRequestStatus._value2member_map_:
        stmt = stmt.where(AccessRequest.status == AccessRequestStatus(status))
    return paginate(db, stmt, page, 20)


def consent_map(db: Session, request_ids: list[int]) -> dict[int, Consent]:
    if not request_ids:
        return {}
    return {c.request_id: c for c in db.scalars(select(Consent).where(Consent.request_id.in_(request_ids)))}


def list_emergencies(db: Session, cu: CurrentUser, *, page: int, active_only: bool = False) -> Page:
    hid = _scope(cu)
    stmt = (select(EmergencyAccess)
            .options(joinedload(EmergencyAccess.doctor).joinedload(Doctor.user), joinedload(EmergencyAccess.hospital),
                     joinedload(EmergencyAccess.patient).joinedload(Patient.user))
            .order_by(EmergencyAccess.accessed_at.desc()))
    if hid is not None:
        stmt = stmt.where(EmergencyAccess.hospital_id == hid)
    if active_only:
        stmt = stmt.where(EmergencyAccess.expires_at > utcnow(), EmergencyAccess.ended_at.is_(None))
    return paginate(db, stmt, page, 20)


def end_emergency(db: Session, cu: CurrentUser, emergency_access_id: int, ip: str) -> None:
    hid = _scope(cu)
    em = db.get(EmergencyAccess, emergency_access_id)
    if em is None or (hid is not None and em.hospital_id != hid):
        raise AdminError("Emergency access not found.", 404)
    if em.ended_at is None and em.expires_at > utcnow():
        em.ended_at = utcnow()
        audit(db, action="admin.emergency_ended", entity="emergency_access", entity_id=emergency_access_id, user_id=cu.id, ip=ip, hospital_id=em.hospital_id)
        db.commit()


def inter_hospital_accesses(db: Session, cu: CurrentUser, *, page: int) -> Page:
    """Clinicians opening records that were written at a DIFFERENT hospital."""
    hid = _scope(cu)
    rec_h = aliased(Hospital)
    doc_h = aliased(Hospital)
    stmt = (
        select(AccessLog.accessed_at, AccessLog.access_type, User.full_name.label("who"), doc_h.name.label("from_h"),
               rec_h.name.label("record_h"), MedicalInformation.information_type, Patient.upi, AccessLog.emergency_access_id, AccessLog.consent_id,
               Doctor.hospital_id.label("doc_hid"), MedicalInformation.hospital_id.label("rec_hid"))
        .join(User, User.user_id == AccessLog.user_id)
        .join(Doctor, Doctor.user_id == User.user_id)
        .join(MedicalInformation, MedicalInformation.information_id == AccessLog.information_id)
        .join(Patient, Patient.patient_id == AccessLog.patient_id)
        .join(doc_h, doc_h.hospital_id == Doctor.hospital_id)
        .join(rec_h, rec_h.hospital_id == MedicalInformation.hospital_id)
        .where(MedicalInformation.hospital_id != Doctor.hospital_id)
        .order_by(AccessLog.accessed_at.desc())
    )
    if hid is not None:
        stmt = stmt.where(or_(Doctor.hospital_id == hid, MedicalInformation.hospital_id == hid))
    return paginate(db, stmt, page, 20, scalars=False)


# ================================================================ audit

AUDIT_GROUPS = {"auth": "Sign-in", "patient": "Patients", "record": "Records", "consent": "Consent", "emergency": "Emergency",
                "admin": "Administration", "backup": "Backups", "contact": "Contact"}


def _audit_query(cu: CurrentUser, *, action: str | None, user_q: str | None, date_from: datetime | None, date_to: datetime | None, q: str | None) -> Select:
    hid = _scope(cu)
    stmt = select(AuditLog, User.full_name, User.email).outerjoin(User, User.user_id == AuditLog.user_id)
    if hid is not None:
        stmt = stmt.where(or_(AuditLog.hospital_id == hid, AuditLog.user_id.in_(
            select(Doctor.user_id).where(Doctor.hospital_id == hid).union(
                select(HealthcareStaff.user_id).where(HealthcareStaff.hospital_id == hid),
                select(HospitalAdmin.user_id).where(HospitalAdmin.hospital_id == hid)))))
    if action and re.fullmatch(r"[a-z_.]{2,60}", action):
        stmt = stmt.where(AuditLog.action.like(action.replace("_", "\\_") + "%"))
    if user_q:
        esc = user_q.strip()[:80].replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(or_(User.full_name.like(f"%{esc}%"), User.email.like(f"%{esc}%")))
    if q:
        esc = q.strip()[:80].replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(or_(AuditLog.action.like(f"%{esc}%"), AuditLog.entity.like(f"%{esc}%"), AuditLog.entity_id == q.strip()[:50], AuditLog.ip_address == q.strip()[:45]))
    if date_from:
        stmt = stmt.where(AuditLog.timestamp >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.timestamp < date_to + timedelta(days=1))
    return stmt.order_by(AuditLog.timestamp.desc(), AuditLog.audit_id.desc())


def list_audit(db: Session, cu: CurrentUser, *, page: int, per_page: int = 25, **filters: Any) -> Page:
    return paginate(db, _audit_query(cu, **filters), page, per_page, scalars=False)


def export_audit_csv(db: Session, cu: CurrentUser, ip: str, **filters: Any) -> Iterator[str]:
    """Streams CSV in chunks (server-side cursor batches), capped at 50k rows."""
    audit(db, action="admin.audit_exported", entity="audit_log", user_id=cu.id, ip=ip, hospital_id=_scope(cu),
          details={k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in filters.items() if v})
    db.commit()
    stmt = _audit_query(cu, **filters).limit(50_000).execution_options(yield_per=1000)

    def gen() -> Iterator[str]:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["audit_id", "timestamp_utc", "user", "email", "action", "entity", "entity_id", "ip_address", "hospital_id", "details"])
        yield buf.getvalue()
        for i, (a, name, email) in enumerate(db.execute(stmt)):
            buf.seek(0)
            buf.truncate()
            # Prefix cells that could be read as formulas by spreadsheet apps (CSV injection).
            row = [a.audit_id, a.timestamp.isoformat(), name or "", email or "", a.action, a.entity, a.entity_id or "", a.ip_address or "",
                   a.hospital_id or "", "" if a.details is None else str(a.details)]
            w.writerow(["'" + c if isinstance(c, str) and c[:1] in ("=", "+", "-", "@", "\t", "\r") else c for c in row])
            yield buf.getvalue()

    return gen()


# ================================================================ dashboard

@dataclass
class AdminDashboard:
    scope_name: str
    hospitals: int
    doctors: int
    staff: int
    patients: int | None
    pending_doctors: int
    active_consents: int
    pending_requests: int
    emergency_7d: int
    active_emergencies: int
    audit_today: int
    failed_logins_24h: int
    access_by_day: list[tuple[str, int]]
    recent_emergencies: list[EmergencyAccess]


def dashboard(db: Session, cu: CurrentUser) -> AdminDashboard:
    hid = _scope(cu)
    now = utcnow()
    # Aggregate, non-PHI counters are cached briefly per scope (explicitly invalidated on hospital changes).
    key = f"admin:dash:{hid or 'all'}"

    def load() -> dict[str, Any]:
        def cnt(stmt) -> int:
            return int(db.scalar(stmt) or 0)
        doc_f = Doctor.hospital_id == hid if hid else True
        st_f = HealthcareStaff.hospital_id == hid if hid else True
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week = now - timedelta(days=7)
        by_day_stmt = select(func.date(AccessLog.accessed_at), func.count()).where(AccessLog.accessed_at >= now - timedelta(days=6, hours=now.hour))
        if hid:
            by_day_stmt = by_day_stmt.where(AccessLog.user_id.in_(select(Doctor.user_id).where(Doctor.hospital_id == hid).union(select(HealthcareStaff.user_id).where(HealthcareStaff.hospital_id == hid))))
        by_day = {str(d): int(c) for d, c in db.execute(by_day_stmt.group_by(func.date(AccessLog.accessed_at)))}
        days = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
        em_f = EmergencyAccess.hospital_id == hid if hid else True
        return {
            "hospitals": cnt(select(func.count()).select_from(Hospital).where(Hospital.hospital_id == hid if hid else True)),
            "doctors": cnt(select(func.count()).select_from(Doctor).where(doc_f)),
            "staff": cnt(select(func.count()).select_from(HealthcareStaff).where(st_f)),
            "patients": None if hid else cnt(select(func.count()).select_from(Patient)),
            "pending_doctors": cnt(select(func.count()).select_from(Doctor).where(doc_f, Doctor.verification_status == VerificationStatus.PENDING)),
            "active_consents": cnt(select(func.count()).select_from(Consent).where(Consent.status == ConsentStatus.ACTIVE, Consent.expires_at > now,
                                                                                    Consent.doctor_id.in_(_doctor_ids_of(hid)) if hid else True)),
            "pending_requests": cnt(select(func.count()).select_from(AccessRequest).where(AccessRequest.status == AccessRequestStatus.PENDING,
                                                                                           AccessRequest.doctor_id.in_(_doctor_ids_of(hid)) if hid else True)),
            "emergency_7d": cnt(select(func.count()).select_from(EmergencyAccess).where(em_f, EmergencyAccess.accessed_at >= week)),
            "active_emergencies": cnt(select(func.count()).select_from(EmergencyAccess).where(em_f, EmergencyAccess.expires_at > now, EmergencyAccess.ended_at.is_(None))),
            "audit_today": cnt(select(func.count()).select_from(AuditLog).where(AuditLog.timestamp >= day0, AuditLog.hospital_id == hid if hid else True)),
            "failed_logins_24h": cnt(select(func.count()).select_from(AuditLog).where(AuditLog.action == "auth.login_failed", AuditLog.timestamp >= now - timedelta(hours=24))) if not hid else 0,
            "access_by_day": [(d.strftime("%a"), by_day.get(str(d), 0)) for d in days],
        }

    data = cache.cached(key, 30, load)
    recent = list_emergencies(db, cu, page=1).items[:5]
    scope_name = "All hospitals" if hid is None else (db.get(Hospital, hid).name if db.get(Hospital, hid) else "")
    return AdminDashboard(scope_name=scope_name, recent_emergencies=recent, access_by_day=[tuple(x) for x in data["access_by_day"]],
                          **{k: v for k, v in data.items() if k != "access_by_day"})


# ================================================================ system

def system_health(db: Session) -> dict[str, Any]:
    import shutil
    import time

    from app.config import settings
    from app.database import engine
    from app.services.common.kvstore import kv

    t0 = time.perf_counter()
    db.execute(select(1))
    db_ms = (time.perf_counter() - t0) * 1000
    version = db.execute(select(func.version())).scalar()
    pool = engine.pool
    disk = shutil.disk_usage(settings.upload_dir if settings.upload_dir.exists() else ".")

    def dir_size(p) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0

    from alembic.migration import MigrationContext

    rev = MigrationContext.configure(db.connection()).get_current_revision()
    return {
        "db_ok": True, "db_ms": round(db_ms, 1), "db_version": version, "migration": rev,
        "pool": {"size": pool.size(), "checked_out": pool.checkedout(), "overflow": pool.overflow()} if hasattr(pool, "size") else {},
        "redis": "connected" if settings.redis_url and kv.ping() and not settings.is_test else "in-memory fallback",
        "disk_free_gb": round(disk.free / 1e9, 1), "disk_total_gb": round(disk.total / 1e9, 1),
        "uploads_mb": round(dir_size(settings.upload_dir) / 1e6, 2), "backups_mb": round(dir_size(settings.backup_dir) / 1e6, 2),
        "env": settings.app_env, "sms": settings.sms_provider,
        "counts": {name: int(db.scalar(select(func.count()).select_from(m)) or 0) for name, m in
                   (("users", User), ("patients", Patient), ("records", MedicalInformation), ("access_log", AccessLog), ("audit_log", AuditLog))},
    }


SETTING_RULES: dict[str, tuple[str, Any]] = {
    "maintenance_banner": ("text", 200),
    "allow_patient_registration": ("bool", None),
    "allow_doctor_registration": ("bool", None),
    "consent_default_hours": ("int", (1, 168)),
    "emergency_access_minutes": ("int", (5, 240)),
}


def update_settings(db: Session, cu: CurrentUser, values: dict[str, str], ip: str) -> list[str]:
    errors: dict[str, str] = {}
    changed: list[str] = []
    rows = {s.setting_key: s for s in db.scalars(select(SystemSetting))}
    for key, raw in values.items():
        if key not in SETTING_RULES or key not in rows:
            errors[key] = "Unknown setting."
            continue
        kind, rule = SETTING_RULES[key]
        v = (raw or "").strip()
        if kind == "bool":
            if v not in ("true", "false"):
                errors[key] = "Choose on or off."
                continue
        elif kind == "int":
            if not v.isdigit() or not (rule[0] <= int(v) <= rule[1]):
                errors[key] = f"Enter a number from {rule[0]} to {rule[1]}."
                continue
        elif len(v) > rule:
            errors[key] = f"Keep it under {rule} characters."
            continue
        if rows[key].setting_value != v:
            rows[key].setting_value = v
            rows[key].updated_by_user_id = cu.id
            changed.append(key)
    if errors:
        db.rollback()
        raise AdminError(next(iter(errors.values())), 422, errors)
    if changed:
        audit(db, action="admin.settings_changed", entity="system_setting", user_id=cu.id, ip=ip, details={"keys": changed})
    db.commit()
    system_settings.invalidate()
    return changed

