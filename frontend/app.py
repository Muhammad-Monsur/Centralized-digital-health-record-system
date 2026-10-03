"""
CDHRS - Portal Server (static frontend + working login)
--------------------------------------------------------
Serves the portal-separated frontend and provides real (server-side) auth:

    POST /api/auth/login      email + password + portal  -> sets session cookie
    POST /api/auth/register   patient self-registration  -> sets session cookie
    POST /api/auth/logout
    GET  /api/me              current user (used by the profile pages)

Users live in a local SQLite file (cdhrs.db, auto-created and seeded with the
demo accounts from README.md). When the MySQL layer is added later, only the
small "user store" section below needs to change - the routes and frontend
stay the same.

Profile pages are PROTECTED: /<portal>/profile.html is only served when the
session cookie belongs to a user with that portal's role.

Run:  uvicorn app:app --reload      then open  http://127.0.0.1:8000/
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CDHRS_DB", BASE_DIR / "cdhrs.db"))
# Dev default only - set CDHRS_SECRET in the environment for anything real.
SECRET = os.environ.get("CDHRS_SECRET", "cdhrs-dev-secret-change-me").encode()
COOKIE = "cdhrs_session"
SESSION_SECONDS = 8 * 60 * 60

# portal folder name -> role stored in the database
PORTAL_ROLE = {
    "patient": "patient",
    "doctor": "doctor",
    "hospital-admin": "hospital_admin",
    "system-admin": "system_admin",
}
ROLE_PORTAL = {v: k for k, v in PORTAL_ROLE.items()}

app = FastAPI(title="CDHRS")


# ------------------------------------------------------------------ user store
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000)
    return hmac.compare_digest(check.hex(), digest_hex)


DEMO_USERS = [
    # id, email, password, role, full_name, phone, gender, dob, extra
    (1, "sysadmin@cdhrs.bd", "SysAdmin@12345", "system_admin", "System Admin", "", "", "", ""),
    (2, "admin@cdhrs.bd", "Admin@12345", "hospital_admin", "Hospital Admin", "", "", "", "Dhaka Medical Center"),
    (3, "dr.farhana@cdhrs.bd", "Doctor@12345", "doctor", "Dr. Farhana Akter", "+880 1711 000003", "Female", "", "Cardiology"),
    (4, "dr.nazmoon@cdhrs.bd", "Doctor@12345", "doctor", "Dr. Nazmoon Nahar Suzana", "", "", "", ""),
    (178, "rahim@email.com", "Patient@12345", "patient", "Rahim Ahmed", "+880 1712 345678", "Male", "2003-12-18", ""),
]


def init_db():
    with db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                full_name TEXT NOT NULL,
                phone TEXT DEFAULT '',
                gender TEXT DEFAULT '',
                dob TEXT DEFAULT '',
                extra TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        # Add any demo account that is missing, so accounts added later also reach existing databases.
        for uid, email, pw, role, name, phone, gender, dob, extra in DEMO_USERS:
            if con.execute("SELECT 1 FROM users WHERE email=? OR id=?", (email, uid)).fetchone():
                continue
            con.execute(
                "INSERT INTO users (id,email,password_hash,role,full_name,phone,gender,dob,extra) VALUES (?,?,?,?,?,?,?,?,?)",
                (uid, email, hash_password(pw), role, name, phone, gender, dob, extra),
            )


init_db()


def public_user(row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "portal": ROLE_PORTAL[row["role"]],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "gender": row["gender"],
        "dob": row["dob"],
        "extra": row["extra"],
        "patient_id": f"P-{row['id']:06d}" if row["role"] == "patient" else "",
    }


# -------------------------------------------------------------------- sessions
def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _unsign(token: str | None):
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    good = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None
    return payload if payload.get("exp", 0) > time.time() else None


def start_session(response: Response, user_id: int):
    token = _sign({"uid": user_id, "exp": int(time.time()) + SESSION_SECONDS})
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax", path="/")


def current_user(request: Request):
    payload = _unsign(request.cookies.get(COOKIE))
    if not payload:
        return None
    with db() as con:
        return con.execute("SELECT * FROM users WHERE id=?", (payload["uid"],)).fetchone()


# ------------------------------------------------------------------------ auth
FAILS: dict[str, list] = {}  # email -> [count, first_fail_time]  (basic brute-force guard)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginIn(BaseModel):
    email: str
    password: str
    portal: str


class RegisterIn(BaseModel):
    full_name: str
    email: str
    phone: str
    gender: str = ""
    dob: str = ""
    password: str
    confirm_password: str


@app.post("/api/auth/login")
def login(data: LoginIn, response: Response):
    email = data.email.strip().lower()
    if data.portal not in PORTAL_ROLE:
        raise HTTPException(400, "Unknown portal.")
    count, first = FAILS.get(email, [0, time.time()])
    if time.time() - first > 300:
        count, first = 0, time.time()
    if count >= 5:
        raise HTTPException(429, "Too many failed attempts. Please wait a few minutes and try again.")

    with db() as con:
        row = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    ok = bool(row) and verify_password(data.password, row["password_hash"]) and row["role"] == PORTAL_ROLE[data.portal]
    if not ok:
        FAILS[email] = [count + 1, first]
        raise HTTPException(401, "Invalid email or password for this portal.")

    FAILS.pop(email, None)
    start_session(response, row["id"])
    return {"ok": True, "redirect": f"/{data.portal}/profile.html", "user": public_user(row)}


@app.post("/api/auth/register")
def register(data: RegisterIn, response: Response):
    email = data.email.strip().lower()
    if not data.full_name.strip():
        raise HTTPException(400, "Please enter your full name.")
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if len(data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if data.password != data.confirm_password:
        raise HTTPException(400, "Passwords do not match.")
    try:
        with db() as con:
            cur = con.execute(
                "INSERT INTO users (email,password_hash,role,full_name,phone,gender,dob) VALUES (?,?,?,?,?,?,?)",
                (email, hash_password(data.password), "patient", data.full_name.strip(),
                 data.phone.strip(), data.gender, data.dob),
            )
            new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists.")
    start_session(response, new_id)
    return {"ok": True, "redirect": "/patient/profile.html"}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    row = current_user(request)
    if not row:
        raise HTTPException(401, "Not signed in.")
    return public_user(row)


# ------------------------------------------------- protected portal pages
# Pages that need a signed-in user of that portal's role (everything except login).
PROTECTED_PAGES = {portal: ["profile.html"] for portal in PORTAL_ROLE}
PROTECTED_PAGES["doctor"] += [
    "prescription.html", "medical-reports.html", "lab-reports.html", "emergency-access.html", "activity-log.html",
]


def make_guard(portal: str, page: str):
    def guard(request: Request):
        row = current_user(request)
        if not row or row["role"] != PORTAL_ROLE[portal]:
            return RedirectResponse(f"/{portal}/login.html", status_code=302)
        resp = FileResponse(BASE_DIR / portal / page)
        resp.headers["Cache-Control"] = "no-store"
        return resp
    return guard


def make_home(portal: str):
    def home():
        return RedirectResponse(f"/{portal}/login.html", status_code=302)
    return home


# Guards/redirects are registered BEFORE the static mounts so they take priority.
for _portal in PORTAL_ROLE:
    for _page in PROTECTED_PAGES[_portal]:
        app.add_api_route(f"/{_portal}/{_page}", make_guard(_portal, _page), methods=["GET"], include_in_schema=False)
    app.add_api_route(f"/{_portal}", make_home(_portal), methods=["GET"], include_in_schema=False)
    app.add_api_route(f"/{_portal}/", make_home(_portal), methods=["GET"], include_in_schema=False)

# ------------------------------------------------------------------ static
app.mount("/shared", StaticFiles(directory=BASE_DIR / "shared"), name="shared")
for _portal in PORTAL_ROLE:
    app.mount(f"/{_portal}", StaticFiles(directory=BASE_DIR / _portal), name=_portal)


@app.get("/")
def landing():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/preview.html")
def preview():
    return FileResponse(BASE_DIR / "preview.html")
