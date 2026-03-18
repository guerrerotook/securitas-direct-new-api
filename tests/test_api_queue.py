"""Tests for ApiQueue — priority-based API rate limiter."""

import asyncio
import time

import pytest

from custom_components.securitas.api_queue import ApiQueue

pytestmark = pytest.mark.asyncio


class TestApiQueueBasic:
    """Basic submit and rate limiting."""

    async def test_submit_executes_coroutine(self):
        queue = ApiQueue(interval=0)

        async def fn():
            return 42

        result = await queue.submit(fn, priority=ApiQueue.BACKGROUND)
        assert result == 42

    async def test_submit_passes_args(self):
        queue = ApiQueue(interval=0)

        async def fn(a, b):
            return a + b

        result = await queue.submit(fn, 3, 7, priority=ApiQueue.BACKGROUND)
        assert result == 10

    async def test_submit_propagates_exception(self):
        queue = ApiQueue(interval=0)

        async def fn():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await queue.submit(fn, priority=ApiQueue.BACKGROUND)

    async def test_last_api_time_updated_on_success(self):
        queue = ApiQueue(interval=0)
        before = time.monotonic()

        async def fn():
            return 1

        await queue.submit(fn, priority=ApiQueue.BACKGROUND)
        assert queue._last_api_time >= before

    async def test_last_api_time_updated_on_error(self):
        queue = ApiQueue(interval=0)

        async def fn():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await queue.submit(fn, priority=ApiQueue.BACKGROUND)
        assert queue._last_api_time > 0


class TestApiQueueRateLimiting:
    """Minimum gap enforcement."""

    async def test_background_enforces_interval(self):
        queue = ApiQueue(interval=0.1)
        times = []

        async def fn():
            times.append(time.monotonic())

        await queue.submit(fn, priority=ApiQueue.BACKGROUND)
        await queue.submit(fn, priority=ApiQueue.BACKGROUND)
        assert times[1] - times[0] >= 0.09  # allow small float error


class TestApiQueuePriority:
    """Foreground preemption of background work."""

    async def test_foreground_runs_before_queued_background(self):
        """When foreground and background are both waiting, foreground goes first."""
        queue = ApiQueue(interval=0.05)
        order = []

        # Hold the lock with an initial call
        release = asyncio.Event()

        async def blocker():
            await release.wait()
            return "blocker"

        async def bg():
            order.append("bg")

        async def fg():
            order.append("fg")

        # Start blocker (holds the lock)
        blocker_task = asyncio.create_task(
            queue.submit(blocker, priority=ApiQueue.BACKGROUND)
        )
        await asyncio.sleep(0.01)  # let blocker acquire lock

        # Queue background then foreground
        bg_task = asyncio.create_task(queue.submit(bg, priority=ApiQueue.BACKGROUND))
        await asyncio.sleep(0.01)
        fg_task = asyncio.create_task(queue.submit(fg, priority=ApiQueue.FOREGROUND))
        await asyncio.sleep(0.01)

        # Release blocker
        release.set()
        await asyncio.gather(blocker_task, bg_task, fg_task)

        assert order[0] == "fg"
        assert order[1] == "bg"

    async def test_background_yields_while_foreground_pending(self):
        """Background waits while foreground work is pending."""
        queue = ApiQueue(interval=0)
        events = []

        # Simulate: foreground is "pending" (incremented but not yet submitted)
        queue._pending_foreground = 1
        queue._bg_event.clear()

        async def bg():
            events.append("bg")

        # Background should block
        bg_task = asyncio.create_task(queue.submit(bg, priority=ApiQueue.BACKGROUND))
        await asyncio.sleep(0.05)
        assert "bg" not in events  # still waiting

        # Clear foreground
        queue._pending_foreground = 0
        queue._bg_event.set()
        await bg_task
        assert "bg" in events


