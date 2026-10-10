"""Tiny in-memory sliding-window rate limiter (per client key)."""
from __future__ import annotations
import time
from collections import defaultdict, deque
from typing import Callable


class RateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self._clock = limit, window_s, clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record one attempt for `key`; False (and not recorded) when the window is already full."""
        now = self._clock()
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
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
