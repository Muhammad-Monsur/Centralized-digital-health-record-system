

from datetime import datetime
from pydantic import BaseModel, EmailStr


# ---------- auth ----------
class LoginIn(BaseModel):
    email: str
    password: str
    portal: str  # "patient" | "doctor" | "hospital-admin" | "system-admin"


class RegisterIn(BaseModel):
    full_name: str
    email: EmailStr
    phone: str = ""
    gender: str = ""
    dob: str = ""
    password: str
    confirm_password: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    portal: str
    full_name: str
    phone: str
    gender: str
    status: str
    patient_id: str = ""
    hospital_name: str = ""
    specialization: str = ""



class DoctorCreateIn(BaseModel):
    full_name: str
    email: EmailStr
    phone: str = ""
    gender: str = ""
    specialization: str = ""
    temp_password: str


class DoctorOut(BaseModel):
    id: int
    user_id: int
    full_name: str
    email: str
    specialization: str
    status: str


class RecordCreateIn(BaseModel):
    information_type: str  # record | prescription | lab_report
    title: str
    details: str = ""
    visibility: str = "Public"


class RecordOut(BaseModel):
    id: int
    information_type: str
    title: str
    details: str
    visibility: str
    doctor_name: str = ""
    information_date: datetime


class VisibilityIn(BaseModel):
    profile_visibility: str  # "Public" | "Private"


class ProfileUpdateIn(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    gender: str | None = None
    blood_group: str | None = None
    address: str | None = None



class PrescriptionIn(BaseModel):
    patient_upi: str
    diagnosis: str
    medicine: str
    dosage: str = ""
    duration: str = ""


class AccessRequestIn(BaseModel):
    patient_upi: str
    purpose: str = "Access private records"


class ConsentDecisionIn(BaseModel):
    approve: bool
    otp_code: str | None = None  # required only when approving


class EmergencyAccessIn(BaseModel):
    patient_upi: str
    reason: str
