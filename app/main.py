"""CDHRS application factory: middleware stack, routers, static files, error pages."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import settings
from app.controllers import admin as admin_ctrl
from app.controllers import auth as auth_ctrl
from app.controllers import common as common_ctrl
from app.controllers import doctor as doctor_ctrl
from app.controllers import docs as docs_ctrl
from app.controllers import patient as patient_ctrl
from app.controllers.errors import register_error_handlers
from app.database import engine
from app.middleware.cache_control import CacheControlMiddleware
from app.middleware.compression import CompressionMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.session import SessionMiddleware
from app.views import STATIC_DIR

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if settings.is_production and (problems := settings.production_problems()):
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    yield
    engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CDHRS API",
        description=(
            "Centralized Digital Health Record System. All state-changing endpoints require a "
            "session cookie and an `X-CSRF-Token` header (see README)."
        ),
        version="1.0.0",
        # Swagger UI / ReDoc pages are served by app/controllers/docs.py (CSP nonce aware).
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.api_docs_enabled else None,
        lifespan=lifespan,
    )

    # Middleware: the LAST added runs FIRST. Effective order for a request:
    # Compression -> SecurityHeaders -> CacheControl -> RateLimit -> Session -> CSRF -> route
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(SessionMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CacheControlMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CompressionMiddleware)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    if settings.api_docs_enabled:
        app.include_router(docs_ctrl.router)

    for module in (auth_ctrl, common_ctrl, patient_ctrl, doctor_ctrl, admin_ctrl):
        app.include_router(module.pages)
        app.include_router(module.api)

    @app.get("/healthz", tags=["system"], summary="Liveness + database check (load balancer probe)")
    def healthz() -> dict[str, str]:
        """Liveness + database connectivity probe (used by nginx / docker)."""
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    register_error_handlers(app)
    return app


app = create_app()
