"""View layer: Jinja2 environment, template helpers and the ``render`` function.

Autoescaping is on for every template (XSS protection). Templates never receive
raw HTML from users; ``|safe`` is only used on our own inline SVG icon sprites.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.responses import Response

from app.config import BASE_DIR, settings
from app.services.common.security import mask_token

TEMPLATE_DIR = BASE_DIR / "app" / "views" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"
DISPLAY_TZ = ZoneInfo(settings.display_timezone)

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
env = templates.env
env.trim_blocks = True
env.lstrip_blocks = True


@lru_cache(maxsize=1)
def _manifest() -> dict[str, str]:
    """Maps 'css/app.css' -> 'dist/app.3f9a1c.css' (written by scripts/build_assets.mjs)."""
    path = STATIC_DIR / "dist" / "manifest.json"
    if settings.use_built_assets and path.exists():
        return json.loads(path.read_text())
    return {}


def static_url(path: str) -> str:
    path = path.lstrip("/")
    resolved = _manifest().get(path, path)
    return f"{settings.static_url_prefix.rstrip('/')}/{resolved}"


@lru_cache(maxsize=16)
def _built_css(path: str) -> str:
    """Minified CSS for inlining. Relative url(...) (fonts) is rewritten to absolute URLs,
    because inside the HTML page relative URLs would resolve against the page path."""
    built = _manifest().get(path)
    if not built:
        return ""
    text = (STATIC_DIR / built).read_text(encoding="utf-8")
    base = static_url(built).rsplit("/", 1)[0]
    return re.sub(r"url\((['\"]?)(?:\./)?(fonts/[^'\")]+)\1\)", lambda m: f"url({base}/{m.group(2)})", text)


def css_tag(path: str, nonce: str = "", inline: bool = False) -> Markup:
    """<style> with the built CSS inlined (no render-blocking request) or a <link> to it.
    Inlining only happens with built assets; in development it's always a <link>."""
    if inline and settings.use_built_assets:
        css = _built_css(path)
        if css:
            return Markup(f'<style nonce="{escape(nonce)}">{css}</style>')
    return Markup(f'<link rel="stylesheet" href="{escape(static_url(path))}">')


def _local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).astimezone(DISPLAY_TZ)


def fmt_datetime(dt: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    loc = _local(dt)
    return loc.strftime(fmt) if loc else "—"


def fmt_date(d: date | datetime | None) -> str:
    if d is None:
        return "—"
    if isinstance(d, datetime):
        d = _local(d)  # type: ignore[assignment]
    return d.strftime("%d %b %Y")  # type: ignore[union-attr]


def iso_utc(dt: datetime | None) -> str:
    return dt.replace(tzinfo=UTC).isoformat() if dt else ""


def humanize(value: str | None) -> str:
    return (value or "").replace("_", " ").capitalize()


env.globals.update(static_url=static_url, css_tag=css_tag, app_name=settings.app_name, settings=settings)
env.filters.update(dt=fmt_datetime, d=fmt_date, iso=iso_utc, humanize=humanize)


def render(request: Request, name: str, context: dict[str, Any] | None = None, status_code: int = 200) -> Response:
    ctx: dict[str, Any] = {
        "csrf_token": mask_token(request.state.csrf_token) if getattr(request.state, "csrf_token", "") else "",
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
        "current_user": getattr(request.state, "current_user", None),
        "session_seconds": request.state.session.seconds_left() if getattr(request.state, "session", None) else 0,
        "session_warning": settings.session_warning_seconds,
        "path": request.url.path,
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def safe_next(target: str | None, default: str) -> str:
    """Only allow same-site relative paths. Blocks //evil.com, /\\evil.com and control-character
    tricks like "/\t/evil.com" (browsers strip tabs/newlines, turning it into //evil.com)."""
    from urllib.parse import urlsplit

    if not target or len(target) > 300 or not target.startswith("/"):
        return default
    if any(ord(c) < 0x20 or ord(c) == 0x7F or c == "\\" for c in target):
        return default
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or target.startswith("//"):
        return default
    return target


__all__ = ["render", "safe_next", "static_url", "templates", "Path"]
