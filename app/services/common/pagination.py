"""Server-side pagination: a COUNT plus a LIMIT/OFFSET page of the same filtered query."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")
MAX_PER_PAGE = 100


@dataclass
class Page(Generic[T]):
    items: list[T]
    page: int
    per_page: int
    total: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.per_page))

    def meta(self) -> dict[str, int]:
        return {"page": self.page, "per_page": self.per_page, "total": self.total, "pages": self.pages}


def clamp(page: int | None, per_page: int | None, default: int = 20) -> tuple[int, int]:
    p = max(1, int(page or 1))
    pp = max(1, min(MAX_PER_PAGE, int(per_page or default)))
    return p, pp


def paginate(db: Session, stmt: Select, page: int = 1, per_page: int = 20, *, scalars: bool = True) -> Page:
    page, per_page = clamp(page, per_page)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    q = stmt.limit(per_page).offset((page - 1) * per_page)
    rows = list(db.scalars(q).unique()) if scalars else list(db.execute(q).unique())
    return Page(items=rows, page=page, per_page=per_page, total=int(total))
