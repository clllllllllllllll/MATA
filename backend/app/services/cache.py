from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class ScopedTTLCache:
    """
    In-memory cache abstraction for local/dev.

    Keys are always role- and scope-qualified to prevent cross-scope leakage.
    """

    def __init__(self) -> None:
        self._store: dict[str, _CacheEntry] = {}

    @staticmethod
    def build_key(role: str, scope: dict[str, Any], namespace: str, suffix: str = "") -> str:
        scope_parts = [f"{key}={scope[key]}" for key in sorted(scope)]
        base = f"{namespace}|role={role}|{'|'.join(scope_parts)}"
        return f"{base}|{suffix}" if suffix else base

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time.monotonic() + ttl_seconds,
        )

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> int:
        removed = 0
        for key in list(self._store.keys()):
            if key.startswith(prefix):
                self._store.pop(key, None)
                removed += 1
        return removed

    def clear_expired(self) -> int:
        removed = 0
        now = time.monotonic()
        for key, entry in list(self._store.items()):
            if entry.expires_at <= now:
                self._store.pop(key, None)
                removed += 1
        return removed


cache = ScopedTTLCache()