class TestApiQueueConcurrency:
    """Verify the queue serializes concurrent callers."""

    async def test_concurrent_calls_are_serialized(self):
        """Three concurrent submits must not overlap — each starts after the previous ends."""
        queue = ApiQueue(interval=0.05)
        timestamps = []  # (start, end) pairs

        async def fn():
            start = time.monotonic()
            await asyncio.sleep(0.01)  # simulate work
            end = time.monotonic()
            timestamps.append((start, end))

        tasks = [
            asyncio.create_task(queue.submit(fn, priority=ApiQueue.BACKGROUND))
            for _ in range(3)
        ]
        await asyncio.gather(*tasks)

        assert len(timestamps) == 3
        # Sort by start time and verify no overlap
        timestamps.sort()
        for i in range(1, len(timestamps)):
            assert timestamps[i][0] >= timestamps[i - 1][1], (
                f"Call {i} started at {timestamps[i][0]} before call {i - 1} "
                f"ended at {timestamps[i - 1][1]}"
            )

    async def test_multiple_foreground_callers_all_complete(self):
        """Three concurrent foreground calls all complete with correct results."""
        queue = ApiQueue(interval=0.05)

        async def fn(n):
            await asyncio.sleep(0.01)
            return n * 10

        tasks = [
            asyncio.create_task(queue.submit(fn, i, priority=ApiQueue.FOREGROUND))
            for i in range(3)
        ]
        results = await asyncio.gather(*tasks)

        assert sorted(results) == [0, 10, 20]
        # Counter must be back to zero after all complete
        assert queue._pending_foreground == 0

    async def test_foreground_counter_correct_after_errors(self):
        """A foreground error still decrements the counter, unblocking background."""
        queue = ApiQueue(interval=0)

        async def failing_fg():
            raise RuntimeError("fg error")

        with pytest.raises(RuntimeError, match="fg error"):
            await queue.submit(failing_fg, priority=ApiQueue.FOREGROUND)

        # Counter must be back to zero
        assert queue._pending_foreground == 0
        assert queue._bg_event.is_set()

        # Background should proceed without blocking
        async def bg():
            return "ok"

        result = await queue.submit(bg, priority=ApiQueue.BACKGROUND)
        assert result == "ok"


class TestApiQueueErrorRecovery:
    """Verify errors don't leave the queue in a broken state."""

    async def test_error_does_not_block_subsequent_calls(self):
        """A failed call does not prevent the next call from succeeding."""
        queue = ApiQueue(interval=0)

        async def failing():
            raise ValueError("first")

        async def succeeding():
            return "second"

        with pytest.raises(ValueError, match="first"):
            await queue.submit(failing, priority=ApiQueue.BACKGROUND)

        result = await queue.submit(succeeding, priority=ApiQueue.BACKGROUND)
        assert result == "second"

    async def test_foreground_error_unblocks_background(self):
        """A foreground error releases the bg_event so background can proceed."""
        queue = ApiQueue(interval=0)
        events = []

        async def failing_fg():
            raise RuntimeError("fg boom")

        async def bg():
            events.append("bg")
            return "bg done"

        # Start background first — it will block once foreground is pending
        release = asyncio.Event()

        async def slow_bg():
            await release.wait()
            # Now submit the real background call after the foreground error
            return await queue.submit(bg, priority=ApiQueue.BACKGROUND)

        # Submit and fail a foreground call
        with pytest.raises(RuntimeError, match="fg boom"):
            await queue.submit(failing_fg, priority=ApiQueue.FOREGROUND)

        # Background should not be blocked
        assert queue._pending_foreground == 0
        assert queue._bg_event.is_set()

        result = await queue.submit(bg, priority=ApiQueue.BACKGROUND)
        assert result == "bg done"
        assert "bg" in events

    async def test_last_api_time_updated_even_on_error_with_interval(self):
        """Error still updates _last_api_time, so subsequent calls respect throttle."""
        queue = ApiQueue(interval=0.05)

        async def failing():
            raise RuntimeError("fail")

        async def succeeding():
            return time.monotonic()

        with pytest.raises(RuntimeError):
            await queue.submit(failing, priority=ApiQueue.BACKGROUND)

        error_time = queue._last_api_time
        assert error_time > 0

        result = await queue.submit(succeeding, priority=ApiQueue.BACKGROUND)
        # The successful call must have waited for the interval after the error
        assert result >= error_time + 0.04  # allow small float tolerance
