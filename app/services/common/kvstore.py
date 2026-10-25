"""Tiny key-value store with TTLs: Redis when REDIS_URL is set, else in-process memory.

Used for sessions, rate-limit counters and the non-PHI cache. Redis is required
when several app instances run behind the load balancer (sessions must be shared);
the in-memory fallback is for single-process development and tests.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Protocol

from app.config import settings


class KVStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int) -> None: ...
    def delete(self, *keys: str) -> None: ...
    def incr(self, key: str, ttl: int) -> int: ...
    def ttl(self, key: str) -> int: ...
    def expire(self, key: str, ttl: int) -> None: ...
    def sadd(self, key: str, member: str, ttl: int) -> None: ...
    def smembers(self, key: str) -> set[str]: ...
    def srem(self, key: str, member: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def ping(self) -> bool: ...


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def _alive(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, exp = item
        if exp and exp < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def get(self, key: str) -> str | None:
        with self._lock:
            v = self._alive(key)
            return v if isinstance(v, str) else None

    def set(self, key: str, value: str, ttl: int) -> None:
        with self._lock:
            self._data[key] = (value, time.monotonic() + ttl if ttl else 0)

    def delete(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._data.pop(k, None)

    def incr(self, key: str, ttl: int) -> int:
        with self._lock:
            v = self._alive(key)
            if v is None:
                self._data[key] = ("1", time.monotonic() + ttl)
                return 1
            n = int(v) + 1
            self._data[key] = (str(n), self._data[key][1])
            return n

    def ttl(self, key: str) -> int:
        with self._lock:
            if self._alive(key) is None:
                return -2
            exp = self._data[key][1]
            return int(exp - time.monotonic()) if exp else -1

    def expire(self, key: str, ttl: int) -> None:
        with self._lock:
            v = self._alive(key)
            if v is not None:
                self._data[key] = (v, time.monotonic() + ttl)

    def sadd(self, key: str, member: str, ttl: int) -> None:
        with self._lock:
            v = self._alive(key)
            s: set[str] = set(v) if isinstance(v, set) else set()
            s.add(member)
            self._data[key] = (s, time.monotonic() + ttl)

    def smembers(self, key: str) -> set[str]:
        with self._lock:
            v = self._alive(key)
            return set(v) if isinstance(v, set) else set()

    def srem(self, key: str, member: str) -> None:
        with self._lock:
            v = self._alive(key)
            if isinstance(v, set):
                v.discard(member)

    def delete_prefix(self, prefix: str) -> None:
        with self._lock:
            for k in [k for k in self._data if k.startswith(prefix)]:
                self._data.pop(k, None)

    def ping(self) -> bool:
        return True

    def flush(self) -> None:  # tests
        with self._lock:
            self._data.clear()


class RedisStore:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2, health_check_interval=30)

    def get(self, key: str) -> str | None:
        return self._r.get(key)  # type: ignore[return-value]

    def set(self, key: str, value: str, ttl: int) -> None:
        self._r.set(key, value, ex=ttl or None)

    def delete(self, *keys: str) -> None:
        if keys:
            self._r.delete(*keys)

    def incr(self, key: str, ttl: int) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)  # set TTL only on first increment (fixed window)
        n, _ = pipe.execute()
        return int(n)

    def ttl(self, key: str) -> int:
        return int(self._r.ttl(key))  # type: ignore[arg-type]

    def expire(self, key: str, ttl: int) -> None:
        self._r.expire(key, ttl)

    def sadd(self, key: str, member: str, ttl: int) -> None:
        pipe = self._r.pipeline()
        pipe.sadd(key, member)
        pipe.expire(key, ttl)
        pipe.execute()

    def smembers(self, key: str) -> set[str]:
        return set(self._r.smembers(key))  # type: ignore[arg-type]

    def srem(self, key: str, member: str) -> None:
        self._r.srem(key, member)

    def delete_prefix(self, prefix: str) -> None:
        batch: list[str] = []
        for k in self._r.scan_iter(match=f"{prefix}*", count=500):
            batch.append(k)
            if len(batch) >= 500:
                self._r.delete(*batch)
                batch.clear()
        if batch:
            self._r.delete(*batch)

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False


def _build() -> KVStore:
    if settings.redis_url and not settings.is_test:
        return RedisStore(settings.redis_url)
    return MemoryStore()


kv: KVStore = _build()


def get_json(key: str) -> Any | None:
    raw = kv.get(key)
    return json.loads(raw) if raw else None


def set_json(key: str, value: Any, ttl: int) -> None:
    kv.set(key, json.dumps(value, separators=(",", ":"), default=str), ttl)
