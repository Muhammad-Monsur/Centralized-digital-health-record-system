"""Permission catalogue and default role -> permission mapping (seeded into the RBAC tables).

Routes check *permissions*, never role names, so an admin can re-shape roles in the
RBAC editor without code changes. Ownership / hospital scoping is enforced separately
in the service layer.
"""
from __future__ import annotations

from app.models.enums import RoleName


class P:
    """Permission name constants (use these in code, never raw strings)."""

    # Patient (own data only)
    OWN_PROFILE = "patient.profile.manage"
    OWN_RECORDS_READ = "patient.records.read"
    OWN_RECORDS_UPLOAD = "patient.records.upload"
    OWN_RECORDS_VISIBILITY = "patient.records.visibility"
    OWN_CONSENT = "patient.consent.manage"
    OWN_ACCESS_HISTORY = "patient.access_history.read"

    # Clinical
    PROVIDER_PROFILE = "provider.profile.manage"
    PATIENT_SEARCH = "clinical.patient.search"
    RECORDS_PUBLIC_READ = "clinical.records.read_public"
    RECORDS_PRIVATE_READ = "clinical.records.read_private"  # still needs consent / emergency
    RECORDS_CREATE = "clinical.records.create"
    RECORDS_UPDATE = "clinical.records.update"
    ACCESS_REQUEST = "clinical.access.request"
    EMERGENCY_ACCESS = "clinical.access.emergency"

    # Administration
    ADMIN_DASHBOARD = "admin.dashboard.view"
    HOSPITAL_MANAGE = "admin.hospital.manage"
    HOSPITAL_MANAGE_ALL = "admin.hospital.manage_all"
    USER_MANAGE = "admin.user.manage"
    DOCTOR_VERIFY = "admin.doctor.verify"
    ROLE_MANAGE = "admin.role.manage"
    CONSENT_MONITOR = "admin.consent.monitor"
    EMERGENCY_MONITOR = "admin.emergency.monitor"
    AUDIT_READ = "admin.audit.read"
    AUDIT_EXPORT = "admin.audit.export"
    SYSTEM_MONITOR = "admin.system.monitor"
    SYSTEM_CONFIG = "admin.system.config"
    BACKUP_MANAGE = "admin.backup.manage"


PERMISSION_DESCRIPTIONS: dict[str, str] = {
    P.OWN_PROFILE: "View and update own patient profile",
    P.OWN_RECORDS_READ: "View own medical records",
    P.OWN_RECORDS_UPLOAD: "Upload documents to own record",
    P.OWN_RECORDS_VISIBILITY: "Set own records public or private",
    P.OWN_CONSENT: "Approve, reject and revoke access requests",
    P.OWN_ACCESS_HISTORY: "See who accessed own records",
    P.PROVIDER_PROFILE: "Manage own provider profile",
    P.PATIENT_SEARCH: "Find a patient by UPI",
    P.RECORDS_PUBLIC_READ: "Read a patient's public records",
    P.RECORDS_PRIVATE_READ: "Read private records under consent or emergency access",
    P.RECORDS_CREATE: "Create medical records",
    P.RECORDS_UPDATE: "Update medical records the user's hospital created",
    P.ACCESS_REQUEST: "Request consent for private records",
    P.EMERGENCY_ACCESS: "Invoke emergency access (logged, patient notified)",
    P.ADMIN_DASHBOARD: "Open the admin portal",
    P.HOSPITAL_MANAGE: "Manage own hospital's details and users",
    P.HOSPITAL_MANAGE_ALL: "Create and manage every hospital",
    P.USER_MANAGE: "Activate, deactivate and edit users",
    P.DOCTOR_VERIFY: "Verify or reject doctor licences",
    P.ROLE_MANAGE: "Edit roles and permissions",
    P.CONSENT_MONITOR: "Monitor consents and access requests",
    P.EMERGENCY_MONITOR: "Oversee emergency and inter-hospital access",
    P.AUDIT_READ: "Read audit logs",
    P.AUDIT_EXPORT: "Export audit logs",
    P.SYSTEM_MONITOR: "View system health",
    P.SYSTEM_CONFIG: "Change system configuration",
    P.BACKUP_MANAGE: "Create, list and restore backups",
}

