"""MEDICAL_INFORMATION and its per-record update history."""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin
from app.models.enums import HistoryChangeType, InformationType, RecordStatus, Visibility, db_enum

if TYPE_CHECKING:
    from app.models.user import Doctor, Hospital, Patient, User


class MedicalInformation(TimestampMixin, Base):
    __tablename__ = "medical_information"
    __table_args__ = (
        # Every patient-facing and doctor-facing list filters on these three columns.
        Index("ix_medinfo_patient_vis_status", "patient_id", "visibility", "status"),
        Index("ix_medinfo_patient_date", "patient_id", "information_date"),
    )

    information_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.patient_id", ondelete="RESTRICT"), nullable=False)
    # Nullable: a patient may upload their own documents (no doctor / hospital involved).
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctor.doctor_id", ondelete="SET NULL"), nullable=True, index=True)
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospital.hospital_id", ondelete="SET NULL"), nullable=True, index=True)
    information_type: Mapped[InformationType] = mapped_column(db_enum(InformationType, "information_type"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Stored file name on disk (random, never user-controlled). Original name kept separately.
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    information_date: Mapped[date] = mapped_column(Date, nullable=False)
    visibility: Mapped[Visibility] = mapped_column(db_enum(Visibility, "record_visibility"), nullable=False, default=Visibility.PRIVATE)
    status: Mapped[RecordStatus] = mapped_column(db_enum(RecordStatus, "record_status"), nullable=False, default=RecordStatus.ACTIVE)
    # Added for the "Last updated by" stamp and authorship.
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="RESTRICT"), nullable=False, index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True)

    patient: Mapped[Patient] = relationship(lazy="raise")
    doctor: Mapped[Doctor | None] = relationship(lazy="raise")
    hospital: Mapped[Hospital | None] = relationship(lazy="raise")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id], lazy="raise")
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_user_id], lazy="raise")
    history: Mapped[list[MedicalInformationHistory]] = relationship(
        back_populates="information", order_by="MedicalInformationHistory.changed_at.desc()", lazy="raise"
    )


class MedicalInformationHistory(Base):
    """Added: the per-record update history required by "Updates on every post".

    One row per change. ``changes`` holds ``{field: {"old": ..., "new": ...}}`` for
    the fields that changed, so the UI can render "who changed what, when".
    Rows are append-only (never updated or deleted by the application).
    """

    __tablename__ = "medical_information_history"
    __table_args__ = (Index("ix_medhist_info_changed", "information_id", "changed_at"),)

    history_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    information_id: Mapped[int] = mapped_column(ForeignKey("medical_information.information_id", ondelete="CASCADE"), nullable=False)
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="RESTRICT"), nullable=False, index=True)
    change_type: Mapped[HistoryChangeType] = mapped_column(db_enum(HistoryChangeType, "history_change_type"), nullable=False)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    information: Mapped[MedicalInformation] = relationship(back_populates="history")
    changed_by: Mapped[User] = relationship(lazy="joined")
