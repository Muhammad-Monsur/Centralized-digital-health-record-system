"""Server-side sessions stored in the KV store.

The browser only ever holds an opaque random id (HttpOnly, Secure, SameSite=Lax).
The store key is a SHA-256 of that id, so a leaked Redis dump cannot be replayed
as cookies. Sessions expire after an idle timeout (sliding) and an absolute
lifetime, and all of a user's sessions can be killed at once (deactivation,
password change).
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import asdict, dataclass, field

from app.config import settings
from app.services.common.kvstore import get_json, kv, set_json

_PREFIX = "sess:"
_USER_SET = "usess:"


@dataclass
class SessionData:
    user_id: int
    csrf: str
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    ip: str = ""

    @property
    def idle_ttl(self) -> int:
        return settings.session_idle_timeout_minutes * 60

    def seconds_left(self) -> int:
        idle_left = self.last_seen + self.idle_ttl - time.time()
        abs_left = self.created + settings.session_absolute_timeout_hours * 3600 - time.time()
        return max(0, int(min(idle_left, abs_left)))


def session_ref(sid: str | None) -> str | None:
    """Stable, non-secret reference to one sign-in session (SHA-256 of the id).

    Stored on consents and emergency access so that access granted to a doctor
    lasts only for the session in which it was requested."""
    return hashlib.sha256(sid.encode()).hexdigest() if sid else None


def session_ref_alive(ref: str | None) -> bool:
    """True while the session behind ``ref`` exists and has not timed out."""
    if not ref:
        return False
    raw = get_json(_PREFIX + ref)
    return bool(raw) and SessionData(**raw).seconds_left() > 0


def _key(sid: str) -> str:
    return _PREFIX + session_ref(sid)


def create_session(user_id: int, ip: str) -> tuple[str, SessionData]:
    """Always issues a brand-new id (prevents session fixation)."""
    sid = secrets.token_urlsafe(32)
    data = SessionData(user_id=user_id, csrf=secrets.token_urlsafe(32), ip=ip)
    set_json(_key(sid), asdict(data), data.idle_ttl)
    kv.sadd(_USER_SET + str(user_id), _key(sid), settings.session_absolute_timeout_hours * 3600)
    return sid, data


def load_session(sid: str | None) -> SessionData | None:
    if not sid or len(sid) > 100:
        return None
    raw = get_json(_key(sid))
    if not raw:
        return None
    data = SessionData(**raw)
    if data.seconds_left() <= 0:
        destroy_session(sid)
        return None
    return data


def touch_session(sid: str, data: SessionData) -> None:
    """Slide the idle timeout forward (called on real user activity only)."""
    data.last_seen = time.time()
    ttl = max(1, data.seconds_left())
    set_json(_key(sid), asdict(data), ttl)


def destroy_session(sid: str) -> None:
    raw = get_json(_key(sid))
    kv.delete(_key(sid))
    if raw:
        kv.srem(_USER_SET + str(raw["user_id"]), _key(sid))


def destroy_user_sessions(user_id: int) -> None:
    keys = kv.smembers(_USER_SET + str(user_id))
    if keys:
        kv.delete(*keys)
    kv.delete(_USER_SET + str(user_id))
