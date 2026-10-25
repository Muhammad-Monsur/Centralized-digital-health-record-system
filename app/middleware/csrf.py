"""CSRF protection for every state-changing request.

Two layers:
1. Origin/Referer must match our own origin when the browser sends them.
2. The ``X-CSRF-Token`` header must equal the session's token (signed-in users)
   or the anonymous double-submit cookie (login/register/newsletter/contact).

All mutations in the frontend go through ``fetch`` (static/js/core/http.js), which
adds the header automatically. Cross-site pages cannot read our token or cookie.
"""
from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.services.common.security import unmask_token

_SAFE = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _origin_ok(request: Request) -> bool:
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return True  # non-browser clients; the token check below still applies
    src = urlsplit(source)
    allowed = {urlsplit(settings.base_url).netloc, request.headers.get("host", "")}
    return src.netloc in allowed


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _SAFE:
            return await call_next(request)
        expected = getattr(request.state, "csrf_token", None)
        sent = unmask_token(request.headers.get("x-csrf-token", "")[:200]) or ""
        if not _origin_ok(request) or not expected or not sent or not hmac.compare_digest(expected, sent):
            return JSONResponse(
                {"detail": "Your form expired or came from another site. Reload the page and try again."},
                status_code=403,
            )
        return await call_next(request)
