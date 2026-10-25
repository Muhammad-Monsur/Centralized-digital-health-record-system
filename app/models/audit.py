"""ACCESS_LOG, AUDIT_LOG, plus notifications, newsletter, contact messages and system settings."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import AccessType, NotificationKind, db_enum

if TYPE_CHECKING:
    from app.models.user import Patient, User


class AccessLog(Base):
    """Who touched which patient's data, and how. Shown to the patient as access history."""

    __tablename__ = "access_log"
    __table_args__ = (
        Index("ix_accesslog_patient_time", "patient_id", "accessed_at"),
        Index("ix_accesslog_user_time", "user_id", "accessed_at"),
    )

    access_log_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="RESTRICT"), nullable=False)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.patient_id", ondelete="RESTRICT"), nullable=False)
    access_type: Mapped[AccessType] = mapped_column(db_enum(AccessType, "access_type"), nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    # Added context so the patient can see *what* was accessed and *under what grant*.
    information_id: Mapped[int | None] = mapped_column(ForeignKey("medical_information.information_id", ondelete="SET NULL"), nullable=True)
    consent_id: Mapped[int | None] = mapped_column(ForeignKey("consent.consent_id", ondelete="SET NULL"), nullable=True)
    emergency_access_id: Mapped[int | None] = mapped_column(ForeignKey("emergency_access.emergency_access_id", ondelete="SET NULL"), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    user: Mapped[User] = relationship(lazy="raise")
    patient: Mapped[Patient] = relationship(lazy="raise")


class AuditLog(Base):
    """System-wide, append-only audit trail of security-relevant actions."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_entity", "entity", "entity_id"),
        Index("ix_audit_user_time", "user_id", "timestamp"),
        Index("ix_audit_action_time", "action", "timestamp"),
    )

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nullable: failed logins for unknown usernames have no user.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)
    # Added: request context. ``details`` never contains passwords, OTPs or record contents.
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Added: hospital scope so hospital admins see only their hospital's events.
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospital.hospital_id", ondelete="SET NULL"), nullable=True, index=True)

    user: Mapped[User | None] = relationship(lazy="raise")


class Notification(Base):
    """Added: in-app notices (e.g. "Dr X used emergency access to your records")."""

    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_user_read_time", "user_id", "is_read", "created_at"),)

    notification_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[NotificationKind] = mapped_column(db_enum(NotificationKind, "notification_kind"), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class NewsletterSubscriber(Base):
    """Added: newsletter signups (feature 11.12)."""

    __tablename__ = "newsletter_subscriber"

    subscriber_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    subscribed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class ContactMessage(Base):
    """Added: messages from the floating contact button (feature 11.10)."""

    __tablename__ = "contact_message"

    message_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)
    is_handled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SystemSetting(Base):
    """Added: runtime-editable configuration for the admin "system configuration" screen."""

    __tablename__ = "system_setting"

    setting_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    setting_value: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True)
