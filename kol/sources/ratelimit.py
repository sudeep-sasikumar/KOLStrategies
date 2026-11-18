from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Spaces calls evenly: at most `rate` per second."""

    def __init__(self, rate: float):
        self.interval = 1.0 / rate
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
                now = self._next
            self._next = now + self.interval

    def penalize(self, seconds: float) -> None:
        """Push the next allowed call back (after a 429)."""
        self._next = max(self._next, time.monotonic() + seconds)
