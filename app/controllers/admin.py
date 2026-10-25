"""Admin portal controller (hospital admin + system admin; scope enforced in the service)."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.controllers.patient import _err
from app.controllers.portal import render_portal
from app.database import get_db
from app.middleware.auth import CurrentUser, require_permissions
from app.middleware.rate_limit import client_ip
from app.models import Hospital, SystemSetting
from app.models.enums import HospitalStatus, RoleName
from app.schemas.admin import (
    AccountCreateIn,
    AccountUpdateIn,
    HospitalIn,
    HospitalStatusIn,
    HospitalUpdateIn,
    ResetPasswordIn,
    RestoreIn,
    RoleIn,
    RolePermissionsIn,
    RoleStatusIn,
    SettingsIn,
    StatusIn,
    VerifyIn,
)
from app.services import admin as svc
from app.services import backup as backup_service
from app.services.common import notification
from app.services.common.permissions import P
from app.services.common.security import utcnow
from app.views import render

pages = APIRouter(include_in_schema=False)
api = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ADMIN = require_permissions(P.ADMIN_DASHBOARD)


def _counts(db: Session, cu: CurrentUser) -> dict[str, int]:
    d = svc.dashboard(db, cu)
    return {"pending_doctors": d.pending_doctors, "emergency_24h": d.active_emergencies}


def _page(request: Request, db: Session, cu: CurrentUser, template: str, ctx: dict, status_code: int = 200):
    return render_portal(request, db, cu, template, {"is_sys": cu.is_system_admin, **ctx}, kind="admin", counts=_counts(db, cu), status_code=status_code)


def _not_found(request: Request, e: svc.AdminError):
    return render(request, "errors/404.html", {"title": "Not found", "message": e.message}, status_code=404)


def _hospital_options(db: Session, cu: CurrentUser) -> list[Hospital]:
    stmt = select(Hospital).where(Hospital.status == HospitalStatus.ACTIVE).order_by(Hospital.name)
    if not cu.is_system_admin:
        stmt = stmt.where(Hospital.hospital_id == cu.hospital_id)
    return list(db.scalars(stmt))


def _parse_date(v: str | None) -> datetime | None:
    try:
        return datetime.combine(date.fromisoformat(v), datetime.min.time()) if v else None
    except ValueError:
        return None


ROLE_FILTERS = [(RoleName.DOCTOR.value, "Doctors"), (RoleName.STAFF.value, "Staff"), (RoleName.HOSPITAL_ADMIN.value, "Hospital admins"), (RoleName.PATIENT.value, "Patients")]


# ================================================================ pages

@pages.get("/admin")
def dashboard(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(ADMIN)):
    d = svc.dashboard(db, cu)
    peak = max([c for _, c in d.access_by_day] + [1])
    return _page(request, db, cu, "admin/dashboard.html", {"d": d, "peak": peak, "now": utcnow()})


@pages.get("/admin/users")
def users_page(request: Request, page: int = Query(1, ge=1), role: str | None = None, status: str | None = None,
               q: str | None = Query(None, max_length=80), verification: str | None = None,
               db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.USER_MANAGE))):
    pg = svc.list_users(db, cu, role=role, status=status, q=q, verification=verification, page=page)
    filters = {"role": role or "", "status": status or "", "q": q or "", "verification": verification or ""}
    roles = ROLE_FILTERS if cu.is_system_admin else ROLE_FILTERS[:3]
    return _page(request, db, cu, "admin/users.html", {"page": pg, "filters": filters, "role_filters": roles,
                                                       "hospitals": _hospital_options(db, cu), "open_new": request.query_params.get("new", ""),
                                                       "now": utcnow()})


@pages.get("/admin/users/{user_id}")
def user_page(user_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.USER_MANAGE))):
    try:
        u = svc.get_user(db, cu, user_id)
    except svc.AdminError as e:
        return _not_found(request, e)
    manageable = True
    try:
        svc._assert_manageable(cu, u)
    except svc.AdminError:
        manageable = False
    return _page(request, db, cu, "admin/user.html", {"u": u, "manageable": manageable, "now": utcnow(), "can_verify": cu.can(P.DOCTOR_VERIFY)})


@pages.get("/admin/hospitals")
def hospitals_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.HOSPITAL_MANAGE))):
    return _page(request, db, cu, "admin/hospitals.html", {"rows": svc.list_hospitals(db, cu), "can_all": cu.can(P.HOSPITAL_MANAGE_ALL)})


@pages.get("/admin/hospitals/{hospital_id}")
def hospital_page(hospital_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.HOSPITAL_MANAGE))):
    try:
        h = svc.get_hospital(db, cu, hospital_id)
    except svc.AdminError as e:
        return _not_found(request, e)
    info = next((r for r in svc.list_hospitals(db, cu) if r["h"].hospital_id == hospital_id), None)
    return _page(request, db, cu, "admin/hospital.html", {"h": h, "info": info, "can_all": cu.can(P.HOSPITAL_MANAGE_ALL)})


@pages.get("/admin/roles")
def roles_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.ROLE_MANAGE))):
    from app.services.common.permissions import PERMISSION_DESCRIPTIONS

    return _page(request, db, cu, "admin/roles.html", {"m": svc.roles_matrix(db), "descriptions": PERMISSION_DESCRIPTIONS})


@pages.get("/admin/access")
def access_page(request: Request, page: int = Query(1, ge=1), status: str | None = None, db: Session = Depends(get_db),
                cu: CurrentUser = Depends(require_permissions(P.CONSENT_MONITOR))):
    pg = svc.list_consents(db, cu, status=status, page=page)
    return _page(request, db, cu, "admin/access.html", {"page": pg, "consents": svc.consent_map(db, [r.request_id for r in pg.items]),
                                                        "status": status or "", "now": utcnow()})


@pages.get("/admin/emergency")
def emergency_page(request: Request, page: int = Query(1, ge=1), tab: str = "emergency", active: bool = False,
                   db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.EMERGENCY_MONITOR))):
    if tab == "inter":
        pg = svc.inter_hospital_accesses(db, cu, page=page)
    else:
        pg = svc.list_emergencies(db, cu, page=page, active_only=active)
    return _page(request, db, cu, "admin/emergency.html", {"page": pg, "tab": tab, "active": active, "now": utcnow()})


@pages.get("/admin/audit")
def audit_page(request: Request, page: int = Query(1, ge=1), action: str | None = Query(None, max_length=60), user: str | None = Query(None, max_length=80),
               q: str | None = Query(None, max_length=80), date_from: str | None = None, date_to: str | None = None,
               db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.AUDIT_READ))):
    filters = {"action": action, "user_q": user, "q": q, "date_from": _parse_date(date_from), "date_to": _parse_date(date_to)}
    pg = svc.list_audit(db, cu, page=page, **filters)
    qs = request.url.query
    return _page(request, db, cu, "admin/audit.html", {"page": pg, "groups": svc.AUDIT_GROUPS, "can_export": cu.can(P.AUDIT_EXPORT),
                                                       "f": {"action": action or "", "user": user or "", "q": q or "", "date_from": date_from or "", "date_to": date_to or ""},
                                                       "qs": "&".join(p for p in qs.split("&") if p and not p.startswith("page="))})


@pages.get("/admin/audit/export.csv")
def audit_export(request: Request, action: str | None = Query(None, max_length=60), user: str | None = Query(None, max_length=80),
                 q: str | None = Query(None, max_length=80), date_from: str | None = None, date_to: str | None = None,
                 db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.AUDIT_EXPORT))):
    gen = svc.export_audit_csv(db, cu, client_ip(request), action=action, user_q=user, q=q, date_from=_parse_date(date_from), date_to=_parse_date(date_to))
    name = f"cdhrs-audit-{utcnow():%Y%m%d-%H%M}.csv"
    return StreamingResponse(gen, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


@pages.get("/admin/system")
def system_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.SYSTEM_MONITOR))):
    rows = {s.setting_key: s for s in db.scalars(select(SystemSetting))}
    return _page(request, db, cu, "admin/system.html", {"h": svc.system_health(db), "settings_rows": rows, "rules": svc.SETTING_RULES,
                                                        "can_config": cu.can(P.SYSTEM_CONFIG)})


@pages.get("/admin/backups")
def backups_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.BACKUP_MANAGE))):
    return _page(request, db, cu, "admin/backups.html", {"backups": backup_service.list_backups()})


@pages.get("/admin/profile")
def profile_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(ADMIN)):
    return _page(request, db, cu, "admin/profile.html", {"u": cu.user})


@pages.get("/admin/notifications")
def notifications_page(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db), cu: CurrentUser = Depends(ADMIN)):
    return _page(request, db, cu, "common/notifications.html", {"page": notification.list_for(db, cu.id, page), "base": "/admin"})


# ================================================================ API: users

def _wrap(fn):
    try:
        return fn()
    except svc.AdminError as e:
        return _err(e)


@api.post("/users", status_code=201, summary="Create a doctor, staff or hospital-admin account")
def create_user(body: AccountCreateIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.USER_MANAGE))):
    def go():
        u = svc.create_account(db, cu, body, client_ip(request))
        label = {"doctor": "Doctor", "staff": "Staff", "hospital_admin": "Hospital admin"}[body.kind]
        return {"detail": f"{label} account created. They sign in with {u.email}.", "redirect": f"/admin/users/{u.user_id}?created=1"}
    return _wrap(go)


@api.put("/users/{user_id}", summary="Edit an account")
def update_user(user_id: int, body: AccountUpdateIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.USER_MANAGE))):
    return _wrap(lambda: (svc.update_account(db, cu, user_id, body, client_ip(request)), {"detail": "Account saved."})[1])


@api.post("/users/{user_id}/status", summary="Activate or deactivate an account")
def user_status(user_id: int, body: StatusIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.USER_MANAGE))):
    msg = "Account activated." if body.status == "active" else "Account deactivated and signed out everywhere."
    return _wrap(lambda: (svc.set_user_status(db, cu, user_id, body.status, client_ip(request)), {"detail": msg})[1])


@api.post("/users/{user_id}/unlock", summary="Unlock sign-in after lockout")
def user_unlock(user_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.USER_MANAGE))):
    return _wrap(lambda: (svc.unlock_user(db, cu, user_id, client_ip(request)), {"detail": "Sign-in unlocked."})[1])


@api.post("/users/{user_id}/password", summary="Reset a password (user must change it)")
def user_password(user_id: int, body: ResetPasswordIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.USER_MANAGE))):
    return _wrap(lambda: (svc.reset_password(db, cu, user_id, body.password, client_ip(request)), {"detail": "Password reset. Share it with the user securely; they should change it."})[1])


@api.post("/users/{user_id}/verify", summary="Verify or reject a doctor's licence")
def user_verify(user_id: int, body: VerifyIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.DOCTOR_VERIFY))):
    return _wrap(lambda: (svc.verify_doctor(db, cu, user_id, body.status, body.note, client_ip(request)), {"detail": f"Doctor marked {body.status.value}."})[1])


# ================================================================ API: hospitals

@api.post("/hospitals", status_code=201, summary="Add a hospital (system admin)")
def create_hospital(body: HospitalIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.HOSPITAL_MANAGE_ALL))):
    def go():
        h = svc.create_hospital(db, cu, body, client_ip(request))
        return {"detail": "Hospital added. Next, create its hospital administrator.", "redirect": f"/admin/hospitals/{h.hospital_id}"}
    return _wrap(go)


@api.put("/hospitals/{hospital_id}", summary="Edit hospital details")
def update_hospital(hospital_id: int, body: HospitalUpdateIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.HOSPITAL_MANAGE))):
    return _wrap(lambda: (svc.update_hospital(db, cu, hospital_id, body, client_ip(request)), {"detail": "Hospital saved."})[1])


@api.post("/hospitals/{hospital_id}/status", summary="Activate or deactivate a hospital")
def hospital_status(hospital_id: int, body: HospitalStatusIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.HOSPITAL_MANAGE_ALL))):
    return _wrap(lambda: (svc.set_hospital_status(db, cu, hospital_id, body.status, client_ip(request)), {"detail": f"Hospital {body.status.value}."})[1])


# ================================================================ API: roles

@api.post("/roles", status_code=201, summary="Create a role")
def create_role(body: RoleIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.ROLE_MANAGE))):
    return _wrap(lambda: (svc.create_role(db, cu, body.role_name, body.description, client_ip(request)), {"detail": "Role created."})[1])


@api.put("/roles/{role_id}/permissions", summary="Replace a role's permissions")
def role_permissions(role_id: int, body: RolePermissionsIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.ROLE_MANAGE))):
    def go():
        diff = svc.set_role_permissions(db, cu, role_id, body.permissions, client_ip(request))
        n = len(diff["added"]) + len(diff["removed"])
        return {"detail": f"Saved: {len(diff['added'])} added, {len(diff['removed'])} removed. Takes effect on users' next request." if n else "No changes.", **diff}
    return _wrap(go)


@api.post("/roles/{role_id}/status", summary="Activate or deactivate a custom role")
def role_status(role_id: int, body: RoleStatusIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.ROLE_MANAGE))):
    return _wrap(lambda: (svc.set_role_status(db, cu, role_id, body.status, client_ip(request)), {"detail": f"Role {body.status}."})[1])


@api.post("/roles/{role_id}/reset", summary="Restore a built-in role's defaults")
def role_reset(role_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.ROLE_MANAGE))):
    return _wrap(lambda: (svc.reset_role_defaults(db, cu, role_id, client_ip(request)), {"detail": "Default permissions restored."})[1])


# ================================================================ API: oversight, system, backups

@api.post("/emergency/{emergency_access_id}/end", summary="End someone's emergency access")
def end_emergency(emergency_access_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.EMERGENCY_MONITOR))):
    return _wrap(lambda: (svc.end_emergency(db, cu, emergency_access_id, client_ip(request)), {"detail": "Emergency access ended."})[1])


@api.put("/settings", summary="Change system settings")
def update_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.SYSTEM_CONFIG))):
    def go():
        changed = svc.update_settings(db, cu, body.values, client_ip(request))
        return {"detail": f"Saved {len(changed)} setting{'s' if len(changed) != 1 else ''}." if changed else "No changes."}
    return _wrap(go)


@api.get("/health", summary="System health (JSON)")
def health(db: Session = Depends(get_db), _cu: CurrentUser = Depends(require_permissions(P.SYSTEM_MONITOR))):
    return svc.system_health(db)


@api.post("/backups", status_code=201, summary="Create a backup")
def create_backup(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.BACKUP_MANAGE))):
    info = backup_service.create_backup(db, cu.id, client_ip(request))
    return {"detail": f"Backup created: {info.name}", "name": info.name}


@api.post("/backups/{name}/restore", summary="Restore a backup (type RESTORE)")
def restore_backup(name: str, body: RestoreIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.BACKUP_MANAGE))):
    if body.confirm != "RESTORE":
        return JSONResponse({"detail": 'Type RESTORE to confirm.', "fields": {"confirm": 'Type RESTORE to confirm.'}}, status_code=422)
    try:
        result = backup_service.restore_backup(db, name, cu.id, client_ip(request))
    except backup_service.BackupError as e:
        return _err(e)
    return {"detail": f"Restored {result['rows']} rows and {result['files']} files. A safety backup ({result['safety_backup']}) was made first. Everyone must sign in again.",
            "redirect": "/system-admin/login?reason=signed_out"}

