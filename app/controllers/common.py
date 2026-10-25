"""Public/common controller: search, help, privacy, contact form, newsletter."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import CurrentUser, get_optional_user
from app.middleware.rate_limit import client_ip
from app.models import ContactMessage, NewsletterSubscriber
from app.schemas.common_forms import ContactIn, NewsletterIn
from app.services import search as search_service
from app.services.common import rate_limit as rl
from app.services.common.audit import audit
from app.services.content import FAQ, HELP
from app.views import render

pages = APIRouter(include_in_schema=False)
api = APIRouter(prefix="/api/v1", tags=["common"])


def _public_stats(db: Session) -> dict[str, int]:
    """Aggregate, non-identifying counts for the landing page (cached 5 min, safe to share)."""
    from sqlalchemy import func

    from app.models import Doctor, Hospital, MedicalInformation
    from app.models.enums import HospitalStatus, RecordStatus, VerificationStatus
    from app.services.common import cache

    return cache.cached("public:stats", 300, lambda: {
        "hospitals": int(db.scalar(select(func.count()).select_from(Hospital).where(Hospital.status == HospitalStatus.ACTIVE)) or 0),
        "doctors": int(db.scalar(select(func.count()).select_from(Doctor).where(Doctor.verification_status == VerificationStatus.VERIFIED)) or 0),
        "records": int(db.scalar(select(func.count()).select_from(MedicalInformation).where(MedicalInformation.status == RecordStatus.ACTIVE)) or 0),
    })


@pages.get("/")
def landing(request: Request, db: Session = Depends(get_db), _u: CurrentUser | None = Depends(get_optional_user)):
    return render(request, "landing/index.html", {"faq": FAQ, "stats": _public_stats(db)})


@pages.get("/help")
def help_page(request: Request, _u: CurrentUser | None = Depends(get_optional_user)):
    return render(request, "common/help.html", {"faq": FAQ, "help": HELP})


@pages.get("/privacy")
def privacy_page(request: Request, _u: CurrentUser | None = Depends(get_optional_user)):
    return render(request, "common/privacy.html")


@api.get("/search", summary="Role-aware site search")
def search(request: Request, q: str = Query("", max_length=80), db: Session = Depends(get_db), cu: CurrentUser | None = Depends(get_optional_user)):
    who = str(cu.id) if cu else client_ip(request)
    if not rl.hit("search", who, 120, 60).allowed:
        return JSONResponse({"detail": "Too many searches. Slow down a little."}, status_code=429)
    groups = search_service.search(db, cu, q)
    # Results depend on who is asking -> never cacheable by shared caches.
    return JSONResponse({"q": q, "groups": groups}, headers={"Cache-Control": "private, no-store"})


@api.get("/faq", summary="FAQ (public, ETag-cached)")
def faq(request: Request):
    """Public, non-sensitive, identical for everyone -> cacheable with an ETag."""
    body = json.dumps({"items": [{"q": q, "a": a} for q, a in FAQ]}, separators=(",", ":"))
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:16] + '"'
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "public, max-age=300"})
    return Response(body, media_type="application/json", headers={"ETag": etag, "Cache-Control": "public, max-age=300"})


def etag_matches(header: str | None, etag: str) -> bool:
    """Weak comparison (RFC 9110): compression rewrites our ETag as W/"..."."""
    if not header:
        return False
    if header.strip() == "*":
        return True
    bare = etag.removeprefix("W/")
    return any(t.strip().removeprefix("W/") == bare for t in header.split(","))


@api.post("/newsletter", status_code=201, summary="Subscribe to the newsletter")
def newsletter(body: NewsletterIn, request: Request, db: Session = Depends(get_db)):
    if not rl.hit("newsletter", client_ip(request), 10, 3600).allowed:
        return JSONResponse({"detail": "Too many sign-ups from this network. Try later."}, status_code=429)
    if db.scalar(select(NewsletterSubscriber.subscriber_id).where(NewsletterSubscriber.email == body.email)):
        return JSONResponse({"detail": "You're already subscribed with this email.", "fields": {"email": "Already subscribed."}}, status_code=409)
    db.add(NewsletterSubscriber(email=body.email))
    try:
        db.commit()
    except IntegrityError:  # concurrent duplicate
        db.rollback()
        return JSONResponse({"detail": "You're already subscribed with this email."}, status_code=409)
    return {"detail": "Subscribed. Thanks! We'll only email about CDHRS updates."}


@api.post("/contact", status_code=201, summary="Send a contact message")
def contact(body: ContactIn, request: Request, db: Session = Depends(get_db), cu: CurrentUser | None = Depends(get_optional_user)):
    if not rl.hit("contact", client_ip(request), 5, 3600).allowed:
        return JSONResponse({"detail": "You've sent several messages already. Try again later."}, status_code=429)
    if body.website:  # bot filled the honeypot: pretend success, store nothing
        return {"detail": "Message sent. We'll reply by email."}
    msg = ContactMessage(name=body.name, email=body.email, subject=body.subject, message=body.message)
    db.add(msg)
    db.flush()
    audit(db, action="contact.received", entity="contact_message", entity_id=msg.message_id, user_id=cu.id if cu else None, ip=client_ip(request))
    db.commit()
    return {"detail": "Message sent. We'll reply by email."}
