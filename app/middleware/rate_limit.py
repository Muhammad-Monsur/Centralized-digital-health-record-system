"""Coarse per-IP rate limit for the JSON API (abuse/brute-force backstop).

Fine-grained limits (login, OTP, search, newsletter) live in the services, which
know *what* is being limited (username, consent id ...).
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.services.common.rate_limit import hit

API_LIMIT_PER_MINUTE = 300


def client_ip(request: Request) -> str:
    # uvicorn/gunicorn run with --proxy-headers --forwarded-allow-ips=<nginx> so this is the real client.
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/api/") and not request.url.path.startswith(("/api/docs", "/api/redoc", "/api/openapi")):
            res = hit("api", client_ip(request), API_LIMIT_PER_MINUTE, 60)
            if not res.allowed:
                return JSONResponse(
                    {"detail": "Too many requests. Wait a moment and try again."},
                    status_code=429,
                    headers={"Retry-After": str(res.retry_after), "Cache-Control": "no-store"},
                )
        return await call_next(request)
