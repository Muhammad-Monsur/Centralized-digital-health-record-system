from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import SessionLocal
from .security import read_session
from . import models


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    cdhrs_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    user_id = read_session(cdhrs_session)
    if not user_id:
        raise HTTPException(401, "Not signed in.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(401, "Not signed in.")
    if user.status == "Blocked":
        raise HTTPException(403, "This account has been blocked.")
    return user


def require_role(role: str):
    # Usage: Depends(require_role('doctor')) on any doctor-only endpoint.
    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role != role:
            raise HTTPException(403, f"This action requires a {role.replace('_', ' ')} account.")
        return user
    return checker


def log_audit(db: Session, user_id: int | None, action: str, entity: str = "", entity_id: int = None, details: str = ""):
   
    entry = models.AuditLog(user_id=user_id, action=action, entity=entity, entity_id=entity_id, details=details)
    db.add(entry)
    db.commit()
