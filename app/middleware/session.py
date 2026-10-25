"""Session loading + idle/absolute timeout + CSRF token provisioning.

* Loads the server-side session named by the session cookie into ``request.state``.
* Slides the idle timeout on real activity (not on status polls or static files).
* Exposes ``X-Session-Expires-In`` so the UI can warn before timeout.
* Anonymous visitors get a random CSRF cookie (double-submit) for login/register forms.
"""
from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.services.common.session import load_session, touch_session

# __Host- prefix (only possible over HTTPS) stops subdomains from planting cookies.
_PREFIX = "__Host-" if settings.cookie_secure else ""
SESSION_COOKIE = _PREFIX + settings.session_cookie_name
CSRF_COOKIE = _PREFIX + "cdhrs_csrf"

# Requests that must not extend the session (otherwise the warning could never fire).
_NO_TOUCH = ("/api/v1/session/status",)


def set_session_cookie(response: Response, sid: str) -> None:
    # No Max-Age: a browser-session cookie, gone when the browser closes (shared PCs).
    response.set_cookie(SESSION_COOKIE, sid, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path.startswith("/static/"):
            return await call_next(request)

        sid = request.cookies.get(SESSION_COOKIE)
        session = load_session(sid)
        request.state.sid = sid if session else None
        request.state.session = session

        new_csrf_cookie: str | None = None
        if session:
            request.state.csrf_token = session.csrf
            if path not in _NO_TOUCH:
                touch_session(sid, session)  # type: ignore[arg-type]
        else:
            token = request.cookies.get(CSRF_COOKIE)
            if not token or len(token) < 32 or len(token) > 64:
                token = new_csrf_cookie = secrets.token_urlsafe(32)
            request.state.csrf_token = token

        response = await call_next(request)

        if new_csrf_cookie:
            response.set_cookie(CSRF_COOKIE, new_csrf_cookie, httponly=True, secure=settings.cookie_secure, samesite="strict", path="/")
        if session and getattr(request.state, "session", None) is session:
            response.headers["X-Session-Expires-In"] = str(session.seconds_left())
        if sid and not session and not getattr(request.state, "sid", None):
            clear_session_cookie(response)  # stale cookie
        return response
