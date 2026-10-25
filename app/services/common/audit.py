"""Audit and access logging.

``audit()`` records security-relevant actions; ``access()`` records who touched
which patient's data (shown to the patient). Both add rows to the caller's
session, so they commit atomically with the business change. Never put
passwords, OTPs or medical content into ``details``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AccessLog, AuditLog
from app.models.enums import AccessType

_FORBIDDEN_KEYS = {"password", "otp", "code", "token", "details_text", "password_hash", "csrf"}


def _scrub(details: dict[str, Any] | None) -> dict[str, Any] | None:
    if not details:
        return None
    return {k: ("[redacted]" if k.lower() in _FORBIDDEN_KEYS else v) for k, v in details.items()}


def audit(
    db: Session,
    *,
    action: str,
    entity: str,
    entity_id: int | str | None = None,
    user_id: int | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
    hospital_id: int | None = None,
) -> None:
    db.add(AuditLog(
        user_id=user_id, action=action, entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        ip_address=(ip or None), details=_scrub(details), hospital_id=hospital_id,
    ))


def access(
    db: Session,
    *,
    user_id: int,
    patient_id: int,
    access_type: AccessType,
    ip: str | None = None,
    information_id: int | None = None,
    consent_id: int | None = None,
    emergency_access_id: int | None = None,
) -> None:
    db.add(AccessLog(
        user_id=user_id, patient_id=patient_id, access_type=access_type, ip_address=ip or None,
        information_id=information_id, consent_id=consent_id, emergency_access_id=emergency_access_id,
    ))
