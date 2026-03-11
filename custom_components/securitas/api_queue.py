"""Priority-based API rate limiter for Securitas Direct.

All API calls go through an ApiQueue which enforces a minimum gap between
requests and lets foreground (user-initiated) requests preempt background
(periodic polling) work.
"""

import asyncio
import logging
import time

_LOGGER = logging.getLogger(__name__)

# Default intervals
DEFAULT_INTERVAL: float = 2.0


class ApiQueue:
    """Serialize API calls with priority-based rate limiting.

    Two priority levels:
    - FOREGROUND: arm/disarm, lock changes, setup/discovery, and their
      status polls.
    - BACKGROUND: periodic alarm status, sentinel, air quality, lock
      status reads.

    Both levels share the same minimum gap (interval).  Foreground requests
    preempt queued background work.  In-flight API calls are never
    cancelled — preemption happens between calls.
    """

    FOREGROUND = 0
    BACKGROUND = 1

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self._intervals = {
            self.FOREGROUND: interval,
            self.BACKGROUND: interval,
        }
        self._lock = asyncio.Lock()
        self._last_api_time: float = 0
        self._pending_foreground: int = 0
        self._bg_event = asyncio.Event()
        self._bg_event.set()  # initially no foreground work pending

    async def submit(
        self, coro_fn, *args, priority: int = BACKGROUND, label: str | None = None
    ):
        """Submit an API call and wait for its result.

        Args:
            coro_fn: Async callable (not a coroutine — the queue calls it).
            *args: Arguments passed to coro_fn.
            priority: FOREGROUND or BACKGROUND.
            label: Human-readable name for log messages (defaults to coro_fn.__name__).

        Returns:
            The result of coro_fn(*args).

        Raises:
            Whatever coro_fn raises — exceptions propagate to the caller.
        """
        if label is None:
            label = getattr(coro_fn, "__name__", str(coro_fn))
        # Safe without lock: asyncio is single-threaded and these are
        # synchronous operations with no await in between.
        if priority == self.FOREGROUND:
            self._pending_foreground += 1
            self._bg_event.clear()

        try:
            while True:
                # Background callers wait while foreground work is pending
                if priority == self.BACKGROUND:
                    while self._pending_foreground > 0:
                        await self._bg_event.wait()

                # Compute throttle delay outside the lock so we don't block
                # other callers (especially foreground) during the sleep.
                interval = self._intervals[priority]
                elapsed = time.monotonic() - self._last_api_time
                if elapsed < interval:
                    delay = interval - elapsed
                    _LOGGER.debug(
                        "[queue] Throttling %.1fs (%s) for %s",
                        delay,
                        "fg" if priority == self.FOREGROUND else "bg",
                        label,
                    )
                    await asyncio.sleep(delay)

                async with self._lock:
                    # Background must re-check after acquiring lock — foreground
                    # may have arrived while we were waiting on the lock.
                    if priority == self.BACKGROUND and self._pending_foreground > 0:
                        # Release lock and loop back to yield to foreground
                        continue

                    # Re-check throttle after acquiring lock — another caller
                    # may have made a request while we were sleeping/waiting.
                    elapsed = time.monotonic() - self._last_api_time
                    if elapsed < interval:
                        # Need to wait more — release lock and loop back
                        continue

                    try:
                        result = await coro_fn(*args)
                    finally:
                        self._last_api_time = time.monotonic()

                    return result
        finally:
            if priority == self.FOREGROUND:
                self._pending_foreground -= 1
                if self._pending_foreground == 0:
                    self._bg_event.set()
