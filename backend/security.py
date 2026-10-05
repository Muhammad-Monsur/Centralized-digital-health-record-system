
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

SECRET = os.environ.get("CDHRS_SECRET", "cdhrs-dev-secret-change-me").encode()
COOKIE_NAME = "cdhrs_session"
SESSION_SECONDS = 8 * 60 * 60  # 8 hours


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000)
    return hmac.compare_digest(check.hex(), digest_hex)


def sign_session(user_id: int) -> str:
    payload = {"uid": user_id, "exp": int(time.time()) + SESSION_SECONDS}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_session(token: str | None):
    """Returns the user id if the cookie is valid and not expired, else None."""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    good_sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good_sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload.get("uid")


def generate_otp() -> str:
    
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()
