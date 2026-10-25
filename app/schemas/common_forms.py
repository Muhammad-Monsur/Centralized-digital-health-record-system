from __future__ import annotations

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import CleanStr, StrictModel


class NewsletterIn(StrictModel):
    email: EmailStr = Field(max_length=255)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class ContactIn(StrictModel):
    name: CleanStr = Field(min_length=2, max_length=120)
    email: EmailStr = Field(max_length=255)
    subject: CleanStr = Field(min_length=3, max_length=150)
    message: CleanStr = Field(min_length=10, max_length=3000)
    # Honeypot: real people never fill this hidden field.
    website: str = Field(default="", max_length=200)
