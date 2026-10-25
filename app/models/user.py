"""USER, PATIENT, DOCTOR, HEALTHCARE_STAFF, HOSPITAL, HOSPITAL_ADMIN, SYSTEM_ADMIN."""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin
from app.models.enums import (
    BloodGroup,
    Gender,
    HospitalStatus,
    UserStatus,
    VerificationStatus,
    Visibility,
    db_enum,
)

if TYPE_CHECKING:
    from app.models.rbac import UserRole


class User(TimestampMixin, Base):
    __tablename__ = "user"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Added: the schema has no name column, but every portal must show a person's name.
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Optional for staff accounts created by admins; required for patients (consent OTPs) by
    # the patient schemas and service.
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[UserStatus] = mapped_column(db_enum(UserStatus, "user_status"), nullable=False, default=UserStatus.ACTIVE, index=True)
    # Added for failed-login protection (per-account lockout survives restarts).
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Added: set when an administrator chose the password (account creation / reset). The user
    # must pick their own before doing anything else, so the admin can't keep using the account.
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    # Lazy by default: loaded explicitly (selectinload) where needed - auth and admin lists -
    # so lists that merely show a person's name don't also fetch roles and permissions.
    roles: Mapped[list[UserRole]] = relationship(back_populates="user", cascade="all, delete-orphan", lazy="select")
    patient: Mapped[Patient | None] = relationship(back_populates="user", uselist=False)
    doctor: Mapped[Doctor | None] = relationship(back_populates="user", uselist=False)
    staff: Mapped[HealthcareStaff | None] = relationship(back_populates="user", uselist=False)
    hospital_admin: Mapped[HospitalAdmin | None] = relationship(back_populates="user", uselist=False)
    system_admin: Mapped[SystemAdmin | None] = relationship(back_populates="user", uselist=False)

    @property
    def role_names(self) -> set[str]:
        from app.models.enums import RoleStatus

        return {ur.role.role_name for ur in self.roles if ur.role is not None and ur.role.status == RoleStatus.ACTIVE}


class Hospital(TimestampMixin, Base):
    __tablename__ = "hospital"

    hospital_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    registration_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[HospitalStatus] = mapped_column(db_enum(HospitalStatus, "hospital_status"), nullable=False, default=HospitalStatus.ACTIVE, index=True)


class Patient(TimestampMixin, Base):
    __tablename__ = "patient"

    patient_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="RESTRICT"), unique=True, nullable=False)
    upi: Mapped[str] = mapped_column("UPI", String(20), unique=True, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[Gender] = mapped_column(db_enum(Gender, "gender"), nullable=False)
    blood_group: Mapped[BloodGroup] = mapped_column(db_enum(BloodGroup, "blood_group"), nullable=False, default=BloodGroup.UNKNOWN)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_visibility: Mapped[Visibility] = mapped_column(db_enum(Visibility, "profile_visibility"), nullable=False, default=Visibility.PRIVATE)

    user: Mapped[User] = relationship(back_populates="patient", lazy="joined")


class Doctor(TimestampMixin, Base):
    __tablename__ = "doctor"
    __table_args__ = (Index("ix_doctor_hospital_verification", "hospital_id", "verification_status"),)

    doctor_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="RESTRICT"), unique=True, nullable=False)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospital.hospital_id", ondelete="RESTRICT"), nullable=False)
    license_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    specialization: Mapped[str] = mapped_column(String(100), nullable=False)
    # Added: job title set by the hospital admin when creating the account (e.g. "Consultant").
    designation: Mapped[str] = mapped_column(String(100), nullable=False, server_default="Medical Officer")
    verification_status: Mapped[VerificationStatus] = mapped_column(
        db_enum(VerificationStatus, "verification_status"), nullable=False, default=VerificationStatus.PENDING
    )
    # Added: why a verification was rejected (shown to the doctor).
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="doctor", lazy="joined")
    hospital: Mapped[Hospital] = relationship(lazy="joined")


class HealthcareStaff(TimestampMixin, Base):
    """Added: the "Healthcare Staff" role needs a hospital link to scope its permissions."""

    __tablename__ = "healthcare_staff"

    staff_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="RESTRICT"), unique=True, nullable=False)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospital.hospital_id", ondelete="RESTRICT"), nullable=False, index=True)
    position: Mapped[str] = mapped_column(String(100), nullable=False)

    user: Mapped[User] = relationship(back_populates="staff", lazy="joined")
    hospital: Mapped[Hospital] = relationship(lazy="joined")


class HospitalAdmin(TimestampMixin, Base):
    __tablename__ = "hospital_admin"

    hospital_admin_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="RESTRICT"), unique=True, nullable=False)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospital.hospital_id", ondelete="RESTRICT"), nullable=False, index=True)

    user: Mapped[User] = relationship(back_populates="hospital_admin", lazy="joined")
    hospital: Mapped[Hospital] = relationship(lazy="joined")


class SystemAdmin(TimestampMixin, Base):
    __tablename__ = "system_admin"

    system_admin_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="RESTRICT"), unique=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="system_admin", lazy="joined")
