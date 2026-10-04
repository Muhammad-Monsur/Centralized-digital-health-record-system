import datetime
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..database import SQLALCHEMY_DATABASE_URL
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
        user_count = db.query(models.UserRole).filter(models.UserRole.role_id == role.id).count()
        perms = (
            db.query(models.Permission)
            .join(models.RolePermission, models.RolePermission.permission_id == models.Permission.id)
            .filter(models.RolePermission.role_id == role.id)
            .all()
        )
        out.append({"role": role.name, "users": user_count, "permissions": ", ".join(p.name for p in perms)})
    return out
