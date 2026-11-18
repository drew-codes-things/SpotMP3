import ipaddress
import threading
import time
from collections import OrderedDict, deque
from typing import Callable

WINDOW_SECONDS = 60.0
FAILURES_PER_ADDRESS = 5
FAILURES_PER_DEVICE = 5
FAILURES_BEFORE_STRICT = 100
STRICT_FAILURES_PER_ADDRESS = 1
FAILURE_WINDOW_SECONDS = 15 * 60
MAX_TRACKED_ADDRESSES = 10000
IPV6_NETWORK_BITS = 64
STRICT_IPV4_NETWORK_BITS = 24
STRICT_IPV6_NETWORK_BITS = 48


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


def failure_bucket(address: str, strict: bool = False) -> str:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    if parsed.version == 6 and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    if parsed.version == 4:
        return str(ipaddress.IPv4Network((int(parsed), STRICT_IPV4_NETWORK_BITS), strict=False)) if strict else str(parsed)
    bits = STRICT_IPV6_NETWORK_BITS if strict else IPV6_NETWORK_BITS
    return str(ipaddress.IPv6Network((int(parsed), bits), strict=False))


def _is_in(address: str, networks) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in networks)


def visitor_address(peer: str, forwarded_for: str | None, trusted_proxies) -> str:
    if not _is_in(peer, trusted_proxies):
        return peer
    client = peer
    for hop in reversed((forwarded_for or "").split(",")):
        try:
            client = str(ipaddress.ip_address(hop.strip()))
        except ValueError:
            return client
        if not _is_in(client, trusted_proxies):
            return client
    return client


class FailureLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic, per_address: int = FAILURES_PER_ADDRESS,
                 window: float = FAILURE_WINDOW_SECONDS, before_strict: int | None = FAILURES_BEFORE_STRICT,
                 max_tracked: int = MAX_TRACKED_ADDRESSES):
        self.clock = clock
        self.per_address = per_address
        self.window = window
        self.before_strict = before_strict
        self.max_tracked = max_tracked
        self._lock = threading.Lock()
        self._failures: OrderedDict[str, deque] = OrderedDict()
        self._everyone: deque = deque()

    def _forget_old(self, now: float) -> None:
        cutoff = now - self.window
        while self._everyone and self._everyone[0] <= cutoff:
            self._everyone.popleft()
        for key in list(self._failures):
            moments = self._failures[key]
            while moments and moments[0] <= cutoff:
                moments.popleft()
            if not moments:
                del self._failures[key]

    def _is_strict(self) -> bool:
        return self.before_strict is not None and len(self._everyone) >= self.before_strict

    def _buckets(self, key: str) -> tuple[str, ...]:
        if self._is_strict():
            return failure_bucket(key), failure_bucket(key, strict=True)
        return (failure_bucket(key),)

    def _seconds_left(self, moments, now: float) -> int:
        limit = STRICT_FAILURES_PER_ADDRESS if self._is_strict() else self.per_address
        if not moments or len(moments) < limit:
            return 0
        return max(1, int(moments[len(moments) - limit] + self.window - now) + 1)

    def _wait_for(self, buckets, now: float) -> int:
        return max(self._seconds_left(self._failures.get(bucket), now) for bucket in buckets)

    def _make_room(self, now: float) -> int:
        if len(self._failures) < self.max_tracked:
            return 0
        unblocked = next((key for key, moments in self._failures.items() if not self._seconds_left(moments, now)), None)
        if unblocked is not None:
            del self._failures[unblocked]
            return 0
        return min(self._seconds_left(moments, now) for moments in self._failures.values())

    def seconds_blocked(self, key: str) -> int:
        with self._lock:
            now = self.clock()
            self._forget_old(now)
            return self._wait_for(self._buckets(key), now)

    def take_turn(self, key: str) -> int:
        with self._lock:
            now = self.clock()
            self._forget_old(now)
            buckets = self._buckets(key)
            counted = buckets[-1]
            wait = self._wait_for(buckets, now)
            if not wait and counted not in self._failures:
                wait = self._make_room(now)
            if wait:
                return wait
            moments = self._failures.setdefault(counted, deque())
            moments.append(now)
            self._failures.move_to_end(counted)
            if self.before_strict is not None:
                self._everyone.append(now)
            return 0

    def succeeded(self, key: str) -> None:
        with self._lock:
            buckets = {failure_bucket(key), failure_bucket(key, strict=True)}
            cleared = [self._failures.pop(bucket) for bucket in buckets if bucket in self._failures]
            latest = max((moments[-1] for moments in cleared if moments), default=None)
            if latest is not None and self.before_strict is not None and latest in self._everyone:
                self._everyone.remove(latest)
