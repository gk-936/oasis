"""Tiny in-memory sliding-window rate limiter (per client key)."""
from __future__ import annotations
import time
from collections import defaultdict, deque
from typing import Callable


class RateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic, store=None, name: str = ""):
        """With `store` (an encrypted SqliteStore) and a `name`, recorded attempts survive a restart: the wall clock is used and
        the hits are written through, so restarting the server no longer resets a login lockout."""
        self.limit, self.window, self._clock = limit, window_s, (time.time if store is not None else clock)
        self._hits: dict[str, deque] = defaultdict(deque)
        self._store, self._name = store, name
        if store is not None:
            now = self._clock()
            for k, ts in (store.get_kv(name) or {}).items():
                q = deque(t for t in ts if t > now - window_s)
                if q:
                    self._hits[k] = q

    def _save(self) -> None:
        if self._store is not None:
            now = self._clock()
            self._store.set_kv(self._name, {k: [t for t in q if t > now - self.window] for k, q in self._hits.items() if q})

    def allow(self, key: str) -> bool:
        """Record one attempt for `key`; False (and not recorded) when the window is already full."""
        now = self._clock()
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        self._save()
        return True

    def retry_after(self, key: str) -> int:
        q = self._hits.get(key)
        return max(1, int(self.window - (self._clock() - q[0])) + 1) if q else 1

    def blocked(self, key: str) -> bool:
        """True when the window is full (without recording anything)."""
        now = self._clock()
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        return len(q) >= self.limit

    def record(self, key: str) -> None:
        self._hits[key].append(self._clock())
        self._save()
