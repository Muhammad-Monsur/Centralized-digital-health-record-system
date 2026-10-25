"""Database engine, session factory and declarative base.

Uses a pooled SQLAlchemy engine. ``pool_pre_ping`` drops stale MySQL
connections transparently; ``pool_recycle`` keeps connections younger than
MySQL's ``wait_timeout``.
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import DateTime, MetaData, create_engine, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings

# Deterministic constraint names make Alembic migrations reviewable and portable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds created_at / updated_at columns maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


def make_engine(url: str | None = None):
    eng = create_engine(
        url or settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        echo=settings.sql_echo,
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _utc_session(dbapi_conn, _record) -> None:  # pragma: no cover - trivial
        # All timestamps are stored in UTC regardless of the server's time zone.
        cur = dbapi_conn.cursor()
        cur.execute("SET time_zone = '+00:00'")
        cur.close()

    return eng


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
