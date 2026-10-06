from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Process-local fallback limiter; put shared deployments behind a rate-limit gateway."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, limit: int, period: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - period:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


limiter = RateLimiter()
