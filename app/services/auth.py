"""Login, logout, password change - with lockout, rate limiting and audit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.models.enums import UserStatus
from app.services.common import rate_limit
from app.services.common.audit import audit
from app.services.common.security import (
    hash_password,
    hmac_sha256,
    password_needs_rehash,
    password_problems,
    utcnow,
    verify_password,
)
from app.services.common.session import create_session, destroy_session, destroy_user_sessions, session_ref


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


GENERIC_FAIL = "That username or password isn't right."
LOCKED_MSG = "Too many failed attempts. Sign-in is paused for this account; try again in {m} minutes."
IP_LIMIT_PER_15MIN = 30


@dataclass
class LoginResult:
    user: User
    sid: str


def login(db: Session, identifier: str, password: str, ip: str, allowed_roles: set[str] | None = None) -> LoginResult:
    ident = identifier.strip().lower()
    ip_check = rate_limit.hit("login-ip", ip, IP_LIMIT_PER_15MIN, 15 * 60)
    if not ip_check.allowed:
        audit(db, action="auth.login_rate_limited", entity="user", ip=ip, details={"identifier": ident[:100]})
        db.commit()
        raise AuthError("Too many sign-in attempts from this network. Wait a few minutes and try again.", 429, ip_check.retry_after)

    # Unknown identifiers get the same lockout behaviour as real ones (no account enumeration).
    ghost_key = "ghost:" + hmac_sha256(ident)[:32]  # keyed hash: attempted usernames aren't stored in clear
    if rate_limit.peek("login-ghost", ghost_key) >= settings.login_max_attempts:
        raise AuthError(LOCKED_MSG.format(m=settings.login_lockout_minutes), 429)

    user = db.scalar(select(User).where(or_(func.lower(User.username) == ident, func.lower(User.email) == ident)))
    now = utcnow()

    if user is not None and user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise AuthError(LOCKED_MSG.format(m=minutes), 429)

    ok = verify_password(user.password_hash if user else None, password)
    if not ok:
        if user is None:
            rate_limit.hit("login-ghost", ghost_key, 10_000, settings.login_lockout_minutes * 60)
            audit(db, action="auth.login_failed", entity="user", ip=ip, details={"identifier": ident[:100], "reason": "unknown_user"})
        else:
            user.failed_login_count += 1
            details = {"attempt": user.failed_login_count}
            if user.failed_login_count >= settings.login_max_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
                audit(db, action="auth.account_locked", entity="user", entity_id=user.user_id, user_id=user.user_id, ip=ip)
            audit(db, action="auth.login_failed", entity="user", entity_id=user.user_id, user_id=user.user_id, ip=ip, details=details)
        db.commit()
        raise AuthError(GENERIC_FAIL, 401)

    assert user is not None
    # Right password, wrong door (e.g. a patient on the doctor sign-in page): same generic
    # answer as a wrong password so the page can't be used to probe which role an account has.
    # Not counted towards lockout, because the password was correct.
    if allowed_roles is not None and not (user.role_names & allowed_roles):
        audit(db, action="auth.login_wrong_portal", entity="user", entity_id=user.user_id, user_id=user.user_id, ip=ip)
        db.commit()
        raise AuthError(GENERIC_FAIL, 401)

    # Correct password: only now reveal account state.
    if user.status in (UserStatus.INACTIVE, UserStatus.LOCKED):
        audit(db, action="auth.login_blocked", entity="user", entity_id=user.user_id, user_id=user.user_id, ip=ip, details={"status": user.status.value})
        db.commit()
        raise AuthError("This account is disabled. Contact your hospital or system administrator.", 403)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    audit(db, action="auth.login", entity="user", entity_id=user.user_id, user_id=user.user_id, ip=ip)
    db.commit()
    sid, _ = create_session(user.user_id, ip)
    return LoginResult(user=user, sid=sid)


def logout(db: Session, sid: str | None, user_id: int | None, ip: str, reason: str = "user") -> None:
    if sid:
        destroy_session(sid)
        # Consent and emergency access belong to this session: signing out ends them.
        from app.services import consent as consent_service
        consent_service.end_for_session(db, session_ref(sid), "signed_out" if reason == "user" else "timeout")
        db.commit()
    if user_id:
        audit(db, action="auth.logout", entity="user", entity_id=user_id, user_id=user_id, ip=ip, details={"reason": reason})
        db.commit()


def change_password(db: Session, user: User, current: str, new: str, ip: str) -> str:
    """Returns a fresh session id; every other session of the user is ended."""
    if not verify_password(user.password_hash, current):
        raise AuthError("Your current password isn't right.", 400)
    problems = password_problems(new, username=user.username, email=user.email)
    if problems:
        raise AuthError(" ".join(problems), 422)
    if verify_password(user.password_hash, new):
        raise AuthError("Choose a password you haven't used here before.", 422)
    user.password_hash = hash_password(new)
    user.must_change_password = False
    audit(db, action="auth.password_changed", entity="user", entity_id=user.user_id, user_id=user.user_id, ip=ip)
    db.commit()
    destroy_user_sessions(user.user_id)
    sid, _ = create_session(user.user_id, ip)
    return sid
