
"""
CDHRS - Patient Portal API  (backend/routers/patient.py)
Ei ekta file-i shob kichu: database, login, ar patient er sob API.
Onno kono file banate hobe na, ar doctor.py / admin file er sathe conflict hobe na
(karon table er naam alada, database file-o alada: database/patient.db).

Install (ekbar):
    pip install fastapi uvicorn sqlalchemy pyjwt

Run (alada chalate chaile):
    cd backend/routers
    uvicorn patient:app --reload
    -> Test: http://127.0.0.1:8000/docs

Tomar main app e jure dite chaile (jekhane app = FastAPI() ache):
    from routers.patient import router as patient_router
    app.include_router(patient_router)
"""

import hashlib
import hmac
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import jwt
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

# =====================================================================
# 1) SETTINGS
# =====================================================================
SECRET_KEY = os.getenv("CDHRS_PATIENT_SECRET", "change-me-in-real-project")
TOKEN_MINUTES = 60 * 8


def now():
    return datetime.now(timezone.utc)


# =====================================================================
# 2) DATABASE  (SQLite file: <project root>/database/patient.db)
# =====================================================================
# patient.py -> routers -> backend -> project root
ROOT_DIR = Path(__file__).resolve().parents[2]
DB_DIR = ROOT_DIR / "database"
DB_DIR.mkdir(exist_ok=True)

engine = create_engine(f"sqlite:///{DB_DIR / 'patient.db'}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class PatientUser(Base):
    __tablename__ = "patient_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(30), default="")
    gender: Mapped[str] = mapped_column(String(20), default="")
    dob: Mapped[str] = mapped_column(String(20), default="")
    blood_group: Mapped[str] = mapped_column(String(5), default="")
    address: Mapped[str] = mapped_column(String(200), default="")
    visibility: Mapped[str] = mapped_column(String(10), default="Public")  # Public / Private


class PatientRecord(Base):
    __tablename__ = "patient_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient_users.id"))
    title: Mapped[str] = mapped_column(String(150))
    information_type: Mapped[str] = mapped_column(String(20))  # record / lab_report / prescription
    details: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[str] = mapped_column(String(10), default="Public")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PatientConsent(Base):
    """Doctor access chaile ekta request toiri hoy. Patient OTP diye approve kore."""
    __tablename__ = "patient_consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient_users.id"))
    doctor_name: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(200))
    otp: Mapped[str] = mapped_column(String(6))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending / approved / denied
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PatientActivity(Base):
    __tablename__ = "patient_activity"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient_users.id"))
    accessed_by: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


Base.metadata.create_all(engine)  # table na thakle banay


