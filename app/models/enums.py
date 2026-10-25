"""Enumerations shared by models, schemas and services.

Values (not names) are stored in MySQL ENUM columns, so they are stable,
human-readable strings.
"""
from __future__ import annotations

import enum


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class UserStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"  # e.g. doctor awaiting verification
    INACTIVE = "inactive"  # deactivated by an admin
    LOCKED = "locked"  # administratively locked


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNDISCLOSED = "undisclosed"


class BloodGroup(StrEnum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"
    UNKNOWN = "unknown"


class Visibility(StrEnum):
    PUBLIC = "public"  # visible to verified clinicians who look up the UPI
    PRIVATE = "private"  # visible to clinicians only with active consent / emergency access


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class HospitalStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class InformationType(StrEnum):
    DIAGNOSIS = "diagnosis"
    PRESCRIPTION = "prescription"
    LAB_REPORT = "lab_report"
    IMAGING = "imaging"
    VACCINATION = "vaccination"
    ALLERGY = "allergy"
    SURGERY = "surgery"
    CLINICAL_NOTE = "clinical_note"
    OTHER = "other"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"  # soft-deleted: hidden from views, kept for audit


class AccessRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ConsentStatus(StrEnum):
    PENDING_OTP = "pending_otp"  # patient approved, waiting for OTP confirmation
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    ENDED = "ended"  # the doctor's sign-in session ended (signed out or timed out)


class RoleStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AccessType(StrEnum):
    VIEW_PROFILE = "view_profile"
    VIEW_PUBLIC = "view_public"
    VIEW_PRIVATE = "view_private"  # under consent
    VIEW_EMERGENCY = "view_emergency"  # under emergency access
    DOWNLOAD_FILE = "download_file"
    CREATE_RECORD = "create_record"
    UPDATE_RECORD = "update_record"


class HistoryChangeType(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    VISIBILITY_CHANGED = "visibility_changed"
    FILE_ATTACHED = "file_attached"
    ARCHIVED = "archived"


class NotificationKind(StrEnum):
    ACCESS_REQUEST = "access_request"
    CONSENT = "consent"
    EMERGENCY = "emergency"
    RECORD = "record"
    ACCOUNT = "account"
    SYSTEM = "system"


class RoleName(StrEnum):
    """Built-in role names (the ROLE table may hold more)."""

    PATIENT = "patient"
    DOCTOR = "doctor"
    STAFF = "healthcare_staff"
    HOSPITAL_ADMIN = "hospital_admin"
    SYSTEM_ADMIN = "system_admin"


def db_enum(enum_cls: type[enum.Enum], name: str):
    """SQLAlchemy Enum storing ``.value`` (not ``.name``) in a MySQL ENUM."""
    from sqlalchemy import Enum as SAEnum

    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        validate_strings=True,
    )
