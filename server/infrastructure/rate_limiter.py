from __future__ import annotations

from collections import deque
from hashlib import sha256
from threading import Lock
from time import monotonic


class InMemoryRateLimiter:
    def __init__(
        self,
        max_keys: int = 10_000,
        max_window_seconds: int = 300,
    ) -> None:
        self._max_keys = max_keys
        self._max_window_seconds = max_window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(
        self,
        scope: str,
        identity: str,
        limit: int,
        window_seconds: int,
    ) -> bool:
        if (
            limit <= 0
            or window_seconds <= 0
            or window_seconds > self._max_window_seconds
        ):
            raise ValueError("Rate limit values must be positive")
        key = f"{scope}:{sha256(identity.encode('utf-8')).hexdigest()}"
        now = monotonic()
        cutoff = now - window_seconds
        with self._lock:
            if key not in self._events and len(self._events) >= self._max_keys:
                self._prune(now - self._max_window_seconds)
                if len(self._events) >= self._max_keys:
                    return False
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    def _prune(self, cutoff: float) -> None:
        stale = [
            key
            for key, events in self._events.items()
            if not events or events[-1] <= cutoff
        ]
        for key in stale:
            self._events.pop(key, None)
