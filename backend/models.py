
import datetime

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer,
                         String, Text)
from sqlalchemy.orm import relationship

from .database import Base


def now():
    return datetime.datetime.utcnow()

# Abdullah hospital base add korbe 


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



