"""Security headers + per-request CSP nonce.

Inline <script>/<style> are only allowed when they carry this request's nonce
(the theme no-flash snippet and the critical CSS block). Everything else must be
a same-origin (or configured CDN) file.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings


def _cdn_origin() -> str:
    p = urlsplit(settings.static_url_prefix)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


_CDN = _cdn_origin()
_DOCS_PATHS = ("/api/docs", "/api/redoc")


def build_csp(nonce: str, *, docs: bool = False) -> str:
    extra = f" {_CDN}" if _CDN else ""
    if docs:
        # API docs (Swagger UI / ReDoc) load pinned bundles from jsDelivr. Scripts still need
        # the nonce. ReDoc injects <style> elements at runtime that cannot carry a nonce, so
        # these two pages alone allow inline styles. A nonce in style-src would make browsers
        # ignore 'unsafe-inline', which is why the docs policy leaves it out.
        cdn = extra + " https://cdn.jsdelivr.net"
        style_src = f"style-src 'self'{cdn} 'unsafe-inline'"
        script_src = f"script-src 'self' 'nonce-{nonce}'{cdn}"
        extra_directives = ["worker-src 'self' blob:"]
    else:
        cdn = extra
        style_src = f"style-src 'self' 'nonce-{nonce}'{cdn}"
        script_src = f"script-src 'self' 'nonce-{nonce}'{cdn}"
        extra_directives = []
    return "; ".join([
        "default-src 'self'",
        script_src,
        style_src,
        # Inline style *attributes* (positioning, SVG fills) cannot execute script; <style>
        # elements still need the nonce.
        "style-src-attr 'unsafe-inline'",
        f"img-src 'self' data:{cdn}" + (" https://cdn.redoc.ly" if docs else ""),
        f"font-src 'self'{cdn}",
        "connect-src 'self'",
        *extra_directives,
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        *(["upgrade-insecure-requests"] if settings.cookie_secure else []),
    ])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)
        h = response.headers
        if "content-security-policy" not in h:  # routes may set a stricter one (e.g. sandboxed file views)
            h["Content-Security-Policy"] = build_csp(nonce, docs=request.url.path.startswith(_DOCS_PATHS))
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin" if not _CDN else "cross-origin"
        if settings.cookie_secure:  # only meaningful (and safe) once HTTPS is in place
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if "server" in h:
            del h["server"]
        return response
