"""Default caching policy: nothing dynamic is cacheable unless a route opts in.

* Hashed build assets (/static/dist/...): public, 1 year, immutable.
* Other static files: public, 1 hour (+ ETag from StaticFiles for revalidation).
* Everything else: ``no-store`` unless the route set its own Cache-Control.
  Routes only opt in for non-PHI public data (FAQ, help search) - see section 8.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/"):
            if response.status_code < 400:
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable" if path.startswith("/static/dist/") else "public, max-age=3600"
                )
            return response
        if "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        # Responses for signed-in users must never be stored by shared caches.
        if getattr(request.state, "session", None) is not None and "public" in response.headers["cache-control"]:
            response.headers["Cache-Control"] = "private, no-store"
        response.headers.setdefault("Vary", "Cookie")
        return response
