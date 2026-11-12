"""Small in-memory limiter for sign-in attempts (one server process).

Counts failures per key in a sliding window. A real deployment with several processes
would keep these counts in Redis; the interface stays the same.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque


class TooManyAttemptsError(Exception):
    """Raised when a key has failed too often; ``retry_after`` is in seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__("Too many attempts.")
        self.retry_after = retry_after

    @property
    def message(self) -> str:
        """User-facing wording."""
        minutes = max(1, math.ceil(self.retry_after / 60))
        unit = "minute" if minutes == 1 else "minutes"
        return f"Too many attempts. Please wait {minutes} {unit} and try again."


class AttemptLimiter:
    """Allow ``limit`` failures per key within ``window`` seconds."""

    def __init__(self, limit: int, window: float, clock=time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        times = self._failures[key]
        while times and now - times[0] >= self.window:
            times.popleft()
        return times

    def check(self, *keys: str) -> None:
        """Raise TooManyAttemptsError if any key is over its limit."""
        now = self._clock()
        with self._lock:
            for key in keys:
                times = self._recent(key, now)
                if len(times) >= self.limit:
                    raise TooManyAttemptsError(self.window - (now - times[0]))

    def fail(self, *keys: str) -> None:
        """Record one failure for each key."""
        now = self._clock()
        with self._lock:
            for key in keys:
                self._recent(key, now).append(now)

    def clear(self) -> None:
        """Forget everything (tests)."""
        with self._lock:
            self._failures.clear()

    def reset(self, *keys: str) -> None:
        """Forget failures for these keys (after a successful sign-in)."""
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)
