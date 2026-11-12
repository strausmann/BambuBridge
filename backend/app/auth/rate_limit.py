"""Per-token sliding-window rate limit (60 s window).

The state lives in process memory: with several worker processes every process counts
on its own, so the effective limit is ``limit x processes``. BambuBridge runs one
process; a restart starts every window fresh.
"""

from __future__ import annotations

import ipaddress
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable

WINDOW_SECONDS = 60.0
MAX_KEYS = 10_000


class SlidingWindowRateLimiter:
    """Counts accepted hits per key within the last ``window`` seconds."""

    def __init__(
        self,
        *,
        window: float = WINDOW_SECONDS,
        max_keys: int = MAX_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = window
        self._max_keys = max_keys
        self._clock = clock
        # Least recently used first; bounded because keys come from requests.
        self._hits: OrderedDict[Hashable, deque[float]] = OrderedDict()

    def hit(self, key: Hashable, *, limit: int) -> tuple[bool, int]:
        """Record one hit if allowed. Returns ``(allowed, retry_after_seconds)``.

        A rejected hit is not recorded, so a client that keeps retrying is let in
        again as soon as its oldest accepted hit leaves the window.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        else:
            self._hits.move_to_end(key)
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, math.ceil(hits[0] + self._window - now))
            return False, retry_after
        hits.append(now)
        while len(self._hits) > self._max_keys:
            self._hits.popitem(last=False)
        return True, 0

    def peek(self, key: Hashable, *, limit: int) -> tuple[bool, int]:
        """Like :meth:`hit`, but records nothing: would one more hit be allowed now?"""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        hits = self._hits.get(key)
        if not hits:
            return True, 0
        now = self._clock()
        recent = [t for t in hits if t > now - self._window]
        if len(recent) >= limit:
            return False, max(1, math.ceil(recent[0] + self._window - now))
        return True, 0

    def reset(self, key: Hashable) -> None:
        """Forget a key (e.g. after its token was deleted)."""
        self._hits.pop(key, None)

    def tracked_keys(self) -> int:
        return len(self._hits)


def client_key(host: str | None) -> str:
    """Normalised client address for per-client limits.

    Behind the reverse proxy this is the forwarded client: the entrypoint trusts proxy
    headers from exactly one address (``FORWARDED_ALLOW_IPS``). Anything that is not an IP
    address shares one bucket instead of opening its own.
    """
    try:
        return str(ipaddress.ip_address((host or "").strip()))
    except ValueError:
        return "unknown"
