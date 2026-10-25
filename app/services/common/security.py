"""Password hashing, password policy, UPI generation and time helpers."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings

# argon2id with the library's current recommended parameters (RFC 9106 low-memory profile).
_ph = PasswordHasher()

# A precomputed hash used to keep timing equal when the username does not exist.
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))


def utcnow() -> datetime:
    """Naive UTC 'now' (the DB stores naive UTC; see database.py)."""
    return datetime.now(UTC).replace(tzinfo=None)


def local_str(dt: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Format a stored (naive UTC) datetime in the display time zone."""
    if dt is None:
        return "—"
    from zoneinfo import ZoneInfo

    return dt.replace(tzinfo=UTC).astimezone(ZoneInfo(settings.display_timezone)).strftime(fmt)


# --- Passwords -----------------------------------------------------------------------

PASSWORD_RULES = (
    "At least 10 characters, with an uppercase letter, a lowercase letter, a number and a symbol."
)
_COMMON = {"password", "password1", "123456789", "qwerty123", "letmein123", "welcome123", "admin12345"}


def password_problems(password: str, *, username: str = "", email: str = "") -> list[str]:
    """Return human-readable reasons the password is too weak (empty = OK)."""
    problems: list[str] = []
    if len(password) < 10:
        problems.append("Use at least 10 characters.")
    if len(password) > 128:
        problems.append("Use at most 128 characters.")
    if not re.search(r"[A-Z]", password):
        problems.append("Add an uppercase letter.")
    if not re.search(r"[a-z]", password):
        problems.append("Add a lowercase letter.")
    if not re.search(r"\d", password):
        problems.append("Add a number.")
    if not re.search(r"[^A-Za-z0-9]", password):
        problems.append("Add a symbol (for example ! # @ %).")
    low = password.lower()
    if low in _COMMON:
        problems.append("This password is too common.")
    if username and len(username) >= 3 and username.lower() in low:
        problems.append("Don't include your username.")
    local = email.split("@")[0].lower() if email else ""
    if local and len(local) >= 3 and local in low:
        problems.append("Don't include your email address.")
    return problems


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-ish time verify; also burns time when the user doesn't exist."""
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


# --- UPI -------------------------------------------------------------------------------
# Format: CDH-XXXX-XXXX-XXXX  (Crockford base32: no I, L, O, U -> no look-alike characters)
# 10 random characters (50 bits, ~1.1e15 values) + 2 check characters.
# The check value is a position-weighted sum mod 1021. 1021 is prime and larger than any
# weight (1..10) or character difference (<32), so EVERY single-character typo and EVERY
# swap of two neighbouring characters changes the check value - typos are caught before
# any database lookup. Combined with rate limiting, 50 random bits make UPIs unguessable.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_UPI_RE = re.compile(r"^CDH-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$")
_MOD = 1021


def _check_chars(body: str) -> str:
    total = sum((i + 1) * _ALPHABET.index(c) for i, c in enumerate(body)) % _MOD
    return _ALPHABET[total // 32] + _ALPHABET[total % 32]


def generate_upi() -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    raw = body + _check_chars(body)
    return f"CDH-{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


def normalize_upi(value: str) -> str | None:
    """Uppercase, fix look-alikes, insert dashes; return None if invalid or checksum fails."""
    s = re.sub(r"[\s-]", "", value.strip().upper())
    if s.startswith("CDH"):
        s = s[3:]
    s = s.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    if len(s) != 12 or any(c not in _ALPHABET for c in s):
        return None
    if _check_chars(s[:10]) != s[10:]:
        return None
    upi = f"CDH-{s[0:4]}-{s[4:8]}-{s[8:12]}"
    return upi if _UPI_RE.match(upi) else None


# --- CSRF token masking (BREACH mitigation) ----------------------------------------
# Pages are compressed and also reflect user input; an attacker who can observe response
# sizes could otherwise recover a secret that appears verbatim in every response. So the
# token is never sent as-is: each response carries pad + (token XOR pad) with a fresh
# random pad, and the server unmasks what the browser sends back.

def mask_token(token: str) -> str:
    import base64

    raw = token.encode()
    pad = secrets.token_bytes(len(raw))
    return base64.urlsafe_b64encode(pad + bytes(a ^ b for a, b in zip(raw, pad))).decode().rstrip("=")


def unmask_token(masked: str) -> str | None:
    import base64

    try:
        data = base64.urlsafe_b64decode(masked + "=" * (-len(masked) % 4))
    except (ValueError, TypeError):
        return None
    if len(data) % 2 or not data:
        return None
    half = len(data) // 2
    try:
        return bytes(a ^ b for a, b in zip(data[half:], data[:half])).decode()
    except UnicodeDecodeError:
        return None


# --- Misc hashing -------------------------------------------------------------------------

def hmac_sha256(value: str) -> str:
    """Keyed hash (used for OTPs): useless to an attacker without SECRET_KEY."""
    return hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
