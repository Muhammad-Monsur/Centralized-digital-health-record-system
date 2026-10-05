

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


