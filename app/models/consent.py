"""ACCESS_REQUEST, CONSENT, OTP_VERIFICATION, EMERGENCY_ACCESS."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import AccessRequestStatus, ConsentStatus, db_enum

if TYPE_CHECKING:
    from app.models.user import Doctor, Hospital, Patient


class AccessRequest(Base):
    __tablename__ = "access_request"
    __table_args__ = (
        Index("ix_accreq_patient_status", "patient_id", "status"),
        Index("ix_accreq_doctor_status", "doctor_id", "status"),
    )

    request_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.patient_id", ondelete="RESTRICT"), nullable=False)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.doctor_id", ondelete="RESTRICT"), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    status: Mapped[AccessRequestStatus] = mapped_column(db_enum(AccessRequestStatus, "access_request_status"), nullable=False, default=AccessRequestStatus.PENDING)
    # The request itself lapses if the patient does not answer in time.
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Added: when the patient answered (approve/reject).
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Added: the doctor's sign-in session the request was made from (SHA-256 reference).
    session_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    patient: Mapped[Patient] = relationship(lazy="raise")
    doctor: Mapped[Doctor] = relationship(lazy="raise")


class Consent(Base):
    __tablename__ = "consent"
    __table_args__ = (
        # Hot path: "does doctor D have an active, unexpired consent for patient P?"
        Index("ix_consent_patient_doctor_status_exp", "patient_id", "doctor_id", "status", "expires_at"),
        Index("ix_consent_doctor_status", "doctor_id", "status"),
    )

    consent_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("access_request.request_id", ondelete="RESTRICT"), unique=True, nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.patient_id", ondelete="RESTRICT"), nullable=False)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.doctor_id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[ConsentStatus] = mapped_column(db_enum(ConsentStatus, "consent_status"), nullable=False, default=ConsentStatus.PENDING_OTP)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # set when OTP verified
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Added: the duration the patient chose at approval time (applied once the OTP is verified).
    duration_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=24)
    # Added: consent is valid only in the doctor's session that requested it.
    session_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    request: Mapped[AccessRequest] = relationship(lazy="raise")
    patient: Mapped[Patient] = relationship(lazy="raise")
    doctor: Mapped[Doctor] = relationship(lazy="raise")


class OtpVerification(Base):
    __tablename__ = "otp_verification"

    otp_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consent_id: Mapped[int] = mapped_column(ForeignKey("consent.consent_id", ondelete="CASCADE"), nullable=False, index=True)
    otp_hash: Mapped[str] = mapped_column(String(128), nullable=False)  # HMAC-SHA256, never the code itself
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # set => used (single use)
    # Added: wrong-guess counter; the OTP is burned after OTP_MAX_ATTEMPTS.
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # Added: superseded by a resend, or burned by too many attempts.
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmergencyAccess(Base):
    __tablename__ = "emergency_access"
    __table_args__ = (Index("ix_emerg_patient_doctor_exp", "patient_id", "doctor_id", "expires_at"),)

    emergency_access_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.patient_id", ondelete="RESTRICT"), nullable=False)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctor.doctor_id", ondelete="RESTRICT"), nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospital.hospital_id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)
    # Added: emergency access is temporary; this is when it stops working.
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Added: an admin (or the patient) can end it early.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Added: emergency access also ends with the doctor's sign-in session.
    session_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    patient: Mapped[Patient] = relationship(lazy="raise")
    doctor: Mapped[Doctor] = relationship(lazy="raise")
    hospital: Mapped[Hospital] = relationship(lazy="raise")
