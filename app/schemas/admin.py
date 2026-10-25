"""Admin-side request schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import EmailStr, Field, ValidationInfo, field_validator

from app.models.enums import HospitalStatus, VerificationStatus
from app.schemas.common import CleanStr, Phone, StrictModel
from app.services.common.security import password_problems


def _lower(v: str) -> str:
    return v.lower()


class AccountCreateIn(StrictModel):
    """Create a doctor, staff member or hospital admin.

    Doctors: name, email, designation, password (+ licence number for professional verification).
    """

    kind: Literal["doctor", "staff", "hospital_admin"]
    full_name: CleanStr = Field(min_length=2, max_length=120)
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=10, max_length=128)
    phone: Phone | None = None
    hospital_id: int | None = Field(default=None, description="System admin only; hospital admins always create for their own hospital")
    designation: CleanStr | None = Field(default=None, max_length=100)
    license_number: CleanStr | None = Field(default=None, max_length=50)
    specialization: CleanStr | None = Field(default=None, max_length=100)
    position: CleanStr | None = Field(default=None, max_length=100)

    _email = field_validator("email")(lambda cls, v: _lower(v))

    @field_validator("phone", "designation", "license_number", "specialization", "position", mode="before")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v or None

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str, info: ValidationInfo) -> str:
        problems = password_problems(v, email=info.data.get("email", ""))
        if problems:
            raise ValueError(" ".join(problems))
        return v

    @field_validator("license_number")
    @classmethod
    def _licence(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.upper()
            import re

            if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-/]{3,49}", v):
                raise ValueError("Use letters, numbers and dashes, e.g. BMDC-A-12345.")
        return v


class AccountUpdateIn(StrictModel):
    full_name: CleanStr = Field(min_length=2, max_length=120)
    email: EmailStr = Field(max_length=255)
    phone: Phone | None = None
    designation: CleanStr | None = Field(default=None, max_length=100)
    specialization: CleanStr | None = Field(default=None, max_length=100)
    license_number: CleanStr | None = Field(default=None, max_length=50)
    position: CleanStr | None = Field(default=None, max_length=100)

    _email = field_validator("email")(lambda cls, v: _lower(v))

    @field_validator("phone", "designation", "license_number", "specialization", "position", mode="before")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v or None


class StatusIn(StrictModel):
    status: Literal["active", "inactive"]


class ResetPasswordIn(StrictModel):
    password: str = Field(min_length=10, max_length=128)

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        problems = password_problems(v)
        if problems:
            raise ValueError(" ".join(problems))
        return v


class VerifyIn(StrictModel):
    status: VerificationStatus
    note: CleanStr | None = Field(default=None, max_length=500)


class HospitalIn(StrictModel):
    name: CleanStr = Field(min_length=3, max_length=150)
    registration_number: CleanStr = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-/]+$")
    address: CleanStr = Field(min_length=5, max_length=255)
    phone: Phone


class HospitalUpdateIn(StrictModel):
    name: CleanStr = Field(min_length=3, max_length=150)
    address: CleanStr = Field(min_length=5, max_length=255)
    phone: Phone


class HospitalStatusIn(StrictModel):
    status: HospitalStatus


class RoleIn(StrictModel):
    role_name: str = Field(min_length=3, max_length=50, pattern=r"^[a-z][a-z0-9_]+$")
    description: CleanStr = Field(default="", max_length=255)


class RolePermissionsIn(StrictModel):
    permissions: list[str] = Field(max_length=200)


class RoleStatusIn(StrictModel):
    status: Literal["active", "inactive"]


class SettingsIn(StrictModel):
    values: dict[str, str] = Field(max_length=50)


class RestoreIn(StrictModel):
    confirm: str = Field(description='Type "RESTORE" to confirm')
