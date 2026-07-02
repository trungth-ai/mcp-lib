"""Rate limit trong bộ nhớ theo key-id — "(nền)" theo 07-sprints.md Sprint 4.

Sliding window cố định — đủ dùng cho 1 instance. Chạy nhiều instance (scale ngang, sau
Sprint 5) cần store dùng chung (Redis/Postgres) — ghi trong docs/DECISIONS.md, KHÔNG âm
thầm coi single-instance limiter là đủ cho production nhiều replica.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, *, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key_id: str, *, limit_per_window: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key_id]
        cutoff = now - self._window
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= limit_per_window:
            return False
        hits.append(now)
        return True
