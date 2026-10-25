"""Server-side cache for expensive, NON-SENSITIVE results (Redis, or in-memory TTL fallback).

Rule (section 8): never cache patient health information here. Allowed: system
settings, FAQ/help content, role/permission catalogue, aggregate counts for admin
dashboards. Every cached key has an explicit invalidation path (``invalidate``).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from app.services.common.kvstore import get_json, kv, set_json

T = TypeVar("T")
_NS = "cache:"


def cached(key: str, ttl: int, loader: Callable[[], T]) -> T:
    hit = get_json(_NS + key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    value = loader()
    set_json(_NS + key, value, ttl)
    return value


def invalidate(*keys: str) -> None:
    kv.delete(*(_NS + k for k in keys))


def invalidate_prefix(prefix: str) -> None:
    kv.delete_prefix(_NS + prefix)


def peek(key: str) -> Any | None:
    return get_json(_NS + key)
