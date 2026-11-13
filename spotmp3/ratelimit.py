import threading
import time
from collections import deque
from typing import Callable

WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic):
        self.per_minute = per_minute
        self._clock = clock
        self._lock = threading.Lock()
        self._recent: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        current = self._clock()
        with self._lock:
            recent = self._recent.setdefault(key, deque())
            while recent and current - recent[0] >= WINDOW_SECONDS:
                recent.popleft()
            if len(recent) >= self.per_minute:
                return False
            recent.append(current)
            return True


class OneAtATime:
    def __init__(self):
        self._lock = threading.Lock()
        self._busy: set[str] = set()

    def try_start(self, key: str) -> bool:
        with self._lock:
            if key in self._busy:
                return False
            self._busy.add(key)
            return True

    def finish(self, key: str) -> None:
        with self._lock:
            self._busy.discard(key)
