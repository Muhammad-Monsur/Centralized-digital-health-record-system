"""Import every model so ``Base.metadata`` is complete (Alembic, tests)."""
from app.models.audit import AccessLog, AuditLog, ContactMessage, NewsletterSubscriber, Notification, SystemSetting
from app.models.consent import AccessRequest, Consent, EmergencyAccess, OtpVerification
from app.models.medical import MedicalInformation, MedicalInformationHistory
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.user import Doctor, HealthcareStaff, Hospital, HospitalAdmin, Patient, SystemAdmin, User

__all__ = [
    "AccessLog", "AccessRequest", "AuditLog", "Consent", "ContactMessage", "Doctor", "EmergencyAccess",
    "HealthcareStaff", "Hospital", "HospitalAdmin", "MedicalInformation", "MedicalInformationHistory",
    "NewsletterSubscriber", "Notification", "OtpVerification", "Patient", "Permission", "Role",
    "RolePermission", "SystemAdmin", "SystemSetting", "User", "UserRole",
]
