"""Auth controller: login/logout pages and JSON endpoints, session status/extend."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import CurrentUser, get_optional_user, load_current_user, require_user
from app.middleware.rate_limit import client_ip
from app.middleware.session import clear_session_cookie, set_session_cookie
from app.schemas.auth import LoginIn, LoginOut, PasswordChangeIn, SessionStatusOut
from app.services import auth as auth_service
from app.services.common.permissions import LOGIN_PORTALS
from app.services.common.security import mask_token
from app.services.common.session import touch_session
from app.views import render, safe_next

pages = APIRouter(include_in_schema=False)
api = APIRouter(prefix="/api/v1", tags=["auth"])


def _login_page(portal: str):
    cfg = LOGIN_PORTALS[portal]

    def page(request: Request, next: str | None = None, user: CurrentUser | None = Depends(get_optional_user)):
        if user:
            return RedirectResponse(user.portal, status_code=303)
        return render(request, "auth/login.html", {
            "portal": portal, "cfg": cfg, "next": safe_next(next, ""), "reason": request.query_params.get("reason"),
        })

    page.__name__ = f"login_page_{portal.replace('-', '_')}"
    return page


for _portal, _cfg in LOGIN_PORTALS.items():
    pages.add_api_route(str(_cfg["path"]), _login_page(_portal), methods=["GET"])


@pages.get("/account/change-password")
def change_password_page(request: Request, user: CurrentUser = Depends(require_user)):
    """Shown after sign-in when an administrator set the password (new account or reset)."""
    if not user.user.must_change_password:
        return RedirectResponse(user.portal, status_code=303)
    return render(request, "auth/change_password.html", {"u": user.user, "portal": user.portal})


@pages.get("/admin/login")
def admin_login_chooser(request: Request, user: CurrentUser | None = Depends(get_optional_user)):
    """The admin portal is shared; this asks which kind of admin is signing in."""
    if user:
        return RedirectResponse(user.portal, status_code=303)
    return render(request, "auth/admin_chooser.html", {"next": safe_next(request.query_params.get("next"), "")})


@api.post("/auth/login", response_model=LoginOut, summary="Sign in through a role's portal")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    allowed = set(LOGIN_PORTALS[body.portal]["roles"])  # type: ignore[arg-type]
    try:
        result = auth_service.login(db, body.identifier, body.password, client_ip(request), allowed_roles=allowed)
    except auth_service.AuthError as e:
        headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
        return JSONResponse({"detail": e.message}, status_code=e.status_code, headers=headers)
    cu = load_current_user(db, result.user.user_id)
    portal = cu.portal if cu else "/"
    target = "/account/change-password" if result.user.must_change_password else safe_next(body.next, portal)
    response = JSONResponse({"redirect": target})
    set_session_cookie(response, result.sid)
    return response


@api.post("/auth/logout", summary="Sign out")
def logout(request: Request, db: Session = Depends(get_db), user: CurrentUser | None = Depends(get_optional_user)):
    reason = "timeout" if request.query_params.get("reason") == "timeout" else "user"
    auth_service.logout(db, request.state.sid, user.id if user else None, client_ip(request), reason)
    target = user.login_path if user else "/login"
    response = JSONResponse({"redirect": f"{target}?reason=" + ("timeout" if reason == "timeout" else "signed_out")})
    clear_session_cookie(response)
    return response


@api.post("/auth/password", summary="Change your password (signs out other devices)")
def change_password(body: PasswordChangeIn, request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(require_user)):
    try:
        sid = auth_service.change_password(db, user.user, body.current_password, body.new_password, client_ip(request))
    except auth_service.AuthError as e:
        return JSONResponse({"detail": e.message}, status_code=e.status_code)
    cu = load_current_user(db, user.id)
    response = JSONResponse({"detail": "Password changed. Other devices have been signed out.", "portal": cu.portal if cu else "/"})
    set_session_cookie(response, sid)
    return response


@api.get("/session/status", response_model=SessionStatusOut, summary="Session time left + CSRF token (does not extend)")
def session_status(request: Request):
    """Polled by the timeout warning. Does NOT extend the session."""
    s = getattr(request.state, "session", None)
    return {"authenticated": s is not None, "expires_in": s.seconds_left() if s else 0,
            "warning_seconds": settings.session_warning_seconds, "csrf_token": mask_token(request.state.csrf_token)}


@api.post("/session/extend", response_model=SessionStatusOut, summary="Extend the session (stay signed in)")
def session_extend(request: Request, _user: CurrentUser = Depends(require_user)):
    s = request.state.session
    touch_session(request.state.sid, s)
    return {"authenticated": True, "expires_in": s.seconds_left(), "warning_seconds": settings.session_warning_seconds,
            "csrf_token": mask_token(s.csrf)}
