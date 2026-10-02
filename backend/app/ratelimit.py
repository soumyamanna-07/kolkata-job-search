"""Small in-memory limits, so one visitor (or a bot) can't use up the free AI quota.

Kept in memory: fine for one server. If the app ever runs on several servers,
move these counters to the database or Redis.
"""
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone


class PerKeyLimiter:
    """At most `limit` calls per `window` seconds for each key (e.g. a visitor's IP)."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self._calls: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            calls = self._calls[key]
            while calls and now - calls[0] >= self.window:
                calls.popleft()
            if len(calls) >= self.limit:
                return False
            calls.append(now)
            if len(self._calls) > 10_000:                 # forget idle visitors
                for k in [k for k, v in self._calls.items() if not v]:
                    del self._calls[k]
            return True


class DailyBudget:
    """At most `limit` uses per UTC day for the whole site."""

    def __init__(self, limit: int):
        self.limit = limit
        self._day, self._used = None, 0
        self._lock = threading.Lock()

    def take(self, today: str | None = None) -> bool:
        today = today or datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            if today != self._day:
                self._day, self._used = today, 0
            if self._used >= self.limit:
                return False
            self._used += 1
            return True
