"""Priority-based API rate limiter for Verisure OWA.

All API calls go through an ApiQueue which enforces a minimum gap between
requests and lets foreground (user-initiated) requests preempt background
(periodic polling) work.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable, Coroutine
from typing import Any

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
    cancelled — preemption happens between calls.  Within a level, callers
    are served in the order they arrived: a caller submitting back to back
    must not starve one that queued before its next call.
    """

    FOREGROUND = 0
    BACKGROUND = 1

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self._interval: float = interval
        self._last_api_time: float = 0
        self._waiting: dict[int, deque[object]] = {
            self.FOREGROUND: deque(),
            self.BACKGROUND: deque(),
        }
        self._busy: bool = False
        self._turn = asyncio.Condition()

    def _is_next(self, ticket: object, priority: int) -> bool:
        if self._busy:
            return False
        if priority == self.BACKGROUND and self._waiting[self.FOREGROUND]:
            return False
        return self._waiting[priority][0] is ticket

    async def submit(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        priority: int = BACKGROUND,
        label: str | None = None,
    ) -> Any:
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
        ticket = object()
        line = self._waiting[priority]
        line.append(ticket)
        try:
            while True:
                async with self._turn:
                    await self._turn.wait_for(lambda: self._is_next(ticket, priority))
                    delay = self._interval - (time.monotonic() - self._last_api_time)
                    if delay <= 0:
                        line.popleft()
                        self._busy = True
                        break
                # Sleep out the gap without holding the turn, then check again:
                # foreground work may have arrived in the meantime.
                _LOGGER.debug(
                    "[queue] Throttling %.1fs (%s) for %s",
                    delay,
                    "fg" if priority == self.FOREGROUND else "bg",
                    label,
                )
                await asyncio.sleep(delay)
        except BaseException:
            if ticket in line:
                line.remove(ticket)
                async with self._turn:
                    self._turn.notify_all()
            raise

        try:
            return await coro_fn(*args)
        finally:
            self._last_api_time = time.monotonic()
            self._busy = False
            async with self._turn:
                self._turn.notify_all()