def get_db():
    """Protita request e ekta database session dey, kaj sesh hole bondho kore."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =====================================================================
# 3) SECURITY (password hash + JWT token + current patient)
# =====================================================================
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + digest.hex()


def check_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split(":")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_token(user: PatientUser) -> str:
    payload = {"sub": str(user.id), "role": "patient", "exp": now() + timedelta(minutes=TOKEN_MINUTES)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


bearer = HTTPBearer()


def current_patient(
    cred: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> PatientUser:
    """Protected route e age eta chole: token check kore patient ber kore."""
    try:
        data = jwt.decode(cred.credentials, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired. Please sign in again.")
    if data.get("role") != "patient":
        raise HTTPException(403, "This is not a patient account")
    user = db.get(PatientUser, int(data["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    return user


# =====================================================================
# 4) SCHEMAS (frontend theke ja data ashbe tar shape)
# =====================================================================
class RegisterIn(BaseModel):          # register.html
    full_name: str
    dob: str
    email: str
    phone: str
    gender: str
    password: str
    confirm_password: str
    terms: bool = False


class LoginIn(BaseModel):             # login.html
    email: str
    password: str


class ProfileIn(BaseModel):           # profile.html -> Edit Profile form
    full_name: str
    phone: str = ""
    gender: str = ""
    blood_group: str = ""
    address: str = ""


class VisibilityIn(BaseModel):        # profile.html -> Public/Private toggle
    visibility: Literal["Public", "Private"]


class RecordIn(BaseModel):            # profile.html -> Add a Record form
    title: str
    information_type: Literal["record", "lab_report", "prescription"] = "record"
    details: str = ""
    visibility: Literal["Public", "Private"] = "Public"


class OtpIn(BaseModel):
    otp: str


class DemoRequestIn(BaseModel):       # shudhu test er jonno
    doctor_name: str = "Dr. Demo"
    purpose: str = "Treatment review"


# =====================================================================
# 5) HELPERS (database object -> frontend er jonno dictionary)
# =====================================================================
def initials(name: str) -> str:
    return "".join(p[0] for p in name.split()[:2]).upper() or "?"


def user_out(u: PatientUser) -> dict:
    return {
        "id": u.id,
        "role": "patient",
        "full_name": u.full_name,
        "name": u.full_name,                       # data-me="name"
        "initials": initials(u.full_name),         # data-me="initials"
        "sub": f"Patient ID: P-{u.id:04d}",        # data-me="sub"
        "email": u.email,
        "phone": u.phone,
        "gender": u.gender,
        "dob": u.dob,
        "blood_group": u.blood_group,
        "address": u.address,
        "visibility": u.visibility,
    }


def record_out(r: PatientRecord) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "information_type": r.information_type,
        "details": r.details,
        "visibility": r.visibility,
        "date": r.created_at.strftime("%Y-%m-%d"),
    }


# =====================================================================
# 6) ROUTES  (sob URL shuru hoy /api/patient diye)
# =====================================================================
router = APIRouter(prefix="/api/patient", tags=["Patient"])


# ---------- REGISTER + LOGIN ----------
@router.post("/register", status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Enter a valid email")
    if data.gender not in ("Male", "Female", "Other"):
        raise HTTPException(400, "Please select your gender")
    if len(data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if data.password != data.confirm_password:
        raise HTTPException(400, "Passwords do not match")
    if not data.terms:
        raise HTTPException(400, "Please accept the Terms of Service")
    if db.scalar(select(PatientUser).where(PatientUser.email == email)):
        raise HTTPException(409, "An account with this email already exists")

    user = PatientUser(
        full_name=data.full_name.strip(), email=email,
        password_hash=hash_password(data.password),
        phone=data.phone, gender=data.gender, dob=data.dob,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": create_token(user), "token_type": "bearer", "role": "patient", "user": user_out(user)}


@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(PatientUser).where(PatientUser.email == data.email.strip().lower()))
    if not user or not check_password(data.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"access_token": create_token(user), "token_type": "bearer", "role": "patient", "user": user_out(user)}


# ---------- ME / PROFILE ----------
@router.get("/me")
def me(user: PatientUser = Depends(current_patient)):
    return user_out(user)


@router.put("/profile")
def update_profile(data: ProfileIn, user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    user.full_name = data.full_name.strip() or user.full_name
    user.phone, user.gender = data.phone, data.gender
    user.blood_group, user.address = data.blood_group, data.address
    db.commit()
    return user_out(user)


@router.put("/visibility")
def update_visibility(data: VisibilityIn, user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    user.visibility = data.visibility
    db.commit()
    return {"visibility": user.visibility}


# ---------- DASHBOARD ----------
@router.get("/dashboard")
def dashboard(user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(PatientRecord).where(PatientRecord.patient_id == user.id))
    pending = db.scalar(
        select(func.count()).select_from(PatientConsent)
        .where(PatientConsent.patient_id == user.id, PatientConsent.status == "pending")
    )
    return {"total_records": total, "pending_requests": pending, "report_visibility": user.visibility}


# ---------- MEDICAL RECORDS + PRESCRIPTIONS ----------
@router.get("/records")
def list_records(user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PatientRecord)
        .where(PatientRecord.patient_id == user.id, PatientRecord.information_type != "prescription")
        .order_by(PatientRecord.created_at.desc())
    )
    return [record_out(r) for r in rows]


@router.get("/prescriptions")
def list_prescriptions(user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PatientRecord)
        .where(PatientRecord.patient_id == user.id, PatientRecord.information_type == "prescription")
        .order_by(PatientRecord.created_at.desc())
    )
    return [record_out(r) for r in rows]


@router.post("/records", status_code=201)
def add_record(data: RecordIn, user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    record = PatientRecord(patient_id=user.id, **data.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record_out(record)


# ---------- CONSENT (doctor er request -> patient OTP diye approve/deny) ----------
@router.get("/consent")
def pending_requests(user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PatientConsent).where(PatientConsent.patient_id == user.id, PatientConsent.status == "pending")
    )
    return [{"id": c.id, "doctor": c.doctor_name, "purpose": c.purpose} for c in rows]


def get_my_pending_request(request_id: int, user: PatientUser, db: Session) -> PatientConsent:
    c = db.get(PatientConsent, request_id)
    if not c or c.patient_id != user.id or c.status != "pending":
        raise HTTPException(404, "Request not found")
    return c


@router.post("/consent/{request_id}/approve")
def approve_request(request_id: int, data: OtpIn, user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    c = get_my_pending_request(request_id, user, db)
    if data.otp != c.otp:
        raise HTTPException(400, "Wrong OTP code")
    c.status = "approved"
    db.add(PatientActivity(patient_id=user.id, accessed_by=c.doctor_name, type="Access approved"))
    db.commit()
    return {"status": "approved"}


@router.post("/consent/{request_id}/deny")
def deny_request(request_id: int, user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    c = get_my_pending_request(request_id, user, db)
    c.status = "denied"
    db.add(PatientActivity(patient_id=user.id, accessed_by=c.doctor_name, type="Access denied"))
    db.commit()
    return {"status": "denied"}


@router.post("/consent/demo-request", status_code=201)
def demo_request(data: DemoRequestIn, user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    """
    SHUDHU TEST ER JONNO: doctor er access request nijei toiri kore, jate consent tab test korte paro.
    Doctor portal ready hole eta delete kore dio.
    """
    otp = f"{random.randint(0, 999999):06d}"
    c = PatientConsent(patient_id=user.id, doctor_name=data.doctor_name, purpose=data.purpose, otp=otp)
    db.add(c)
    db.commit()
    print(f"[DEMO] OTP for request #{c.id}: {otp}")  # real project e SMS/email e jabe
    return {"request_id": c.id, "status": "pending"}


# ---------- ACTIVITY LOG ----------
@router.get("/activity")
def activity(user: PatientUser = Depends(current_patient), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PatientActivity).where(PatientActivity.patient_id == user.id).order_by(PatientActivity.created_at.desc())
    )
    return [{"accessed_by": a.accessed_by, "type": a.type, "when": a.created_at.strftime("%Y-%m-%d %H:%M")} for a in rows]


# =====================================================================
# 7) STANDALONE APP (shudhu patient.py alada chalanor jonno)
# =====================================================================
app = FastAPI(title="CDHRS Patient API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)