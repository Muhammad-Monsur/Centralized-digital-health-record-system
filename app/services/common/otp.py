"""One-time passwords for consent confirmation.

* Random (``secrets``), 6 digits, never stored in plain text: we store
  HMAC-SHA256(SECRET_KEY, "consent:<id>:<code>"), so a DB leak reveals nothing.
* Short expiry (OTP_TTL_SECONDS, default 5 min), single use (``verified_at``),
  at most OTP_MAX_ATTEMPTS wrong guesses (then burned), resend cooldown.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import OtpVerification
from app.services.common.security import constant_time_equals, hmac_sha256, utcnow
from app.services.common.sms import get_sms_provider, mask_phone


class OtpError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class OtpIssued:
    otp_id: int
    expires_in: int
    sent_to: str  # masked phone


def _hash(consent_id: int, code: str) -> str:
    return hmac_sha256(f"consent:{consent_id}:{code}")


def issue(db: Session, consent_id: int, phone: str, *, context: str) -> OtpIssued:
    now = utcnow()
    latest = db.scalar(
        select(OtpVerification).where(OtpVerification.consent_id == consent_id).order_by(OtpVerification.otp_id.desc()).limit(1)
    )
    if latest and latest.invalidated_at is None and latest.verified_at is None:
        age = (now - latest.generated_at).total_seconds()
        if age < settings.otp_resend_cooldown_seconds:
            wait = int(settings.otp_resend_cooldown_seconds - age) + 1
            raise OtpError(f"A code was just sent. You can request a new one in {wait} seconds.", 429)

    # A new code always invalidates any earlier unused code for this consent.
    db.execute(
        update(OtpVerification)
        .where(OtpVerification.consent_id == consent_id, OtpVerification.verified_at.is_(None), OtpVerification.invalidated_at.is_(None))
        .values(invalidated_at=now)
    )
    code = f"{secrets.randbelow(10 ** settings.otp_length):0{settings.otp_length}d}"
    otp = OtpVerification(
        consent_id=consent_id, otp_hash=_hash(consent_id, code), generated_at=now,
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
    )
    db.add(otp)
    db.flush()
    minutes = max(1, settings.otp_ttl_seconds // 60)
    result = get_sms_provider().send(phone, f"CDHRS: your code to {context} is {code}. It expires in {minutes} min. Never share it.")
    if not result.ok:
        raise OtpError("We couldn't send the SMS code. Try again in a minute.", 502)
    return OtpIssued(otp_id=otp.otp_id, expires_in=settings.otp_ttl_seconds, sent_to=mask_phone(phone))


def verify(db: Session, consent_id: int, code: str) -> None:
    """Raises OtpError unless ``code`` matches the current live OTP. Marks it used."""
    now = utcnow()
    otp = db.scalar(
        select(OtpVerification)
        .where(OtpVerification.consent_id == consent_id, OtpVerification.invalidated_at.is_(None), OtpVerification.verified_at.is_(None))
        .order_by(OtpVerification.otp_id.desc())
        .limit(1)
        .with_for_update()  # serialise concurrent guesses
    )
    if otp is None:
        raise OtpError("This code is no longer valid. Request a new one.", 410)
    if otp.expires_at <= now:
        otp.invalidated_at = now
        raise OtpError("This code has expired. Request a new one.", 410)
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == settings.otp_length) or not constant_time_equals(otp.otp_hash, _hash(consent_id, code)):
        otp.attempts += 1
        left = settings.otp_max_attempts - otp.attempts
        if left <= 0:
            otp.invalidated_at = now
            raise OtpError("Too many wrong codes. This code is now blocked; request a new one.", 429)
        raise OtpError(f"That code isn't right. {left} attempt{'s' if left != 1 else ''} left.", 400)
    otp.verified_at = now
