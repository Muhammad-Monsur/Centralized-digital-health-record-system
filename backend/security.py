
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


