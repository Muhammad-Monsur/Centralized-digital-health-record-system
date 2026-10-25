"""Patient-side request schemas (Pydantic = the single source of validation rules)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import EmailStr, Field, ValidationInfo, field_validator

from app.models.enums import BloodGroup, Gender, InformationType, Visibility
from app.schemas.common import CleanStr, Phone, StrictModel, Username
from app.services.common.security import password_problems, utcnow

MIN_DOB = date(1900, 1, 1)


def _dob(v: date) -> date:
    today = utcnow().date()
    if v > today:
        raise ValueError("Date of birth can't be in the future.")
    if v < MIN_DOB:
        raise ValueError("Enter a date of birth after 1 January 1900.")
    return v


class PatientRegisterIn(StrictModel):
    full_name: CleanStr = Field(min_length=2, max_length=120)
    username: Username
    email: EmailStr = Field(max_length=255)
    phone: Phone
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(max_length=128)
    date_of_birth: date
    gender: Gender
    blood_group: BloodGroup = BloodGroup.UNKNOWN
    address: CleanStr | None = Field(default=None, max_length=255)
    accept_terms: bool

    _check_dob = field_validator("date_of_birth")(lambda cls, v: _dob(v))

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    # Field-level validators so each message appears next to its own input.
    @field_validator("password")
    @classmethod
    def _strong(cls, v: str, info: ValidationInfo) -> str:
        problems = password_problems(v, username=info.data.get("username", ""), email=info.data.get("email", ""))
        if problems:
            raise ValueError(" ".join(problems))
        return v

    @field_validator("confirm_password")
    @classmethod
    def _match(cls, v: str, info: ValidationInfo) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("The two passwords don't match.")
        return v

    @field_validator("accept_terms")
    @classmethod
    def _terms(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Please accept the privacy notice to continue.")
        return v


class ProfileUpdateIn(StrictModel):
    full_name: CleanStr = Field(min_length=2, max_length=120)
    email: EmailStr = Field(max_length=255)
    phone: Phone
    date_of_birth: date
    gender: Gender
    blood_group: BloodGroup
    address: CleanStr | None = Field(default=None, max_length=255)
    profile_visibility: Visibility
    # Required only when the phone number or email changes: the phone receives consent codes,
    # so changing it must prove it's really the patient, not someone holding their session.
    current_password: str | None = Field(default=None, max_length=128)

    _check_dob = field_validator("date_of_birth")(lambda cls, v: _dob(v))

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @field_validator("current_password", mode="before")
    @classmethod
    def _blank_pw(cls, v: str | None) -> str | None:
        return v or None


class VisibilityIn(StrictModel):
    visibility: Visibility


class ApproveIn(StrictModel):
    duration_hours: Literal[1, 6, 24, 72, 168] = 24


class OtpIn(StrictModel):
    code: str = Field(min_length=4, max_length=10, pattern=r"^\d+$")


def validate_record_fields(title: str, details: str, information_type: str, information_date: str, visibility: str) -> dict:
    """Validation for multipart upload forms (FastAPI Form fields -> same rules as JSON)."""
    errors: dict[str, str] = {}
    title = (title or "").strip()
    details = (details or "").strip()
    if not 2 <= len(title) <= 200:
        errors["title"] = "Give the record a title (2–200 characters)."
    if len(details) > 10_000:
        errors["details"] = "Keep notes under 10,000 characters."
    try:
        itype = InformationType(information_type)
    except ValueError:
        errors["information_type"] = "Choose a record type."
        itype = InformationType.OTHER
    try:
        vis = Visibility(visibility)
    except ValueError:
        errors["visibility"] = "Choose public or private."
        vis = Visibility.PRIVATE
    try:
        d = date.fromisoformat(information_date)
        if d > utcnow().date():
            errors["information_date"] = "The record date can't be in the future."
        elif d < MIN_DOB:
            errors["information_date"] = "Enter a date after 1900."
    except (TypeError, ValueError):
        errors["information_date"] = "Enter the date of the record."
        d = utcnow().date()
    return {"errors": errors, "title": title, "details": details, "information_type": itype, "visibility": vis, "information_date": d}
