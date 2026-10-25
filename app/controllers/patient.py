"""Patient portal controller: HTML pages + JSON API. Every route requires the patient's own permissions."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import CurrentUser, Forbidden, get_optional_user, require_permissions
from app.middleware.rate_limit import client_ip
from app.controllers.portal import file_response, render_portal
from app.models import MedicalInformation
from app.models.enums import BloodGroup, Gender, InformationType, Visibility
from app.schemas.patient import ApproveIn, OtpIn, PatientRegisterIn, ProfileUpdateIn, VisibilityIn, validate_record_fields
from app.services import consent as consent_service
from app.services import patient as patient_service
from app.services import records
from app.services.common import file as file_service
from app.services.common import notification
from app.services.common import rate_limit as rl
from app.services.common.permissions import P
from app.services.common.security import utcnow
from app.services.common.sms import mask_phone
from app.views import render

pages = APIRouter(include_in_schema=False)
api = APIRouter(prefix="/api/v1", tags=["patient"])


def current_patient(cu: CurrentUser = Depends(require_permissions(P.OWN_RECORDS_READ))) -> CurrentUser:
    if cu.patient is None:
        raise Forbidden("This area is for patients.")
    return cu


def _err(e: Exception) -> JSONResponse:
    fields = getattr(e, "fields", {}) or {}
    body: dict[str, Any] = {"detail": getattr(e, "message", "Something went wrong.")}
    if fields:
        body["fields"] = fields
    return JSONResponse(body, status_code=getattr(e, "status_code", 400))


def record_json(info: MedicalInformation, me_user_id: int) -> dict[str, Any]:
    return {
        "id": info.information_id,
        "title": info.title,
        "type": info.information_type.value,
        "type_label": info.information_type.value.replace("_", " ").capitalize(),
        "date": info.information_date.strftime("%d %b %Y"),
        "visibility": info.visibility.value,
        "author": records.author_label(info),
        "has_file": bool(info.file_path),
        "updated_at": (info.updated_at.isoformat() + "Z") if info.updated_at else None,
        "url": f"/patient/records/{info.information_id}",
    }


TYPE_OPTIONS = [(t.value, t.value.replace("_", " ").capitalize()) for t in InformationType]


# ============================================================ registration (public)

@pages.get("/register")
def register_page(request: Request, user: CurrentUser | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse(user.portal, status_code=303)
    return render(request, "auth/register.html", {"genders": list(Gender), "blood_groups": list(BloodGroup), "today": utcnow().date().isoformat()})


@api.post("/patients/register", status_code=201, summary="Register a patient account (issues a UPI)")
def register(body: PatientRegisterIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    limit = rl.hit("register", ip, 10, 3600)
    if not limit.allowed:
        return JSONResponse({"detail": "Too many sign-ups from this network. Try again later."}, status_code=429)
    try:
        patient_service.register(db, body, ip)
    except patient_service.PatientError as e:
        return _err(e)
    return {"redirect": "/login?reason=registered", "detail": "Account created."}


# ============================================================ pages

@pages.get("/patient")
def dashboard(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(current_patient)):
    d = patient_service.dashboard(db, cu.patient)
    return render_portal(request, db, cu, "patient/dashboard.html",
                         {"d": d, "patient": cu.patient, "access_labels": patient_service.ACCESS_LABELS, "author": records.author_label},
                         kind="patient", counts={"pending": d.pending_requests})


@pages.get("/patient/records")
def records_page(request: Request, page: int = Query(1, ge=1), type: str | None = None, visibility: str | None = None,
                 q: str | None = Query(None, max_length=80), db: Session = Depends(get_db), cu: CurrentUser = Depends(current_patient)):
    pg = records.list_records(db, cu.patient.patient_id, page=page, per_page=10, info_type=type, visibility=visibility, q=q)
    return render_portal(request, db, cu, "patient/records.html",
                         {"page": pg, "rows": [record_json(r, cu.id) for r in pg.items], "types": TYPE_OPTIONS,
                          "filters": {"type": type or "", "visibility": visibility or "", "q": q or ""}}, kind="patient")


@pages.get("/patient/records/new")
def upload_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.OWN_RECORDS_UPLOAD))):
    if cu.patient is None:
        raise Forbidden()
    return render_portal(request, db, cu, "patient/upload.html",
                         {"types": TYPE_OPTIONS, "today": utcnow().date().isoformat(), "accept": file_service.ACCEPT_ATTR,
                          "max_mb": settings.max_upload_mb}, kind="patient")


@pages.get("/patient/records/{information_id}")
def record_page(information_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(current_patient)):
    try:
        info = patient_service.get_own_record(db, cu.patient, information_id)
    except patient_service.PatientError:
        return render(request, "errors/404.html", {"title": "Record not found", "message": "This record doesn't exist or isn't yours."}, status_code=404)
    can_delete = info.created_by_user_id == cu.id and info.doctor_id is None
    return render_portal(request, db, cu, "patient/record.html",
                         {"r": info, "history": records.history_view(info), "author": records.author_label(info),
                          "own_upload": can_delete, "size": file_service.human_size(info.file_size),
                          "labels": patient_service.HISTORY_LABELS, "patient": cu.patient}, kind="patient")


@pages.get("/patient/records/{information_id}/file")
def record_file(information_id: int, inline: bool = False, db: Session = Depends(get_db), cu: CurrentUser = Depends(current_patient)):
    try:
        info = patient_service.get_own_record(db, cu.patient, information_id)
        if not info.file_path:
            raise patient_service.PatientError("No file", 404)
        return file_response(info, inline)
    except (patient_service.PatientError, file_service.FileError):
        return JSONResponse({"detail": "File not found."}, status_code=404)


@pages.get("/patient/consent")
def consent_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.OWN_CONSENT))):
    if cu.patient is None:
        raise Forbidden()
    ov = consent_service.patient_overview(db, cu.patient.patient_id)
    return render_portal(request, db, cu, "patient/consent.html",
                         {"ov": ov, "durations": consent_service.ALLOWED_DURATIONS, "default_hours": settings.consent_default_hours,
                          "phone_masked": mask_phone(cu.user.phone), "now": utcnow()},
                         kind="patient", counts={"pending": len(ov["pending"])})


@pages.get("/patient/access-history")
def access_history_page(request: Request, page: int = Query(1, ge=1), emergency: bool = False, db: Session = Depends(get_db),
                        cu: CurrentUser = Depends(require_permissions(P.OWN_ACCESS_HISTORY))):
    if cu.patient is None:
        raise Forbidden()
    pg = patient_service.access_history(db, cu.patient, page=page, only_emergency=emergency)
    titles = patient_service.record_titles(db, cu.patient, {a.information_id for a in pg.items if a.information_id})
    return render_portal(request, db, cu, "patient/access_history.html",
                         {"page": pg, "titles": titles, "labels": patient_service.ACCESS_LABELS, "emergency_only": emergency,
                          "emergencies": patient_service.emergency_events(db, cu.patient, 5), "now": utcnow()}, kind="patient")


@pages.get("/patient/profile")
def profile_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.OWN_PROFILE))):
    if cu.patient is None:
        raise Forbidden()
    return render_portal(request, db, cu, "patient/profile.html",
                         {"p": cu.patient, "u": cu.user, "genders": list(Gender), "blood_groups": list(BloodGroup),
                          "today": utcnow().date().isoformat()}, kind="patient")


@pages.get("/patient/notifications")
def notifications_page(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db), cu: CurrentUser = Depends(current_patient)):
    pg = notification.list_for(db, cu.id, page)
    return render_portal(request, db, cu, "common/notifications.html", {"page": pg, "base": "/patient"}, kind="patient")


# ============================================================ JSON API

@api.get("/patient/records", summary="List own records (filter, search, paginate)")
def api_records(page: int = Query(1, ge=1), per_page: int = Query(10, ge=1, le=50), type: str | None = None,
                visibility: str | None = None, q: str | None = Query(None, max_length=80),
                db: Session = Depends(get_db), cu: CurrentUser = Depends(current_patient)):
    pg = records.list_records(db, cu.patient.patient_id, page=page, per_page=per_page, info_type=type, visibility=visibility, q=q)
    return {"items": [record_json(r, cu.id) for r in pg.items], **pg.meta()}


@api.post("/patient/records", status_code=201, summary="Upload a document / add a record")
async def api_upload(request: Request, title: str = Form(""), details: str = Form(""), information_type: str = Form(""),
                     information_date: str = Form(""), visibility: str = Form("private"), file: UploadFile | None = File(None),
                     db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.OWN_RECORDS_UPLOAD))):
    if cu.patient is None:
        raise Forbidden()
    fields = validate_record_fields(title, details, information_type, information_date, visibility)
    if fields["errors"]:
        return JSONResponse({"detail": next(iter(fields["errors"].values())), "fields": fields["errors"]}, status_code=422)
    lim = rl.hit("upload", str(cu.id), 30, 3600)
    if not lim.allowed:
        return JSONResponse({"detail": "Upload limit reached. Try again in an hour."}, status_code=429)
    try:
        info = await patient_service.upload_record(db, cu.patient, fields, file, client_ip(request))
    except patient_service.PatientError as e:
        return _err(e)
    return {"id": info.information_id, "redirect": f"/patient/records/{info.information_id}?uploaded=1", "detail": "Document uploaded."}


@api.patch("/patient/records/{information_id}/visibility", summary="Set a record public or private")
def api_visibility(information_id: int, body: VisibilityIn, request: Request, db: Session = Depends(get_db),
                   cu: CurrentUser = Depends(require_permissions(P.OWN_RECORDS_VISIBILITY))):
    if cu.patient is None:
        raise Forbidden()
    try:
        info = patient_service.set_visibility(db, cu.patient, information_id, body.visibility, client_ip(request))
    except patient_service.PatientError as e:
        return _err(e)
    label = "public: verified clinicians can see it" if info.visibility == Visibility.PUBLIC else "private: only doctors you approve can see it"
    return {"visibility": info.visibility.value, "detail": f"Record is now {label}."}


@api.delete("/patient/records/{information_id}", summary="Delete a document you uploaded")
def api_delete(information_id: int, request: Request, db: Session = Depends(get_db),
               cu: CurrentUser = Depends(require_permissions(P.OWN_RECORDS_UPLOAD))):
    if cu.patient is None:
        raise Forbidden()
    try:
        patient_service.archive_own_upload(db, cu.patient, information_id, client_ip(request))
    except patient_service.PatientError as e:
        return _err(e)
    return {"detail": "Document deleted.", "redirect": "/patient/records"}


@api.put("/patient/profile", summary="Update profile (password needed to change phone/email)")
def api_profile(body: ProfileUpdateIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.OWN_PROFILE))):
    if cu.patient is None:
        raise Forbidden()
    try:
        changed = patient_service.update_profile(db, cu.patient, body, client_ip(request))
    except patient_service.PatientError as e:
        return _err(e)
    return {"detail": "Profile saved." if changed else "No changes to save."}


# ---- consent

def _consent_patient(cu: CurrentUser = Depends(require_permissions(P.OWN_CONSENT))) -> CurrentUser:
    if cu.patient is None:
        raise Forbidden()
    return cu


@api.post("/patient/consent/requests/{request_id}/approve", summary="Approve an access request (sends SMS code)")
def api_approve(request_id: int, body: ApproveIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(_consent_patient)):
    try:
        started = consent_service.approve(db, patient=cu.patient, request_id=request_id, duration_hours=body.duration_hours, ip=client_ip(request))
        db.commit()
    except (consent_service.ConsentError, consent_service.otp_service.OtpError) as e:
        db.rollback()
        return _err(e)
    return {"consent_id": started.consent_id, "expires_in": started.expires_in, "sent_to": started.sent_to,
            "detail": f"We sent a 6-digit code to {started.sent_to}."}


@api.post("/patient/consent/{consent_id}/verify", summary="Confirm approval with the SMS code")
def api_verify(consent_id: int, body: OtpIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(_consent_patient)):
    lim = rl.hit("otp-verify", str(cu.id), 20, 900)
    if not lim.allowed:
        return JSONResponse({"detail": "Too many attempts. Wait a few minutes."}, status_code=429)
    try:
        c = consent_service.verify_otp(db, patient=cu.patient, consent_id=consent_id, code=body.code, ip=client_ip(request))
        db.commit()
    except consent_service.ConsentError as e:
        return _err(e)
    return {"detail": f"Access granted to {c.doctor.user.full_name}.", "redirect": "/patient/consent?granted=1"}


@api.post("/patient/consent/{consent_id}/resend", summary="Send a new SMS code")
def api_resend(consent_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(_consent_patient)):
    try:
        issued = consent_service.resend_otp(db, patient=cu.patient, consent_id=consent_id, ip=client_ip(request))
        db.commit()
    except (consent_service.ConsentError, consent_service.otp_service.OtpError) as e:
        db.rollback()
        return _err(e)
    return {"detail": f"New code sent to {issued.sent_to}.", "expires_in": issued.expires_in}


@api.post("/patient/consent/requests/{request_id}/reject", summary="Decline an access request")
def api_reject(request_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(_consent_patient)):
    try:
        consent_service.reject(db, patient=cu.patient, request_id=request_id, ip=client_ip(request))
        db.commit()
    except consent_service.ConsentError as e:
        db.rollback()
        return _err(e)
    return {"detail": "Request declined."}


@api.post("/patient/consent/{consent_id}/revoke", summary="Revoke consent immediately")
def api_revoke(consent_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(_consent_patient)):
    try:
        consent_service.revoke(db, patient=cu.patient, consent_id=consent_id, ip=client_ip(request))
        db.commit()
    except consent_service.ConsentError as e:
        db.rollback()
        return _err(e)
    return {"detail": "Access revoked. The doctor can no longer see your private records."}


@api.post("/notifications/read", summary="Mark all notifications read")
def api_notifications_read(db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions())):
    n = notification.mark_all_read(db, cu.id)
    db.commit()
    return {"detail": f"Marked {n} notification{'s' if n != 1 else ''} as read."}
