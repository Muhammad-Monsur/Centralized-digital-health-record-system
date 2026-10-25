"""Shared Pydantic types and validators."""
from __future__ import annotations

import re
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

T = TypeVar("T")

_BD_LOCAL = re.compile(r"^01[3-9]\d{8}$")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _phone(v: str) -> str:
    s = re.sub(r"[\s\-()]", "", v)
    if _BD_LOCAL.match(s):
        return "+880" + s[1:]
    if s.startswith("880") and _BD_LOCAL.match("0" + s[3:]):
        return "+" + s
    if _E164.match(s):
        return s
    raise ValueError("Enter a valid mobile number, for example 01712345678 or +8801712345678.")


def _no_control_chars(v: str) -> str:
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", v):
        raise ValueError("Contains characters that aren't allowed.")
    return v


Phone = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20), AfterValidator(_phone)]
CleanStr = Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(_no_control_chars)]
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")


def _username(v: str) -> str:
    v = v.strip().lower()
    if not _USERNAME.match(v):
        raise ValueError("Use 3–50 letters, numbers, dots, dashes or underscores, starting with a letter or number.")
    return v


Username = Annotated[str, StringConstraints(max_length=50), AfterValidator(_username)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    per_page: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.per_page))


class Message(BaseModel):
    detail: str
