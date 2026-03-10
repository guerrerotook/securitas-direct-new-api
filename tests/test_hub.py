"""Tests for SecuritasHub orchestration methods."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.securitas.api_queue import ApiQueue
from custom_components.securitas.const import API_CACHE_TTL
from custom_components.securitas.hub import SecuritasHub
from custom_components.securitas.securitas_direct_new_api import (
    OperationStatus,
    SecuritasDirectError,
)

from .conftest import make_installation

pytestmark = pytest.mark.asyncio


def make_hub() -> SecuritasHub:
    """Create a SecuritasHub with a real ApiQueue and mocked session."""
    hass = MagicMock()
    hass.data = {}
    config = {
        "username": "test@example.com",
        "password": "pass",
        "country": "ES",
        "device_id": "dev",
        "unique_id": "uid",
        "idDeviceIndigitall": "indi",
        "delay_check_operation": 0.01,
    }
    hub = SecuritasHub(config, config_entry=None, http_client=MagicMock(), hass=hass)
    hub._api_queue = ApiQueue(interval=0)
    hub.session = MagicMock()
    hub.session.delay_check_operation = 0.01
    return hub


# ── _cached_api_call tests ──────────────────────────────────────────────────


class TestCachedApiCall:
    """Tests for _cached_api_call."""

    async def test_cache_miss_calls_api(self):
        """First call should invoke the API and cache the result."""
        hub = make_hub()
        api_fn = AsyncMock(return_value="result_a")

        result = await hub._cached_api_call("key1", api_fn, "arg1")

        assert result == "result_a"
        api_fn.assert_awaited_once_with("arg1")
        assert hub._api_cache["key1"] == "result_a"

    async def test_cache_hit_skips_api(self):
        """Second call within TTL should return cached value without calling API."""
        hub = make_hub()
        api_fn = AsyncMock(return_value="result_a")

        await hub._cached_api_call("key1", api_fn, "arg1")
        api_fn.reset_mock()

        result = await hub._cached_api_call("key1", api_fn, "arg1")

        assert result == "result_a"
        api_fn.assert_not_awaited()

    async def test_cache_expired_calls_api_again(self):
        """After TTL expires, API should be called again."""
        hub = make_hub()
        api_fn = AsyncMock(return_value="result_a")

        await hub._cached_api_call("key1", api_fn, "arg1")
        api_fn.reset_mock()
        api_fn.return_value = "result_b"

        # Simulate cache expiry by backdating the timestamp
        hub._api_cache_time["key1"] = time.monotonic() - API_CACHE_TTL - 1

        result = await hub._cached_api_call("key1", api_fn, "arg1")

        assert result == "result_b"
        api_fn.assert_awaited_once()

    async def test_none_result_not_cached(self):
        """When API returns None, cache should not be updated."""
        hub = make_hub()
        api_fn = AsyncMock(return_value=None)

        result = await hub._cached_api_call("key1", api_fn)

        assert result is None
        assert "key1" not in hub._api_cache

    async def test_custom_priority(self):
        """Priority parameter should be forwarded to the queue."""
        hub = make_hub()
        api_fn = AsyncMock(return_value="val")

        # Just verify it completes without error with a custom priority
        result = await hub._cached_api_call(
            "key1", api_fn, priority=ApiQueue.FOREGROUND
        )
        assert result == "val"


# ── change_lock_mode tests ──────────────────────────────────────────────────


class TestChangeLockMode:
    """Tests for change_lock_mode."""

    async def test_success_first_poll(self):
        """Lock mode change succeeds on first poll attempt."""
        hub = make_hub()
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(
            return_value={"res": "OK", "data": "locked"}
        )
        hub.session.process_lock_mode_result = MagicMock(return_value="processed")

        result = await hub.change_lock_mode(installation, True, "device-1")

        assert result == "processed"
        hub.session.submit_change_lock_mode_request.assert_awaited_once_with(
            installation, True, "device-1"
        )
        hub.session.process_lock_mode_result.assert_called_once_with(
            {"res": "OK", "data": "locked"}
        )

    async def test_success_after_wait(self):
        """Lock mode change succeeds after initial WAIT responses."""
        hub = make_hub()
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(
            side_effect=[
                {"res": "WAIT"},
                {"res": "WAIT"},
                {"res": "OK", "mode": "locked"},
            ]
        )
        hub.session.process_lock_mode_result = MagicMock(return_value="done")

        result = await hub.change_lock_mode(installation, True, "device-1")

        assert result == "done"
        assert hub.session.check_change_lock_mode.await_count == 3

    async def test_timeout_raises(self):
        """TimeoutError raised when all poll attempts return WAIT."""
        hub = make_hub()
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(return_value={"res": "WAIT"})

        with pytest.raises(TimeoutError, match="Lock mode change timed out"):
            await hub.change_lock_mode(installation, False, "device-1")


# ── refresh_alarm_status tests ──────────────────────────────────────────────


class TestRefreshAlarmStatus:
    """Tests for refresh_alarm_status."""

    async def test_returns_on_protom_response(self):
        """Returns immediately when protomResponse is present."""
        hub = make_hub()
        installation = make_installation()
        status = OperationStatus(protomResponse="ARM1")
        hub.session.check_alarm = AsyncMock(return_value="ref-456")
        hub.session.check_alarm_status = AsyncMock(return_value=status)

        result = await hub.refresh_alarm_status(installation)

        assert result is status
        assert result.protomResponse == "ARM1"
        hub.session.check_alarm_status.assert_awaited_once()

    async def test_returns_on_non_wait_status(self):
        """Returns when operation_status is not WAIT (even without protomResponse)."""
        hub = make_hub()
        installation = make_installation()
        status = OperationStatus(operation_status="ERROR", protomResponse="")
        hub.session.check_alarm = AsyncMock(return_value="ref-456")
        hub.session.check_alarm_status = AsyncMock(return_value=status)

        result = await hub.refresh_alarm_status(installation)

        assert result is status

    async def test_waits_then_returns(self):
        """Polls through WAIT responses until protomResponse arrives."""
        hub = make_hub()
        installation = make_installation()
        wait_status = OperationStatus(operation_status="WAIT", protomResponse="")
        ok_status = OperationStatus(protomResponse="DARM1")
        hub.session.check_alarm = AsyncMock(return_value="ref-456")
        hub.session.check_alarm_status = AsyncMock(
            side_effect=[wait_status, wait_status, ok_status]
        )

        result = await hub.refresh_alarm_status(installation)

        assert result is ok_status
        assert hub.session.check_alarm_status.await_count == 3

    async def test_timeout_raises(self):
        """TimeoutError raised when all attempts return WAIT."""
        hub = make_hub()
        installation = make_installation()
        wait_status = OperationStatus(operation_status="WAIT", protomResponse="")
        hub.session.check_alarm = AsyncMock(return_value="ref-456")
        hub.session.check_alarm_status = AsyncMock(return_value=wait_status)

        with pytest.raises(TimeoutError, match="Alarm status refresh timed out"):
            await hub.refresh_alarm_status(installation)


# ── get_lock_modes tests ────────────────────────────────────────────────────


class TestGetLockModes:
    """Tests for get_lock_modes with TTL cache."""

    async def test_cache_miss_calls_api(self):
        """First call fetches from API and caches the result."""
        hub = make_hub()
        installation = make_installation()
        modes = [{"id": "lock-1", "mode": "locked"}]
        hub.session.get_lock_current_mode = AsyncMock(return_value=modes)

        result = await hub.get_lock_modes(installation)

        assert result == modes
        hub.session.get_lock_current_mode.assert_awaited_once_with(installation)
        assert hub._lock_modes[installation.number] == modes

    async def test_cache_hit_skips_api(self):
        """Second call within TTL returns cached value."""
        hub = make_hub()
        installation = make_installation()
        modes = [{"id": "lock-1", "mode": "locked"}]
        hub.session.get_lock_current_mode = AsyncMock(return_value=modes)

        await hub.get_lock_modes(installation)
        hub.session.get_lock_current_mode.reset_mock()

        result = await hub.get_lock_modes(installation)

        assert result == modes
        hub.session.get_lock_current_mode.assert_not_awaited()

    async def test_cache_expired_calls_api_again(self):
        """After TTL expires, fetches from API again."""
        hub = make_hub()
        installation = make_installation()
        hub.session.get_lock_current_mode = AsyncMock(return_value=["old"])

        await hub.get_lock_modes(installation)
        hub.session.get_lock_current_mode.reset_mock()
        hub.session.get_lock_current_mode.return_value = ["new"]

        # Backdate to simulate expiry
        hub._lock_modes_time[installation.number] = time.monotonic() - API_CACHE_TTL - 1

        result = await hub.get_lock_modes(installation)

        assert result == ["new"]
        hub.session.get_lock_current_mode.assert_awaited_once()

    async def test_securitas_error_returns_empty_list(self):
        """SecuritasDirectError is caught and returns an empty list."""
        hub = make_hub()
        installation = make_installation()
        hub.session.get_lock_current_mode = AsyncMock(
            side_effect=SecuritasDirectError("API failure", http_status=500)
        )

        result = await hub.get_lock_modes(installation)

        assert result == []
        # Empty list should still be cached
        assert hub._lock_modes[installation.number] == []
