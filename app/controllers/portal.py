"""Shared helpers for the three portals: sidebar navigation, shell context, file responses."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.middleware.auth import CurrentUser
from app.models import MedicalInformation
from app.models.enums import RoleName
from app.services.common import file as file_service
from app.services.common import notification, system_settings
from app.services.common.permissions import P
from app.views import render

NavItem = tuple[str, str, str, int]  # href, icon, label, badge count


def patient_nav(counts: dict[str, int]) -> list[tuple[str, list[NavItem]]]:
    return [
        ("", [("/patient", "grid", "Overview", 0), ("/patient/records", "file", "My records", 0),
              ("/patient/records/new", "upload", "Upload a document", 0)]),
        ("Privacy", [("/patient/consent", "key", "Access requests", counts.get("pending", 0)),
                     ("/patient/access-history", "history", "Access history", 0)]),
        ("Account", [("/patient/profile", "user", "Profile & security", 0),
                     ("/patient/notifications", "bell", "Notifications", counts.get("unread", 0))]),
    ]


def doctor_nav(cu: CurrentUser, counts: dict[str, int]) -> list[tuple[str, list[NavItem]]]:
    clinical: list[NavItem] = [("/doctor", "grid", "Overview", 0)]
    if cu.can(P.PATIENT_SEARCH):
        clinical.append(("/doctor/search", "search", "Find a patient", 0))
    if cu.can(P.ACCESS_REQUEST):
        clinical.append(("/doctor/requests", "key", "My access requests", 0))
    if cu.can(P.EMERGENCY_ACCESS):
        clinical.append(("/doctor/emergency", "siren", "Emergency access log", 0))
    return [("", clinical),
            ("Account", [("/doctor/profile", "user", "Profile & security", 0),
                         ("/doctor/notifications", "bell", "Notifications", counts.get("unread", 0))])]


def admin_nav(cu: CurrentUser, counts: dict[str, int]) -> list[tuple[str, list[NavItem]]]:
    manage: list[NavItem] = [("/admin", "grid", "Overview", 0)]
    if cu.can(P.HOSPITAL_MANAGE):
        manage.append(("/admin/hospitals", "hospital", "Hospitals", 0))
    if cu.can(P.USER_MANAGE):
        manage.append(("/admin/users", "users", "Users", counts.get("pending_doctors", 0)))
    if cu.can(P.ROLE_MANAGE):
        manage.append(("/admin/roles", "shield", "Roles & permissions", 0))
    oversight: list[NavItem] = []
    if cu.can(P.CONSENT_MONITOR):
        oversight.append(("/admin/access", "key", "Consent & access", 0))
    if cu.can(P.EMERGENCY_MONITOR):
        oversight.append(("/admin/emergency", "siren", "Emergency access", counts.get("emergency_24h", 0)))
    if cu.can(P.AUDIT_READ):
        oversight.append(("/admin/audit", "clipboard", "Audit log", 0))
    system: list[NavItem] = []
    if cu.can(P.SYSTEM_MONITOR):
        system.append(("/admin/system", "activity", "System & settings", 0))
    if cu.can(P.BACKUP_MANAGE):
        system.append(("/admin/backups", "database", "Backups", 0))
    groups = [("", manage), ("Oversight", oversight), ("System", system),
              ("Account", [("/admin/profile", "user", "Profile & security", 0), ("/admin/notifications", "bell", "Notifications", counts.get("unread", 0))])]
    return [g for g in groups if g[1]]


ROLE_LABELS = {
    RoleName.PATIENT.value: "Patient", RoleName.DOCTOR.value: "Doctor", RoleName.STAFF.value: "Healthcare staff",
    RoleName.HOSPITAL_ADMIN.value: "Hospital administrator", RoleName.SYSTEM_ADMIN.value: "System administrator",
}


def role_label(cu: CurrentUser) -> str:
    for r in (RoleName.SYSTEM_ADMIN, RoleName.HOSPITAL_ADMIN, RoleName.DOCTOR, RoleName.STAFF, RoleName.PATIENT):
        if r.value in cu.roles:
            return ROLE_LABELS[r.value]
    return "User"


def render_portal(request: Request, db: Session, cu: CurrentUser, template: str, ctx: dict[str, Any], *, kind: str, counts: dict[str, int] | None = None, status_code: int = 200):
    counts = dict(counts or {})
    counts["unread"] = notification.unread_count(db, cu.id)
    if kind == "patient":
        nav, label, placeholder = patient_nav(counts), "Patient portal", "Search your records, pages and help"
    elif kind == "doctor":
        nav, label, placeholder = doctor_nav(cu, counts), "Clinician portal", "Enter a patient UPI, or search pages and help"
    else:
        nav, label, placeholder = admin_nav(cu, counts), "Admin portal", "Search users, hospitals, pages and help"
    base = {"nav": nav, "portal_label": label, "role_label": role_label(cu), "unread_count": counts["unread"],
            "system_banner": system_settings.get(db, "maintenance_banner"), "search_placeholder": placeholder, "cu": cu}
    base.update(ctx)
    return render(request, template, base, status_code=status_code)


def file_response(info: MedicalInformation, inline: bool) -> FileResponse:
    """Serve a stored document. Never cacheable; inline views are sandboxed (no scripts)."""
    path = file_service.resolve(info.file_path or "")
    # Images may open in the tab (sandboxed). PDFs always download: browsers refuse to render
    # PDFs under a sandbox CSP, and we won't serve them inline without one.
    disp_type = "inline" if inline and info.file_mime in ("image/png", "image/jpeg", "image/webp") else "attachment"
    resp = FileResponse(path, media_type=info.file_mime or "application/octet-stream", filename=info.file_original_name or path.name,
                        content_disposition_type=disp_type)
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp
