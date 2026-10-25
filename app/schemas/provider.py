from __future__ import annotations

from datetime import date

from pydantic import Field, field_validator

from app.models.enums import InformationType
from app.schemas.common import CleanStr, Phone, StrictModel
from app.services.common.security import utcnow


class UpiLookupIn(StrictModel):
    upi: str = Field(min_length=12, max_length=24)


class AccessRequestIn(StrictModel):
    purpose: CleanStr = Field(min_length=15, max_length=1000, description="Why the doctor needs private records")


class EmergencyIn(StrictModel):
    reason: CleanStr = Field(min_length=20, max_length=2000)
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def _confirmed(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Confirm that this is a genuine emergency.")
        return v


class RecordUpdateIn(StrictModel):
    title: CleanStr = Field(min_length=2, max_length=200)
    details: CleanStr = Field(default="", max_length=10_000)
    information_type: InformationType
    information_date: date

    @field_validator("information_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > utcnow().date():
            raise ValueError("The record date can't be in the future.")
        return v


class ProviderProfileIn(StrictModel):
    phone: Phone | None = None
    specialization: CleanStr | None = Field(default=None, min_length=2, max_length=100)

    @field_validator("phone", mode="before")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v or None
