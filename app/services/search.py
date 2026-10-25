"""Role-aware global search. Returns only what the current user may see:

* everyone: pages they can open (by permission) + FAQ/help
* patients: their OWN records (title match)
* clinicians: a patient by EXACT, checksum-valid UPI only (no name / partial search,
  no record contents) - the result just links to the patient page, where access rules apply
* admins: users / hospitals within their scope (hospital admins: own hospital only)
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.middleware.auth import CurrentUser
from app.models import Doctor, HealthcareStaff, Hospital, HospitalAdmin, MedicalInformation, Patient, User
from app.models.enums import RecordStatus
from app.services.common.permissions import P
from app.services.common.security import normalize_upi
from app.services.content import FAQ, HELP

Item = dict[str, str]

# (title, url, required permission or None, portal prefix)
PAGES: list[tuple[str, str, str | None, str]] = [
    ("Patient overview", "/patient", P.OWN_RECORDS_READ, "patient"),
    ("My records", "/patient/records", P.OWN_RECORDS_READ, "patient"),
    ("Upload a document", "/patient/records/new", P.OWN_RECORDS_UPLOAD, "patient"),
    ("Access requests and consent", "/patient/consent", P.OWN_CONSENT, "patient"),
    ("Access history", "/patient/access-history", P.OWN_ACCESS_HISTORY, "patient"),
    ("Profile and password", "/patient/profile", P.OWN_PROFILE, "patient"),
    ("Clinician overview", "/doctor", P.PROVIDER_PROFILE, "doctor"),
    ("Find a patient by UPI", "/doctor/search", P.PATIENT_SEARCH, "doctor"),
    ("My access requests", "/doctor/requests", P.ACCESS_REQUEST, "doctor"),
    ("Emergency access log", "/doctor/emergency", P.EMERGENCY_ACCESS, "doctor"),
    ("Profile and password", "/doctor/profile", P.PROVIDER_PROFILE, "doctor"),
    ("Admin overview", "/admin", P.ADMIN_DASHBOARD, "admin"),
    ("Hospitals", "/admin/hospitals", P.HOSPITAL_MANAGE, "admin"),
    ("Users, doctors and staff", "/admin/users", P.USER_MANAGE, "admin"),
    ("Create a doctor account", "/admin/users?new=doctor", P.USER_MANAGE, "admin"),
    ("Roles and permissions", "/admin/roles", P.ROLE_MANAGE, "admin"),
    ("Consent and access monitoring", "/admin/access", P.CONSENT_MONITOR, "admin"),
    ("Emergency access oversight", "/admin/emergency", P.EMERGENCY_MONITOR, "admin"),
    ("Audit log", "/admin/audit", P.AUDIT_READ, "admin"),
    ("System health and settings", "/admin/system", P.SYSTEM_MONITOR, "admin"),
    ("Backups", "/admin/backups", P.BACKUP_MANAGE, "admin"),
]
PUBLIC_PAGES: list[Item] = [
    {"title": "Help centre", "url": "/help"},
    {"title": "Privacy notice", "url": "/privacy"},
]


def _match(q: str, *texts: str) -> bool:
    ql = q.lower()
    return any(ql in (t or "").lower() for t in texts)


def _like(q: str) -> str:
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def search(db: Session, cu: CurrentUser | None, q: str, limit: int = 6) -> list[dict[str, Any]]:
    q = (q or "").strip()[:80]
    groups: list[dict[str, Any]] = []
    if len(q) < 2:
        return groups

    if cu is not None:
        # Patient lookup by exact UPI (clinicians only) - checked first so it tops the list.
        if cu.can(P.PATIENT_SEARCH):
            upi = normalize_upi(q)
            if upi and db.scalar(select(Patient.patient_id).where(Patient.upi == upi)):
                groups.append({"label": "Patient", "items": [{"title": f"Open patient {upi}", "subtitle": "Access rules apply on the patient page", "url": f"/doctor/patients/{upi}"}]})

        pages = [{"title": t, "url": u} for t, u, perm, _ in PAGES if (perm is None or cu.can(perm)) and _match(q, t)]
        if pages:
            groups.append({"label": "Pages", "items": pages[:limit]})

        if cu.patient is not None and cu.can(P.OWN_RECORDS_READ):
            rows = db.execute(
                select(MedicalInformation.information_id, MedicalInformation.title, MedicalInformation.information_type, MedicalInformation.information_date)
                .where(MedicalInformation.patient_id == cu.patient.patient_id, MedicalInformation.status == RecordStatus.ACTIVE,
                       MedicalInformation.title.like(_like(q)))
                .order_by(MedicalInformation.information_date.desc()).limit(limit)
            ).all()
            if rows:
                groups.append({"label": "My records", "items": [
                    {"title": r.title, "subtitle": f"{r.information_type.value.replace('_', ' ').capitalize()} · {r.information_date:%d %b %Y}", "url": f"/patient/records/{r.information_id}"}
                    for r in rows]})

        if cu.can(P.USER_MANAGE):
            stmt = select(User).where(or_(User.full_name.like(_like(q)), User.email.like(_like(q)), User.username.like(_like(q))))
            if not cu.is_system_admin:
                hid = cu.hospital_id
                stmt = stmt.where(or_(
                    User.user_id.in_(select(Doctor.user_id).where(Doctor.hospital_id == hid)),
                    User.user_id.in_(select(HealthcareStaff.user_id).where(HealthcareStaff.hospital_id == hid)),
                    User.user_id.in_(select(HospitalAdmin.user_id).where(HospitalAdmin.hospital_id == hid)),
                ))
            users = list(db.scalars(stmt.order_by(User.full_name).limit(limit)))
            if users:
                groups.append({"label": "Users", "items": [{"title": u.full_name, "subtitle": u.email, "url": f"/admin/users/{u.user_id}"} for u in users]})

        if cu.can(P.HOSPITAL_MANAGE_ALL):
            hs = list(db.scalars(select(Hospital).where(or_(Hospital.name.like(_like(q)), Hospital.registration_number.like(_like(q)))).limit(limit)))
            if hs:
                groups.append({"label": "Hospitals", "items": [{"title": h.name, "subtitle": h.registration_number, "url": f"/admin/hospitals/{h.hospital_id}"} for h in hs]})
    else:
        pages = [p for p in PUBLIC_PAGES if _match(q, p["title"])]
        if pages:
            groups.append({"label": "Pages", "items": pages})

    help_items = [{"title": h["title"], "subtitle": "Help", "url": f"/help#{h['id']}"} for h in HELP if _match(q, h["title"], h["body"])]
    faq_items = [{"title": qq, "subtitle": "FAQ", "url": f"/help#faq-{i}"} for i, (qq, a) in enumerate(FAQ) if _match(q, qq, a)]
    if help_items or faq_items:
        groups.append({"label": "Help", "items": (help_items + faq_items)[:limit]})
    return groups


def count_results(groups: list[dict[str, Any]]) -> int:
    return sum(len(g["items"]) for g in groups)

