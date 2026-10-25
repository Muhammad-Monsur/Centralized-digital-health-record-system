from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import StrictModel


class LoginIn(StrictModel):
    portal: Literal["patient", "doctor", "hospital-admin", "system-admin"] = "patient"
    identifier: str = Field(min_length=3, max_length=255, description="Username or email")
    password: str = Field(min_length=1, max_length=128)
    next: str | None = Field(default=None, max_length=300)


class LoginOut(StrictModel):
    redirect: str


class PasswordChangeIn(StrictModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class SessionStatusOut(StrictModel):
    authenticated: bool
    expires_in: int
    warning_seconds: int
    # Same-origin only (no CORS), so other sites can't read it. Lets a tab refresh a
    # stale token after the user signed in or out in another tab.
    csrf_token: str = ""
