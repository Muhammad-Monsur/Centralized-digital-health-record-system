"""Authentication + RBAC as FastAPI dependencies.

Why dependencies and not a global middleware: each route declares *which*
permission it needs right next to its definition, FastAPI documents it in
OpenAPI, and a route can't be added without thinking about access. Every route
except the public pages depends on ``require_user`` / ``require_permissions``.
RBAC is evaluated on the server on every request; the UI only hides buttons.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Depends, Request
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.models import Doctor, HealthcareStaff, HospitalAdmin, Patient, User
from app.models.enums import HospitalStatus, RoleStatus, UserStatus, VerificationStatus
from app.services.common.permissions import PORTAL_BY_ROLE, P, login_path_for_roles
from app.services.common.session import session_ref


class LoginRequired(Exception):
    """Raised when no valid session exists (pages redirect, API returns 401)."""


class PasswordChangeRequired(Exception):
    """The user must replace an administrator-set password before doing anything else."""


# Routes still reachable while a password change is pending.
PASSWORD_CHANGE_ALLOWED = ("/account/change-password", "/api/v1/auth/password", "/api/v1/auth/logout", "/api/v1/session/")


class Forbidden(Exception):
    def __init__(self, message: str = "You don't have permission to do that.") -> None:
        super().__init__(message)
        self.message = message


# Clinical permissions require a verified doctor / active staff at an active hospital.
_CLINICAL = {
    P.PATIENT_SEARCH, P.RECORDS_PUBLIC_READ, P.RECORDS_PRIVATE_READ, P.RECORDS_CREATE,
    P.RECORDS_UPDATE, P.ACCESS_REQUEST, P.EMERGENCY_ACCESS,
}


@dataclass
class CurrentUser:
    user: User
    permissions: frozenset[str]
    roles: frozenset[str]
    patient: Patient | None = None
    doctor: Doctor | None = None
    staff: HealthcareStaff | None = None
    hospital_admin: HospitalAdmin | None = None
    is_system_admin: bool = False
    notes: list[str] = field(default_factory=list)
    # Reference to the current sign-in session; consent and emergency access are bound to it.
    session_ref: str | None = None

    @property
    def id(self) -> int:
        return self.user.user_id

    def can(self, *perms: str) -> bool:
        return all(p in self.permissions for p in perms)

    @property
    def hospital_id(self) -> int | None:
        """The hospital this user acts for (None = patient or system admin)."""
        if self.doctor:
            return self.doctor.hospital_id
        if self.staff:
            return self.staff.hospital_id
        if self.hospital_admin:
            return self.hospital_admin.hospital_id
        return None

    @property
    def portal(self) -> str:
        for role, path in PORTAL_BY_ROLE:
            if role in self.roles:
                return path
        return "/"

    @property
    def login_path(self) -> str:
        return login_path_for_roles(self.roles)

    @property
    def is_clinician(self) -> bool:
        return self.doctor is not None or self.staff is not None


def load_current_user(db: Session, user_id: int) -> CurrentUser | None:
    user = db.get(
        User, user_id,
        options=[selectinload(User.roles), joinedload(User.patient), joinedload(User.doctor), joinedload(User.staff),
                 joinedload(User.hospital_admin), joinedload(User.system_admin)],
    )
    if user is None or user.status not in (UserStatus.ACTIVE, UserStatus.PENDING):
        return None

    roles: set[str] = set()
    perms: set[str] = set()
    for ur in user.roles:
        if ur.role.status != RoleStatus.ACTIVE:
            continue
        roles.add(ur.role.role_name)
        perms.update(rp.permission.permission_name for rp in ur.role.permissions)

    cu = CurrentUser(
        user=user, permissions=frozenset(), roles=frozenset(roles),
        patient=user.patient, doctor=user.doctor, staff=user.staff,
        hospital_admin=user.hospital_admin, is_system_admin=user.system_admin is not None,
    )
    # Scope checks that RBAC alone cannot express:
    if user.status == UserStatus.PENDING:
        perms -= _CLINICAL
        cu.notes.append("account_pending")
    if user.doctor and user.doctor.verification_status != VerificationStatus.VERIFIED:
        perms -= _CLINICAL
        cu.notes.append(f"doctor_{user.doctor.verification_status.value}")
    clinic = user.doctor or user.staff
    if clinic and clinic.hospital.status != HospitalStatus.ACTIVE:
        perms -= _CLINICAL
        cu.notes.append("hospital_inactive")
    if not (user.doctor or user.staff):
        perms -= _CLINICAL  # a clinical permission without a hospital link is meaningless
    if not user.patient:
        perms -= {p for p in perms if p.startswith("patient.")}
    if user.hospital_admin and user.hospital_admin.hospital.status != HospitalStatus.ACTIVE and not cu.is_system_admin:
        perms -= {p for p in perms if p.startswith("admin.")}
        cu.notes.append("hospital_inactive")
    cu.permissions = frozenset(perms)
    return cu


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser | None:
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached
    session = getattr(request.state, "session", None)
    if session is None:
        return None
    cu = load_current_user(db, session.user_id)
    if cu is not None:
        cu.session_ref = session_ref(getattr(request.state, "sid", None))
    request.state.current_user = cu
    return cu


def require_user(request: Request, user: CurrentUser | None = Depends(get_optional_user)) -> CurrentUser:
    if user is None:
        raise LoginRequired()
    if user.user.must_change_password and not request.url.path.startswith(PASSWORD_CHANGE_ALLOWED):
        raise PasswordChangeRequired()
    return user


def require_permissions(*perms: str) -> Callable[..., CurrentUser]:
    """Dependency factory: ``Depends(require_permissions(P.X, P.Y))`` (all required)."""

    def _dep(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        if not user.can(*perms):
            raise Forbidden()
        return user

    _dep.__name__ = "require_" + "_".join(p.replace(".", "_") for p in perms)
    return _dep


def require_any_permission(*perms: str) -> Callable[..., CurrentUser]:
    def _dep(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        if not any(user.can(p) for p in perms):
            raise Forbidden()
        return user

    return _dep
