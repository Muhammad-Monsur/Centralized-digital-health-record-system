"""Medical records: create, update, visibility, archive - every change writes history.

Used by both the patient service (own records) and the provider service
(records under public / consent / emergency access). Callers do the
authorisation; this module enforces data rules and keeps the history trail.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Doctor, MedicalInformation, MedicalInformationHistory, User
from app.models.enums import HistoryChangeType, InformationType, RecordStatus, Visibility
from app.services.common.pagination import Page, paginate
from app.services.common.security import utcnow

# Fields tracked in history (and editable through update()).
TRACKED = ("title", "details", "information_type", "information_date", "visibility", "file_original_name")


def _val(v: Any) -> Any:
    if hasattr(v, "value"):
        return v.value
    if isinstance(v, date):
        return v.isoformat()
    return v


def _summ(field: str, v: Any) -> Any:
    """Keep history rows compact: long text is truncated for display."""
    v = _val(v)
    if field == "details" and isinstance(v, str) and len(v) > 280:
        return v[:277] + "..."
    return v


def write_history(db: Session, info: MedicalInformation, user_id: int, change: HistoryChangeType, changes: dict[str, dict[str, Any]]) -> None:
    db.add(MedicalInformationHistory(information_id=info.information_id, changed_by_user_id=user_id, change_type=change, changes=changes, changed_at=utcnow()))


def create(
    db: Session, *, patient_id: int, author_user_id: int, information_type: InformationType, title: str, details: str,
    information_date: date, visibility: Visibility, doctor_id: int | None = None, hospital_id: int | None = None,
    file: Any = None,
) -> MedicalInformation:
    info = MedicalInformation(
        patient_id=patient_id, doctor_id=doctor_id, hospital_id=hospital_id, information_type=information_type,
        title=title, details=details, information_date=information_date, visibility=visibility,
        created_by_user_id=author_user_id, status=RecordStatus.ACTIVE,
    )
    if file is not None:
        info.file_path, info.file_original_name, info.file_mime, info.file_size = file.stored_name, file.original_name, file.mime, file.size
    db.add(info)
    db.flush()
    changes = {f: {"old": None, "new": _summ(f, getattr(info, f))} for f in TRACKED if getattr(info, f) not in (None, "")}
    write_history(db, info, author_user_id, HistoryChangeType.CREATED, changes)
    return info


def update(db: Session, info: MedicalInformation, user_id: int, data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Apply only changed fields; returns the diff (empty = nothing changed)."""
    changes: dict[str, dict[str, Any]] = {}
    for field, new in data.items():
        if field not in TRACKED or field == "file_original_name":
            continue
        old = getattr(info, field)
        if _val(old) != _val(new):
            changes[field] = {"old": _summ(field, old), "new": _summ(field, new)}
            setattr(info, field, new)
    if changes:
        info.updated_by_user_id = user_id
        info.updated_at = utcnow()
        kind = HistoryChangeType.VISIBILITY_CHANGED if set(changes) == {"visibility"} else HistoryChangeType.UPDATED
        write_history(db, info, user_id, kind, changes)
    return changes


def attach_file(db: Session, info: MedicalInformation, user_id: int, file: Any) -> None:
    old_name = info.file_original_name
    info.file_path, info.file_original_name, info.file_mime, info.file_size = file.stored_name, file.original_name, file.mime, file.size
    info.updated_by_user_id = user_id
    info.updated_at = utcnow()
    write_history(db, info, user_id, HistoryChangeType.FILE_ATTACHED, {"file": {"old": old_name, "new": file.original_name}})


def archive(db: Session, info: MedicalInformation, user_id: int) -> None:
    info.status = RecordStatus.ARCHIVED
    info.updated_by_user_id = user_id
    info.updated_at = utcnow()
    write_history(db, info, user_id, HistoryChangeType.ARCHIVED, {"status": {"old": "active", "new": "archived"}})


def base_query(patient_id: int) -> Select:
    """Active records of one patient with everything the lists display, eager-loaded (no N+1)."""
    return (
        select(MedicalInformation)
        .where(MedicalInformation.patient_id == patient_id, MedicalInformation.status == RecordStatus.ACTIVE)
        .options(
            joinedload(MedicalInformation.doctor).joinedload(Doctor.user),
            joinedload(MedicalInformation.hospital),
            joinedload(MedicalInformation.created_by),
            joinedload(MedicalInformation.updated_by),
        )
    )


def list_records(
    db: Session, patient_id: int, *, page: int = 1, per_page: int = 10, public_only: bool = False,
    info_type: str | None = None, visibility: str | None = None, q: str | None = None,
) -> Page[MedicalInformation]:
    stmt = base_query(patient_id)
    if public_only:
        stmt = stmt.where(MedicalInformation.visibility == Visibility.PUBLIC)
    elif visibility in ("public", "private"):
        stmt = stmt.where(MedicalInformation.visibility == Visibility(visibility))
    if info_type and info_type in InformationType._value2member_map_:
        stmt = stmt.where(MedicalInformation.information_type == InformationType(info_type))
    if q:
        escaped = q.strip()[:80].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        stmt = stmt.where(or_(MedicalInformation.title.like(like), MedicalInformation.details.like(like)))
    stmt = stmt.order_by(MedicalInformation.information_date.desc(), MedicalInformation.information_id.desc())
    return paginate(db, stmt, page, per_page)


def get_record(db: Session, information_id: int, patient_id: int, *, with_history: bool = True) -> MedicalInformation | None:
    """Fetch one record *scoped to a patient* - the patient_id filter is the ownership check."""
    stmt = base_query(patient_id).where(MedicalInformation.information_id == information_id)
    if with_history:
        stmt = stmt.options(selectinload(MedicalInformation.history).joinedload(MedicalInformationHistory.changed_by))
    return db.scalar(stmt)


def history_view(info: MedicalInformation) -> list[dict[str, Any]]:
    """History rows shaped for templates / JSON (labels resolved, newest first)."""
    out = []
    for h in info.history:
        who: User = h.changed_by
        out.append({
            "change_type": h.change_type.value,
            "changed_at": h.changed_at,
            "by": who.full_name if who else "Unknown",
            "changes": [
                {"field": f.replace("_", " ").replace("information ", "").capitalize(), "old": c.get("old"), "new": c.get("new")}
                for f, c in (h.changes or {}).items()
            ],
        })
    return out


def uploader_kind(info: MedicalInformation) -> str:
    """'doctor', 'staff' or 'patient' - who uploaded/created the record."""
    if info.doctor_id is not None:
        return "doctor"
    return "staff" if info.hospital_id is not None else "patient"


def uploader_name(info: MedicalInformation) -> str:
    if info.doctor is not None:
        return info.doctor.user.full_name
    return info.created_by.full_name if info.created_by else "Unknown"


def author_label(info: MedicalInformation) -> str:
    """'Uploaded by' text: the person's name and role, plus the hospital for clinicians.
    e.g. "Ayesha Siddiqua (patient)" / "Dr. Tanvir Hasan (doctor, Lakeview General Hospital)"."""
    kind = uploader_kind(info)
    if kind == "patient":
        return f"{uploader_name(info)} (patient)"
    where = f", {info.hospital.name}" if info.hospital is not None else ""
    return f"{uploader_name(info)} ({kind}{where})"
