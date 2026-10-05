
import datetime

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer,
                         String, Text)
from sqlalchemy.orm import relationship

from .database import Base


def now():
    return datetime.datetime.utcnow()

# hospital table  
class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    address = Column(String(255), default="")
    phone = Column(String(30), default="")
    status = Column(String(20), default="Active")  # Active / Suspended

    doctors = relationship("Doctor", back_populates="hospital")
    admins = relationship("HospitalAdminProfile", back_populates="hospital")



class User(Base):
   
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    # role tells us which profile table to join, and which portal/profile page to serve
    role = Column(String(20), nullable=False)  # patient | doctor | hospital_admin | system_admin
    full_name = Column(String(150), nullable=False)
    phone = Column(String(30), default="")
    gender = Column(String(20), default="")
    status = Column(String(20), default="Active")  # Active / Blocked
    created_at = Column(DateTime, default=now)

    patient_profile = relationship("Patient", back_populates="user", uselist=False)
    doctor_profile = relationship("Doctor", back_populates="user", uselist=False)
    hospital_admin_profile = relationship("HospitalAdminProfile", back_populates="user", uselist=False)
    system_admin_profile = relationship("SystemAdminProfile", back_populates="user", uselist=False)
    roles = relationship("UserRole", back_populates="user")



class Role(Base):
   
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255), default="")


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), default="")


class UserRole(Base):
    # Many-to-many: a user can hold more than one role.
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)

    user = relationship("User", back_populates="roles")
    role = relationship("Role")


class RolePermission(Base):
    # Many-to-many: a role can hold more than one permission.
    __tablename__ = "role_permissions"

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    permission_id = Column(Integer, ForeignKey("permissions.id"), nullable=False)

    role = relationship("Role")
    permission = relationship("Permission")


# patient base Tahia add korbe 



# doctor base
class Doctor(Base):
    """Doctor-specific fields. One-to-one with User (role='doctor').
    IMPORTANT (SRS 3.2 + 3.4.2): doctors do NOT self-register - a Hospital
    Admin creates this row (see routers/hospital_admin.py)."""
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    specialization = Column(String(100), default="")
    verification_status = Column(String(20), default="Active")  # Active | Blocked

    user = relationship("User", back_populates="doctor_profile")
    hospital = relationship("Hospital", back_populates="doctors")


# hospital admin profile  table 
class HospitalAdminProfile(Base):
    __tablename__ = "hospital_admins"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    user = relationship("User", back_populates="hospital_admin_profile")
    hospital = relationship("Hospital", back_populates="admins")



class SystemAdminProfile(Base):
    __tablename__ = "system_admins"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    user = relationship("User", back_populates="system_admin_profile")


# medical info base Tahia add korbe




# Access request base suzana add korbe



class OTPVerification(Base):
   
    __tablename__ = "otp_verifications"

    id = Column(Integer, primary_key=True)
    consent_id = Column(Integer, ForeignKey("consents.id"), nullable=False)
    otp_hash = Column(String(255), nullable=False)
    generated_at = Column(DateTime, default=now)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)



# consent base Tahia add korbe





# emergency access base suzana add korbe


class AccessLog(Base):
   
    __tablename__ = "access_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # who accessed it
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    access_type = Column(String(50), nullable=False)  # e.g. "viewed_public", "viewed_private", "emergency"
    accessed_at = Column(DateTime, default=now)



class AuditLog(Base):
    
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(150), nullable=False)
    entity = Column(String(50), default="")
    entity_id = Column(Integer, nullable=True)
    details = Column(String(255), default="")
    timestamp = Column(DateTime, default=now)
