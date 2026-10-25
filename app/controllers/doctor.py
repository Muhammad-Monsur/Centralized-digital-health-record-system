"""Doctor / staff portal controller. Doctors don't self-register: accounts come from hospital admins."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.controllers.patient import TYPE_OPTIONS, _err
from app.controllers.portal import file_response, render_portal
from app.database import get_db
from app.middleware.auth import CurrentUser, Forbidden, require_permissions
from app.middleware.rate_limit import client_ip
from app.models import Patient
from app.schemas.patient import validate_record_fields
from app.schemas.provider import AccessRequestIn, EmergencyIn, ProviderProfileIn, RecordUpdateIn, UpiLookupIn
from app.services import consent as consent_service
from app.services import provider as svc
from app.services import records
from app.services.common import file as file_service
from app.services.common import notification
from app.services.common import rate_limit as rl
from app.services.common.permissions import P
from app.services.common.security import utcnow
from app.views import render

pages = APIRouter(include_in_schema=False)
api = APIRouter(prefix="/api/v1/doctor", tags=["doctor"])


def clinician(cu: CurrentUser = Depends(require_permissions(P.PROVIDER_PROFILE))) -> CurrentUser:
    if not cu.is_clinician:
        raise Forbidden("This area is for doctors and healthcare staff.")
    return cu


def _patient(db: Session, upi: str) -> Patient:
    return svc.find_patient(db, upi)


def _age(dob) -> int:
    t = utcnow().date()
    return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))


def _not_found(request: Request, message: str):
    return render(request, "errors/404.html", {"title": "Not found", "message": message}, status_code=404)


# ================================================================ pages

@pages.get("/doctor")
def dashboard(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(clinician)):
    d = svc.dashboard(db, cu)
    return render_portal(request, db, cu, "doctor/dashboard.html", {"d": d, "now": utcnow()}, kind="doctor")


@pages.get("/doctor/search")
def search_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.PATIENT_SEARCH))):
    return render_portal(request, db, cu, "doctor/search.html", {}, kind="doctor")


@pages.get("/doctor/patients/{upi}")
def patient_page(upi: str, request: Request, page: int = Query(1, ge=1), type: str | None = None,
                 db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.PATIENT_SEARCH, P.RECORDS_PUBLIC_READ))):
    if not rl.hit("upi-view", str(cu.id), 120, 600).allowed:
        return render(request, "errors/500.html", {"status": 429, "title": "Slow down", "message": "Too many patient lookups. Wait a few minutes."}, status_code=429)
    try:
        patient = _patient(db, upi)
        ctx = svc.access_for(db, cu, patient)
        view = svc.patient_view(db, cu, patient, ctx, page=page, ip=client_ip(request), info_type=type)
    except svc.ProviderError as e:
        return _not_found(request, e.message)
    return render_portal(request, db, cu, "doctor/patient.html", {
        "p": patient, "ctx": ctx, "age": _age(patient.date_of_birth), "types": TYPE_OPTIONS, "type": type or "",
        "rows": view["page"].items, "page": view["page"], "hidden_private": view["hidden_private"],
        "show_demographics": view["show_demographics"], "pending_request": view["pending_request"],
        "author": records.author_label, "now": utcnow(), "emergency_minutes": settings.emergency_access_minutes,
    }, kind="doctor")


@pages.get("/doctor/patients/{upi}/records/new")
def new_record_page(upi: str, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.RECORDS_CREATE))):
    if not rl.hit("upi-view", str(cu.id), 120, 600).allowed:
        return render(request, "errors/500.html", {"status": 429, "title": "Slow down", "message": "Too many patient lookups. Wait a few minutes."}, status_code=429)
    try:
        patient = _patient(db, upi)
    except svc.ProviderError as e:
        return _not_found(request, e.message)
    # The page shows the patient's name, so opening it is an access like any other.
    from app.models.enums import AccessType
    from app.services.common.audit import access

    access(db, user_id=cu.id, patient_id=patient.patient_id, access_type=AccessType.VIEW_PROFILE, ip=client_ip(request))
    db.commit()
    return render_portal(request, db, cu, "doctor/record_form.html", {
        "p": patient, "types": TYPE_OPTIONS, "today": utcnow().date().isoformat(), "accept": file_service.ACCEPT_ATTR,
        "max_mb": settings.max_upload_mb, "r": None}, kind="doctor")


@pages.get("/doctor/patients/{upi}/records/{information_id}")
def record_page(upi: str, information_id: int, request: Request, edit: bool = False, db: Session = Depends(get_db),
                cu: CurrentUser = Depends(require_permissions(P.RECORDS_PUBLIC_READ))):
    try:
        patient = _patient(db, upi)
        ctx = svc.access_for(db, cu, patient)
        info = svc.get_record_for(db, cu, patient, ctx, information_id, ip=client_ip(request))
    except svc.ProviderError as e:
        return _not_found(request, e.message)
    editable = svc.can_edit(cu, info, ctx)
    if edit and editable:
        return render_portal(request, db, cu, "doctor/record_form.html", {
            "p": patient, "types": TYPE_OPTIONS, "today": utcnow().date().isoformat(), "r": info,
            "accept": file_service.ACCEPT_ATTR, "max_mb": settings.max_upload_mb}, kind="doctor")
    from app.services.patient import HISTORY_LABELS

    return render_portal(request, db, cu, "doctor/record.html", {
        "p": patient, "r": info, "ctx": ctx, "history": records.history_view(info), "author": records.author_label(info),
        "editable": editable, "size": file_service.human_size(info.file_size), "labels": HISTORY_LABELS}, kind="doctor")


@pages.get("/doctor/patients/{upi}/records/{information_id}/file")
def record_file(upi: str, information_id: int, request: Request, inline: bool = False, db: Session = Depends(get_db),
                cu: CurrentUser = Depends(require_permissions(P.RECORDS_PUBLIC_READ))):
    try:
        patient = _patient(db, upi)
        ctx = svc.access_for(db, cu, patient)
        info = svc.get_record_for(db, cu, patient, ctx, information_id, ip=client_ip(request), download=True)
        if not info.file_path:
            raise svc.ProviderError("No file", 404)
        return file_response(info, inline)
    except (svc.ProviderError, file_service.FileError):
        return JSONResponse({"detail": "File not found."}, status_code=404)


@pages.get("/doctor/requests")
def requests_page(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.ACCESS_REQUEST))):
    pg = svc.my_requests(db, cu, page)
    consents = svc.consents_by_request(db, [r.request_id for r in pg.items])
    return render_portal(request, db, cu, "doctor/requests.html", {"page": pg, "consents": consents, "now": utcnow()}, kind="doctor")


@pages.get("/doctor/emergency")
def emergency_page(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.EMERGENCY_ACCESS))):
    return render_portal(request, db, cu, "doctor/emergency.html", {"page": svc.my_emergencies(db, cu, page), "now": utcnow()}, kind="doctor")


@pages.get("/doctor/profile")
def profile_page(request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(clinician)):
    return render_portal(request, db, cu, "doctor/profile.html", {"u": cu.user, "doc": cu.doctor, "staff": cu.staff}, kind="doctor")


@pages.get("/doctor/notifications")
def notifications_page(request: Request, page: int = Query(1, ge=1), db: Session = Depends(get_db), cu: CurrentUser = Depends(clinician)):
    return render_portal(request, db, cu, "common/notifications.html", {"page": notification.list_for(db, cu.id, page), "base": "/doctor"}, kind="doctor")


# ================================================================ API

@api.post("/patients/lookup", summary="Find a patient by exact UPI")
def lookup(body: UpiLookupIn, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.PATIENT_SEARCH))):
    if not rl.hit("upi-lookup", str(cu.id), 30, 600).allowed:
        return JSONResponse({"detail": "Too many lookups. Wait a few minutes."}, status_code=429)
    try:
        p = _patient(db, body.upi)
    except svc.ProviderError as e:
        return _err(e)
    return {"redirect": f"/doctor/patients/{p.upi}"}


@api.post("/patients/{upi}/access-requests", status_code=201, summary="Request consent for private records")
def request_access(upi: str, body: AccessRequestIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.ACCESS_REQUEST))):
    if cu.doctor is None:
        raise Forbidden("Only doctors can request consent.")
    if not rl.hit("access-request", str(cu.id), 20, 3600).allowed:
        return JSONResponse({"detail": "Too many requests in the last hour."}, status_code=429)
    try:
        patient = _patient(db, upi)
        consent_service.request_access(db, doctor=cu.doctor, patient=patient, purpose=body.purpose, ip=client_ip(request), session_ref=cu.session_ref)
        db.commit()
    except (svc.ProviderError, consent_service.ConsentError) as e:
        db.rollback()
        return _err(e)
    return {"detail": "Request sent. The patient has been notified."}


@api.post("/access-requests/{request_id}/cancel", summary="Cancel a pending request")
def cancel_request(request_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.ACCESS_REQUEST))):
    if cu.doctor is None:
        raise Forbidden()
    try:
        consent_service.cancel_request(db, doctor=cu.doctor, request_id=request_id, ip=client_ip(request))
        db.commit()
    except consent_service.ConsentError as e:
        db.rollback()
        return _err(e)
    return {"detail": "Request cancelled."}


@api.post("/patients/{upi}/emergency", status_code=201, summary="Start emergency access (logged, patient notified)")
def emergency(upi: str, body: EmergencyIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.EMERGENCY_ACCESS))):
    if not rl.hit("emergency", str(cu.id), 10, 3600).allowed:
        return JSONResponse({"detail": "Emergency access limit reached. Contact your hospital administrator."}, status_code=429)
    try:
        patient = _patient(db, upi)
        em = svc.start_emergency(db, cu, patient, body.reason, client_ip(request))
    except svc.ProviderError as e:
        db.rollback()
        return _err(e)
    return {"detail": "Emergency access granted. It has been logged and the patient notified.", "expires_at": em.expires_at.isoformat() + "Z",
            "redirect": f"/doctor/patients/{patient.upi}"}


@api.post("/emergency/{emergency_access_id}/end", summary="End emergency access early")
def end_emergency(emergency_access_id: int, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.EMERGENCY_ACCESS))):
    try:
        svc.end_emergency(db, cu, emergency_access_id, client_ip(request))
    except svc.ProviderError as e:
        return _err(e)
    return {"detail": "Emergency access ended."}


@api.post("/patients/{upi}/records", status_code=201, summary="Add a record for a patient (always private)")
async def create_record(upi: str, request: Request, title: str = Form(""), details: str = Form(""), information_type: str = Form(""),
                        information_date: str = Form(""), visibility: str = Form("private"), file: UploadFile | None = File(None),
                        db: Session = Depends(get_db), cu: CurrentUser = Depends(require_permissions(P.RECORDS_CREATE))):
    fields: dict[str, Any] = validate_record_fields(title, details, information_type, information_date, visibility)
    if fields["errors"]:
        return JSONResponse({"detail": next(iter(fields["errors"].values())), "fields": fields["errors"]}, status_code=422)
    try:
        patient = _patient(db, upi)
    except svc.ProviderError as e:
        return _err(e)
    stored = None
    if file is not None and file.filename:
        try:
            stored = await file_service.save_upload(file)
        except file_service.FileError as e:
            return JSONResponse({"detail": e.message, "fields": {"file": e.message}}, status_code=422)
    elif not fields["details"]:
        return JSONResponse({"detail": "Add notes or a file.", "fields": {"details": "Add notes or a file."}}, status_code=422)
    try:
        info = svc.create_record(db, cu, patient, fields, stored, client_ip(request))
    except Exception as e:
        db.rollback()
        if stored:
            file_service.delete_quietly(stored.stored_name)
        if isinstance(e, svc.ProviderError):
            return _err(e)
        raise
    return {"detail": "Record added.", "redirect": f"/doctor/patients/{patient.upi}?added={info.information_id}"}


@api.patch("/patients/{upi}/records/{information_id}", summary="Edit a record (own hospital, needs access)")
def update_record(upi: str, information_id: int, body: RecordUpdateIn, request: Request, db: Session = Depends(get_db),
                  cu: CurrentUser = Depends(require_permissions(P.RECORDS_UPDATE))):
    try:
        patient = _patient(db, upi)
        ctx = svc.access_for(db, cu, patient)
        changes = svc.update_record(db, cu, patient, ctx, information_id, body.model_dump(), client_ip(request))
    except svc.ProviderError as e:
        db.rollback()
        return _err(e)
    return {"detail": "Record updated." if changes else "No changes to save.", "redirect": f"/doctor/patients/{patient.upi}/records/{information_id}"}


@api.put("/profile", summary="Update own phone / specialization")
def update_profile(body: ProviderProfileIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser = Depends(clinician)):
    svc.update_own_profile(db, cu, body.model_dump(), client_ip(request))
    return {"detail": "Profile saved."}
