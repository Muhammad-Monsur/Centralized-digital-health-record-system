"""Exception handlers: friendly HTML pages for browsers, consistent JSON for the API."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.middleware.auth import Forbidden, LoginRequired, PasswordChangeRequired
from app.views import render

log = logging.getLogger("cdhrs")


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", "")


def _error_page(request: Request, status: int, title: str, message: str) -> Response:
    template = {403: "errors/403.html", 404: "errors/404.html"}.get(status, "errors/500.html")
    return render(request, template, {"status": status, "title": title, "message": message}, status_code=status)


def _friendly(err: dict) -> str:
    """Turn Pydantic's technical messages into plain language."""
    t = err.get("type", "")
    ctx = err.get("ctx") or {}
    if t == "missing":
        return "This field is required."
    if t == "string_too_short":
        return f"Enter at least {ctx.get('min_length')} characters."
    if t == "string_too_long":
        return f"Keep this under {ctx.get('max_length')} characters."
    if t == "enum" or t == "literal_error":
        return "Choose one of the options."
    if t.startswith("date"):
        return "Enter a valid date."
    if t == "extra_forbidden":
        return "Unexpected field."
    if t in ("int_parsing", "int_type"):
        return "Enter a whole number."
    msg = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
    if "email address" in msg:
        return "Enter a valid email address."
    return msg


def _field_errors(exc: RequestValidationError) -> dict[str, str]:
    out: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query", "path")]
        out.setdefault(".".join(loc) or "form", _friendly(err))
    return out


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired) -> Response:
        if _wants_json(request):
            return JSONResponse({"detail": "Please sign in."}, status_code=401)
        nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        from urllib.parse import quote

        from app.services.common.permissions import login_path_for_url

        return RedirectResponse(f"{login_path_for_url(request.url.path)}?next={quote(nxt)}", status_code=303)

    @app.exception_handler(PasswordChangeRequired)
    async def _pw_change(request: Request, _exc: PasswordChangeRequired) -> Response:
        if _wants_json(request):
            return JSONResponse({"detail": "Set a new password before continuing.", "redirect": "/account/change-password"}, status_code=403)
        return RedirectResponse("/account/change-password", status_code=303)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden) -> Response:
        if _wants_json(request):
            return JSONResponse({"detail": exc.message}, status_code=403)
        return _error_page(request, 403, "Access denied", exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        fields = _field_errors(exc)
        first = next(iter(fields.values()), "Check the highlighted fields.")
        return JSONResponse({"detail": first, "fields": fields}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        if _wants_json(request) or exc.status_code not in (403, 404, 405):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
        if exc.status_code == 404:
            return _error_page(request, 404, "Page not found", "The page you were looking for doesn't exist or has moved.")
        return _error_page(request, exc.status_code, "Not allowed", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> Response:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        if _wants_json(request):
            return JSONResponse({"detail": "Something went wrong on our side. Try again in a moment."}, status_code=500)
        return _error_page(request, 500, "Something went wrong", "An unexpected error occurred. Your data is safe; try again in a moment.")