_PATIENT = [P.OWN_PROFILE, P.OWN_RECORDS_READ, P.OWN_RECORDS_UPLOAD, P.OWN_RECORDS_VISIBILITY, P.OWN_CONSENT, P.OWN_ACCESS_HISTORY]
_DOCTOR = [
    P.PROVIDER_PROFILE, P.PATIENT_SEARCH, P.RECORDS_PUBLIC_READ, P.RECORDS_PRIVATE_READ,
    P.RECORDS_CREATE, P.RECORDS_UPDATE, P.ACCESS_REQUEST, P.EMERGENCY_ACCESS,
]
# Staff (nurses, lab technicians): find patients, read public data, add records
# (e.g. lab results). No private access, no consent requests, no emergency override.
_STAFF = [P.PROVIDER_PROFILE, P.PATIENT_SEARCH, P.RECORDS_PUBLIC_READ, P.RECORDS_CREATE]
_HOSPITAL_ADMIN = [
    P.ADMIN_DASHBOARD, P.HOSPITAL_MANAGE, P.USER_MANAGE, P.DOCTOR_VERIFY, P.CONSENT_MONITOR,
    P.EMERGENCY_MONITOR, P.AUDIT_READ, P.AUDIT_EXPORT,
]
_SYSTEM_ADMIN = sorted(set(_HOSPITAL_ADMIN) | {
    P.HOSPITAL_MANAGE_ALL, P.ROLE_MANAGE, P.SYSTEM_MONITOR, P.SYSTEM_CONFIG, P.BACKUP_MANAGE,
})

DEFAULT_ROLES: dict[str, tuple[str, list[str]]] = {
    RoleName.PATIENT.value: ("Patient: owns and controls their health records", _PATIENT),
    RoleName.DOCTOR.value: ("Doctor: verified clinician with consent-based access", _DOCTOR),
    RoleName.STAFF.value: ("Healthcare staff: limited clinical permissions", _STAFF),
    RoleName.HOSPITAL_ADMIN.value: ("Hospital administrator: manages one hospital", _HOSPITAL_ADMIN),
    RoleName.SYSTEM_ADMIN.value: ("System administrator: system-wide management", _SYSTEM_ADMIN),
}

# Which portal a role lands on after login (first match wins).
PORTAL_BY_ROLE: list[tuple[str, str]] = [
    (RoleName.SYSTEM_ADMIN.value, "/admin"),
    (RoleName.HOSPITAL_ADMIN.value, "/admin"),
    (RoleName.DOCTOR.value, "/doctor"),
    (RoleName.STAFF.value, "/doctor"),
    (RoleName.PATIENT.value, "/patient"),
]


# Role-specific sign-in pages. A user can only sign in through the portal of one of
# their roles; anything else gets the generic "wrong username or password" answer.
LOGIN_PORTALS: dict[str, dict[str, object]] = {
    "patient": {
        "path": "/login", "roles": {RoleName.PATIENT.value}, "title": "Patient sign-in",
        "intro": "Sign in to see your records and control who can view them.",
    },
    "doctor": {
        "path": "/doctor/login", "roles": {RoleName.DOCTOR.value, RoleName.STAFF.value}, "title": "Doctor sign-in",
        "intro": "For doctors and healthcare staff. Your account is created by your hospital administrator.",
    },
    "hospital-admin": {
        "path": "/hospital-admin/login", "roles": {RoleName.HOSPITAL_ADMIN.value}, "title": "Hospital admin sign-in",
        "intro": "Manage your hospital, its doctors and staff.",
    },
    "system-admin": {
        "path": "/system-admin/login", "roles": {RoleName.SYSTEM_ADMIN.value}, "title": "System admin sign-in",
        "intro": "System-wide administration of CDHRS.",
    },
}


def login_path_for_roles(roles: set[str] | frozenset[str]) -> str:
    for key in ("system-admin", "hospital-admin", "doctor", "patient"):
        if roles & LOGIN_PORTALS[key]["roles"]:  # type: ignore[operator]
            return str(LOGIN_PORTALS[key]["path"])
    return "/login"


def login_path_for_url(path: str) -> str:
    """Where to send an anonymous visitor who tried to open ``path``."""
    if path.startswith("/doctor"):
        return "/doctor/login"
    if path.startswith("/admin"):
        return "/admin/login"  # small chooser: hospital admin or system admin
    return "/login"
