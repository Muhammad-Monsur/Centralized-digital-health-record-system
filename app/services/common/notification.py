"""In-app notifications (+ optional SMS for security-critical events)."""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Notification, User
from app.models.enums import NotificationKind
from app.services.common.pagination import Page, paginate
from app.services.common.sms import get_sms_provider


def notify(db: Session, user_id: int, kind: NotificationKind, title: str, body: str, link: str | None = None, *, sms: bool = False) -> None:
    db.add(Notification(user_id=user_id, kind=kind, title=title[:150], body=body[:500], link=link))
    if sms:
        phone = db.scalar(select(User.phone).where(User.user_id == user_id))
        if phone:
            # SMS carries no medical details - only that something happened.
            get_sms_provider().send(phone, f"CDHRS: {title}. Sign in to review.")


def unread_count(db: Session, user_id: int) -> int:
    return int(db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False))) or 0)


def list_for(db: Session, user_id: int, page: int = 1, per_page: int = 20) -> Page[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc(), Notification.notification_id.desc())
    return paginate(db, stmt, page, per_page)


def mark_all_read(db: Session, user_id: int) -> int:
    res = db.execute(update(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False)).values(is_read=True))
    return res.rowcount or 0
