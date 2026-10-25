"""Fixed-window rate limiting on top of the KV store."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.common.kvstore import kv


@dataclass
class Limit:
    allowed: bool
    remaining: int
    retry_after: int


def hit(bucket: str, key: str, limit: int, window_seconds: int) -> Limit:
    """Count one event; ``allowed`` is False once ``limit`` is exceeded in the window."""
    k = f"rl:{bucket}:{key}"
    n = kv.incr(k, window_seconds)
    if n > limit:
        ttl = kv.ttl(k)
        return Limit(False, 0, ttl if ttl > 0 else window_seconds)
    return Limit(True, limit - n, 0)


def peek(bucket: str, key: str) -> int:
    v = kv.get(f"rl:{bucket}:{key}")
    return int(v) if v else 0


def reset(bucket: str, key: str) -> None:
    kv.delete(f"rl:{bucket}:{key}")
