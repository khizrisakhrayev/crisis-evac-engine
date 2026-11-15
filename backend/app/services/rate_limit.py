"""In-memory sliding-window rate limiter (thread-safe, injectable clock for tests).

Usage: limiter.hit(key, limit, window_s) -> (allowed, retry_after_s). Rejected hits are not recorded.
"""
import math
import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> tuple[bool, int]:
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, math.ceil(q[0] + window_s - now))
            q.append(now)
            return True, 0

    def blocked(self, key: str, limit: int, window_s: float) -> int:
        """Retry-After seconds if `key` is already at its limit (nothing recorded), else 0."""
        now = self.clock()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 0
            while q and q[0] <= now - window_s:
                q.popleft()
            return max(1, math.ceil(q[0] + window_s - now)) if len(q) >= limit else 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()
