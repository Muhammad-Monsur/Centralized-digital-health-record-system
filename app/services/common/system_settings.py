"""Runtime system settings (admin-editable), cached with explicit invalidation."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SystemSetting
from app.services.common import cache

_KEY = "system_settings"
TTL = 300


def all_settings(db: Session) -> dict[str, str]:
    return cache.cached(_KEY, TTL, lambda: {s.setting_key: s.setting_value for s in db.scalars(select(SystemSetting))})


def get(db: Session, key: str, default: str = "") -> str:
    return all_settings(db).get(key, default)


def flag(db: Session, key: str, default: bool = True) -> bool:
    return get(db, key, "true" if default else "false").lower() == "true"


def invalidate() -> None:
    cache.invalidate(_KEY)
