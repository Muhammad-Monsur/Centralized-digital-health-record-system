
import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..backup import BackupError, list_backups, make_backup
from ..deps import get_db, log_audit, require_role

router = APIRouter(prefix="/api/system-admin", tags=["system-admin"])

@router.get("/overview")
def overview(user: models.User = Depends(require_role("system_admin")), db: Session = Depends(get_db)):
    return {
        "total_users": db.query(models.User).count(),
        "total_hospitals": db.query(models.Hospital).count(),
        "total_records_accessed": db.query(models.AccessLog).count(),
    }


@router.get("/rbac")
def rbac(user: models.User = Depends(require_role("system_admin")), db: Session = Depends(get_db)):
    roles = db.query(models.Role).all()
    out = []
    for role in roles:
        user_count = db.query(models.UserRole).filter(
            models.UserRole.role_id == role.id
        ).count()

        perms = (
            db.query(models.Permission)
            .join(
                models.RolePermission,
                models.RolePermission.permission_id == models.Permission.id
            )
            .filter(models.RolePermission.role_id == role.id)
            .all()
        )

        out.append({
            "id": role.id,
            "role": role.name,
            "users": user_count,
            "permissions": ", ".join(p.name for p in perms)
        })
    return out


@router.get("/hospitals")
def hospitals(user: models.User = Depends(require_role("system_admin")), db: Session = Depends(get_db)):
    rows = db.query(models.Hospital).all()
    return [{"id": h.id, "name": h.name, "status": h.status, "doctors": len(h.doctors)} for h in rows]


@router.get("/audit-log")
def audit_log(user: models.User = Depends(require_role("system_admin")), db: Session = Depends(get_db)):
    logs = db.query(models.AuditLog).order_by(models.AuditLog.timestamp.desc()).limit(100).all()
    out = []
    for log in logs:
        actor = db.query(models.User).filter(models.User.id == log.user_id).first() if log.user_id else None
        out.append({"timestamp": log.timestamp, "user": actor.full_name if actor else "System", "action": log.action, "details": log.details})
    return out


@router.get("/emergency-log")
def emergency_log(user: models.User = Depends(require_role("system_admin")), db: Session = Depends(get_db)):
    rows = db.query(models.EmergencyAccess).order_by(models.EmergencyAccess.accessed_at.desc()).limit(100).all()
    return [
        {
            "timestamp": r.accessed_at, "doctor": r.doctor.user.full_name,
            "patient_id": r.patient.upi, "reason": r.reason,
        }
        for r in rows
    ]


@router.post("/backup")
def backup(user: models.User = Depends(require_role("system_admin")), db: Session = Depends(get_db)):
    
    # this is dummy backup code for SQLite, In next configure a scheduled mysqldump for the MySQL database
    note = "Backup logged (configure a scheduled mysqldump for the real MySQL database)."
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        src = Path(SQLALCHEMY_DATABASE_URL.replace("sqlite:///", ""))
        if src.exists():
            backups_dir = src.parent / "backups"
            backups_dir.mkdir(exist_ok=True)
            stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            dest = backups_dir / f"cdhrs_backup_{stamp}.db"
            shutil.copy(src, dest)
            note = f"SQLite backup saved to {dest.name}"
    log_audit(db, user.id, "Manual database backup triggered", details=note)
    return {"ok": True, "message": note}
