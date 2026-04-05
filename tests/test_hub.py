"""Tests for SecuritasHub orchestration methods."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.securitas.api_queue import ApiQueue
from custom_components.securitas.const import (
    API_CACHE_TTL,
    SIGNAL_CAMERA_STATE,
    SIGNAL_CAMERA_UPDATE,
)
from custom_components.securitas.hub import SecuritasHub
from custom_components.securitas.securitas_direct_new_api import (
    OperationStatus,
    SecuritasDirectError,
)
from custom_components.securitas.securitas_direct_new_api.models import (
    CameraDevice,
    ThumbnailResponse,
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

    _STATUS_NOT_FOUND = {
        "res": "OK",
        "msg": "alarm-manager.error_status_not_found",
        "protomResponse": None,
        "status": None,
    }

    async def test_acknowledged_on_first_poll(self):
        """error_status_not_found on first poll breaks out and waits."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 0  # skip sleep in tests
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(
            return_value=self._STATUS_NOT_FOUND,
        )

        await hub.change_lock_mode(installation, True, "device-1")

        hub.session.submit_change_lock_mode_request.assert_awaited_once_with(
            installation, True, "device-1"
        )
        # Should break on first error_status_not_found, not poll further
        assert hub.session.check_change_lock_mode.await_count == 1
        # Cache should be invalidated
        assert installation.number not in hub._lock_modes_time

    async def test_acknowledged_after_wait(self):
        """WAIT responses then error_status_not_found breaks out."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 0
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(
            side_effect=[
                {"res": "WAIT"},
                {"res": "WAIT"},
                self._STATUS_NOT_FOUND,
            ]
        )

        await hub.change_lock_mode(installation, True, "device-1")

        assert hub.session.check_change_lock_mode.await_count == 3

    async def test_real_status_response_returns_immediately(self):
        """A non-WAIT, non-error_status_not_found response returns immediately."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 0
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(
            return_value={"res": "OK", "data": "locked"}
        )

        await hub.change_lock_mode(installation, True, "device-1")

        assert hub.session.check_change_lock_mode.await_count == 1
        assert installation.number not in hub._lock_modes_time

    async def test_wait_exhausted_without_ack(self):
        """All WAIT responses exhaust attempts; cache still invalidated."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 0
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(return_value={"res": "WAIT"})

        with patch.object(hub, "_max_poll_attempts", return_value=3):
            await hub.change_lock_mode(installation, False, "device-1")

        assert hub.session.check_change_lock_mode.await_count == 3
        assert installation.number not in hub._lock_modes_time

    async def test_retries_on_error_no_response_to_request(self):
        """error_no_response_to_request is treated as transient; polling continues."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 0
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")

        def _make_no_response_err():
            _e = SecuritasDirectError(
                "alarm-manager.error_no_response_to_request", http_status=200
            )
            _e.response_body = {"errors": [], "data": None}
            return _e

        hub.session.check_change_lock_mode = AsyncMock(
            side_effect=[
                _make_no_response_err(),
                _make_no_response_err(),
                self._STATUS_NOT_FOUND,
            ]
        )

        await hub.change_lock_mode(installation, True, "device-1")

        assert hub.session.check_change_lock_mode.await_count == 3

    async def test_error_no_response_exhausted_raises(self):
        """If all attempts return error_no_response, the last error is raised."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 0
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        _no_response_err = SecuritasDirectError(
            "alarm-manager.error_no_response_to_request", http_status=200
        )
        _no_response_err.response_body = {"errors": [], "data": None}
        hub.session.check_change_lock_mode = AsyncMock(side_effect=_no_response_err)

        with patch.object(hub, "_max_poll_attempts", return_value=3):
            with pytest.raises(SecuritasDirectError, match="error_no_response"):
                await hub.change_lock_mode(installation, False, "device-1")

        assert hub.session.check_change_lock_mode.await_count == 3

    async def test_non_transient_error_propagates_immediately(self):
        """Errors other than error_no_response_to_request are not retried."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 0
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        _other_err = SecuritasDirectError("some-other-error", http_status=500)
        _other_err.response_body = {"errors": [], "data": None}
        hub.session.check_change_lock_mode = AsyncMock(side_effect=_other_err)

        with pytest.raises(SecuritasDirectError, match="some-other-error"):
            await hub.change_lock_mode(installation, True, "device-1")

        assert hub.session.check_change_lock_mode.await_count == 1

    async def test_min_wait_sleeps_remaining_time(self):
        """After quick acknowledgement, sleeps for the remaining min wait."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 6.0
        installation = make_installation()
        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(
            return_value=self._STATUS_NOT_FOUND,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await hub.change_lock_mode(installation, True, "device-1")

        # Should have slept for approximately _LOCK_CMD_MIN_WAIT
        mock_sleep.assert_awaited_once()
        slept = mock_sleep.call_args[0][0]
        assert 4.0 < slept <= 6.0  # allows for small elapsed time

    async def test_cache_invalidated_on_status_not_found(self):
        """Cache is invalidated when command is acknowledged."""
        hub = make_hub()
        hub._LOCK_CMD_MIN_WAIT = 0
        installation = make_installation()
        hub._lock_modes_time[installation.number] = 12345.0
        hub._lock_modes[installation.number] = ["stale"]

        hub.session.submit_change_lock_mode_request = AsyncMock(return_value="ref-123")
        hub.session.check_change_lock_mode = AsyncMock(
            return_value=self._STATUS_NOT_FOUND,
        )

        await hub.change_lock_mode(installation, True, "device-1")

        assert installation.number not in hub._lock_modes_time


# ── refresh_alarm_status tests ──────────────────────────────────────────────


class TestRefreshAlarmStatus:
    """Tests for refresh_alarm_status."""

    async def test_returns_on_protom_response(self):
        """Returns immediately when protomResponse is present."""
        hub = make_hub()
        installation = make_installation()
        status = OperationStatus(protom_response="ARM1")
        hub.session.check_alarm = AsyncMock(return_value="ref-456")
        hub.session.check_alarm_status = AsyncMock(return_value=status)

        result = await hub.refresh_alarm_status(installation)

        assert result is status
        assert result.protom_response == "ARM1"
        hub.session.check_alarm_status.assert_awaited_once()

    async def test_returns_on_non_wait_status(self):
        """Returns when operation_status is not WAIT (even without protomResponse)."""
        hub = make_hub()
        installation = make_installation()
        status = OperationStatus(operation_status="ERROR", protom_response="")
        hub.session.check_alarm = AsyncMock(return_value="ref-456")
        hub.session.check_alarm_status = AsyncMock(return_value=status)

        result = await hub.refresh_alarm_status(installation)

        assert result is status

    async def test_waits_then_returns(self):
        """Polls through WAIT responses until protomResponse arrives."""
        hub = make_hub()
        installation = make_installation()
        wait_status = OperationStatus(operation_status="WAIT", protom_response="")
        ok_status = OperationStatus(protom_response="DARM1")
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
        wait_status = OperationStatus(operation_status="WAIT", protom_response="")
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


# ── capture_image tests ─────────────────────────────────────────────────────


def make_camera_device(**overrides) -> CameraDevice:
    defaults = {
        "id": "11",
        "code": 10,
        "zone_id": "QR10",
        "name": "Salon",
        "device_type": "QR",
    }
    defaults.update(overrides)
    return CameraDevice(**defaults)


def make_thumbnail(**overrides) -> ThumbnailResponse:
    defaults: dict = {
        "id_signal": None,
        "image": None,
        "timestamp": None,
        "device_code": None,
        "device_alias": None,
        "signal_type": None,
    }
    defaults.update(overrides)
    return ThumbnailResponse(**defaults)


def _setup_capture(hub, *, baseline_id="sig1", new_id="sig2", new_image=b"\xff\xd8"):
    """Wire session mocks for a standard successful capture."""
    baseline = make_thumbnail(id_signal=baseline_id, timestamp="2026-03-11 10:00:00")
    new_thumb = make_thumbnail(
        id_signal=new_id, image="base64data", timestamp="2026-03-11 10:01:00"
    )
    hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
    hub.session.request_images = AsyncMock(return_value="ref-001")
    hub.session.check_request_images_status = AsyncMock(
        return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
    )
    hub._validate_and_store_image = MagicMock(return_value=new_image)
    return baseline, new_thumb


class TestCaptureImage:
    """Tests for capture_image hub method."""

    async def test_capturing_flag_cleared_after_success(self):
        """_camera_capturing is empty after a successful capture."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        _setup_capture(hub)

        with patch("custom_components.securitas.hub.async_dispatcher_send"):
            await hub.capture_image(installation, device)

        assert not hub.is_capturing(installation.number, device.zone_id)

    async def test_is_capturing_true_during_capture(self):
        """is_capturing returns True once key is added to _camera_capturing."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        capture_key = f"{installation.number}_{device.zone_id}"

        hub._camera_capturing.add(capture_key)
        assert hub.is_capturing(installation.number, device.zone_id) is True

        hub._camera_capturing.discard(capture_key)
        assert hub.is_capturing(installation.number, device.zone_id) is False

    async def test_camera_state_signal_dispatched_at_start(self):
        """SIGNAL_CAMERA_STATE is dispatched immediately when capture starts."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        _setup_capture(hub)

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)

        # First dispatch must be SIGNAL_CAMERA_STATE
        assert calls[0][1] == SIGNAL_CAMERA_STATE

    async def test_camera_update_signal_dispatched_on_success(self):
        """SIGNAL_CAMERA_UPDATE is dispatched when a new image is captured."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        _setup_capture(hub)

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)

        signal_names = [c[1] for c in calls]
        assert SIGNAL_CAMERA_UPDATE in signal_names

    async def test_camera_state_signal_dispatched_when_no_image(self):
        """SIGNAL_CAMERA_STATE (not UPDATE) is dispatched when no image arrives."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        _setup_capture(hub)
        # Simulate validate returning None (no valid JPEG)
        hub._validate_and_store_image = MagicMock(return_value=None)

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)

        signal_names = [c[1] for c in calls]
        assert SIGNAL_CAMERA_UPDATE not in signal_names
        # Last signal should be SIGNAL_CAMERA_STATE to clear the spinner
        assert calls[-1][1] == SIGNAL_CAMERA_STATE

    async def test_missed_baseline_stored_and_update_fired(self):
        """If baseline image differs from stored, it's stored + SIGNAL_CAMERA_UPDATE fired."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        # Stored timestamp differs from what API returns → missed update
        key = f"{installation.number}_{device.zone_id}"
        hub.camera_timestamps[key] = "2026-03-10 09:00:00"

        baseline = make_thumbnail(
            id_signal="sig1", image="base64data", timestamp="2026-03-11 10:00:00"
        )
        new_thumb = make_thumbnail(
            id_signal="sig2", image="newdata", timestamp="2026-03-11 10:01:00"
        )
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
        )
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)

        # _validate_and_store_image called twice: once for baseline, once for new
        assert hub._validate_and_store_image.call_count == 2
        # SIGNAL_CAMERA_UPDATE fired at least twice
        update_calls = [c for c in calls if c[1] == SIGNAL_CAMERA_UPDATE]
        assert len(update_calls) >= 2

    async def test_no_missed_baseline_when_timestamps_match(self):
        """If baseline timestamp matches stored, baseline image is not re-stored."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        same_ts = "2026-03-11 10:00:00"
        key = f"{installation.number}_{device.zone_id}"
        hub.camera_timestamps[key] = same_ts

        baseline = make_thumbnail(
            id_signal="sig1", image="base64data", timestamp=same_ts
        )
        new_thumb = make_thumbnail(
            id_signal="sig2", image="newdata", timestamp="2026-03-11 10:01:00"
        )
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
        )
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        with patch("custom_components.securitas.hub.async_dispatcher_send"):
            await hub.capture_image(installation, device)

        # _validate_and_store_image called once (only for new thumbnail, not baseline)
        assert hub._validate_and_store_image.call_count == 1

    async def test_timeout_during_status_poll_fetches_thumbnail_and_returns(self):
        """When the 30-second wall-clock timeout fires during status polling,
        capture_image fetches one final thumbnail and returns without raising."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        baseline = make_thumbnail(id_signal="sig1", timestamp="2026-03-11 10:00:00")
        fallback = make_thumbnail(
            id_signal="sig1", image="stale_data", timestamp="2026-03-11 10:00:00"
        )
        # First get_thumbnail = baseline; second = fallback fetch after timeout
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, fallback])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        # Status check always returns "processing" — would loop forever without timeout
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.processing"}
        )
        hub._validate_and_store_image = MagicMock(return_value=None)

        async def _immediate_timeout(coro, *, timeout):
            coro.close()
            raise TimeoutError

        with (
            patch("custom_components.securitas.hub.async_dispatcher_send"),
            patch(
                "custom_components.securitas.hub.asyncio.wait_for", _immediate_timeout
            ),
        ):
            await hub.capture_image(installation, device)

        # Fallback thumbnail fetched after timeout
        assert hub.session.get_thumbnail.await_count == 2
        # capturing flag cleared even on timeout
        assert not hub.is_capturing(installation.number, device.zone_id)

    async def test_timeout_during_thumbnail_poll_uses_last_seen_thumbnail(self):
        """When timeout fires during thumbnail polling, capturing is always cleared."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        baseline = make_thumbnail(id_signal="sig1", timestamp="2026-03-11 10:00:00")
        # idSignal never changes — thumbnail poll would loop forever without timeout
        hub.session.get_thumbnail = AsyncMock(return_value=baseline)
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
        )
        hub._validate_and_store_image = MagicMock(return_value=None)

        async def _immediate_timeout(coro, *, timeout):
            coro.close()
            raise TimeoutError

        with (
            patch("custom_components.securitas.hub.async_dispatcher_send"),
            patch(
                "custom_components.securitas.hub.asyncio.wait_for", _immediate_timeout
            ),
        ):
            await hub.capture_image(installation, device)

        # capturing cleared regardless
        assert not hub.is_capturing(installation.number, device.zone_id)

    async def test_polling_stops_after_status_success(self):
        """Status poll exits as soon as the response no longer contains 'processing'."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        baseline = make_thumbnail(id_signal="sig1", timestamp="2026-03-11 10:00:00")
        new_thumb = make_thumbnail(
            id_signal="sig2", image="newdata", timestamp="2026-03-11 10:01:00"
        )
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            side_effect=[
                {"res": "OK", "msg": "alarm-manager.photo-request.processing"},
                {"res": "OK", "msg": "alarm-manager.photo-request.processing"},
                {"res": "OK", "msg": "alarm-manager.photo-request.success"},
            ]
        )
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        with patch("custom_components.securitas.hub.async_dispatcher_send"):
            await hub.capture_image(installation, device)

        assert hub.session.check_request_images_status.await_count == 3

    async def test_capturing_cleared_on_timeout(self):
        """The capturing flag is always cleared, even when the timeout fires."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        baseline = make_thumbnail(id_signal="sig1", timestamp="2026-03-11 10:00:00")
        fallback = make_thumbnail(id_signal="sig1", image=None, timestamp=None)
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, fallback])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "processing"}
        )
        hub._validate_and_store_image = MagicMock(return_value=None)

        async def _immediate_timeout(coro, *, timeout):
            coro.close()
            raise TimeoutError

        with (
            patch("custom_components.securitas.hub.async_dispatcher_send"),
            patch(
                "custom_components.securitas.hub.asyncio.wait_for", _immediate_timeout
            ),
        ):
            await hub.capture_image(installation, device)

        assert not hub.is_capturing(installation.number, device.zone_id)


class TestFullImageCapture:
    """Tests for full-resolution image fetching and storage in the hub."""

    async def test_capture_stores_full_image(self):
        """After a successful capture, the full image is stored in _full_images."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        full_jpeg = b"\xff\xd8\xff\xe0full"
        baseline = make_thumbnail(id_signal="sig1", timestamp="2026-03-11 10:00:00")
        new_thumb = make_thumbnail(
            id_signal="sig2",
            image="base64data",
            timestamp="2026-03-11 10:01:00",
            signal_type="16",
        )
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
        )
        hub.session.get_photo_images = AsyncMock(return_value=full_jpeg)
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        _tasks = []
        hub.hass.async_create_task = lambda coro: _tasks.append(coro)

        with patch("custom_components.securitas.hub.async_dispatcher_send"):
            await hub.capture_image(installation, device)
            for task in _tasks:
                await task

        key = f"{installation.number}_{device.zone_id}"
        assert hub._full_images[key] == full_jpeg

    async def test_capture_fires_signal_full_image_update(self):
        """SIGNAL_FULL_IMAGE_UPDATE is dispatched after the full image is stored."""
        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        full_jpeg = b"\xff\xd8\xff\xe0full"
        baseline = make_thumbnail(id_signal="sig1", timestamp="2026-03-11 10:00:00")
        new_thumb = make_thumbnail(
            id_signal="sig2",
            image="base64data",
            timestamp="2026-03-11 10:01:00",
            signal_type="16",
        )
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
        )
        hub.session.get_photo_images = AsyncMock(return_value=full_jpeg)
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        _tasks = []
        hub.hass.async_create_task = lambda coro: _tasks.append(coro)

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)
            for task in _tasks:
                await task

        signal_names = [c[1] for c in calls]
        assert SIGNAL_FULL_IMAGE_UPDATE in signal_names

    async def test_capture_skips_full_image_when_id_signal_is_none(self):
        """PIR cameras (idSignal=None) do not trigger a get_photo_images call."""
        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        baseline = make_thumbnail(id_signal=None, timestamp="2026-03-11 10:00:00")
        new_thumb = make_thumbnail(
            id_signal=None,
            image="newbase64",
            timestamp="2026-03-11 10:01:00",
        )
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
        )
        hub.session.get_photo_images = AsyncMock()
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)

        hub.session.get_photo_images.assert_not_called()
        signal_names = [c[1] for c in calls]
        assert SIGNAL_FULL_IMAGE_UPDATE not in signal_names

    async def test_get_full_image_returns_none_when_empty(self):
        """get_full_image returns None when no full image has been stored."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        result = hub.get_full_image(installation.number, device.zone_id)
        assert result is None

    async def test_get_full_image_returns_stored_bytes(self):
        """get_full_image returns the correct bytes after storage."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        key = f"{installation.number}_{device.zone_id}"
        hub._full_images[key] = b"\xff\xd8full"
        assert (
            hub.get_full_image(installation.number, device.zone_id) == b"\xff\xd8full"
        )

    async def test_get_full_timestamp_returns_stored_value(self):
        """get_full_timestamp returns the timestamp stored alongside the full image."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        key = f"{installation.number}_{device.zone_id}"
        hub._full_timestamps[key] = "2026-03-25 17:40:41"
        assert (
            hub.get_full_timestamp(installation.number, device.zone_id)
            == "2026-03-25 17:40:41"
        )

    async def test_fetch_latest_thumbnail_also_fetches_full_image(self):
        """fetch_latest_thumbnail fires SIGNAL_FULL_IMAGE_UPDATE when id_signal is set."""
        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        full_jpeg = b"\xff\xd8\xff\xe0full"
        thumb = make_thumbnail(
            id_signal="sig1",
            image="base64data",
            timestamp="2026-03-11 10:00:00",
            signal_type="16",
        )
        hub.session.get_thumbnail = AsyncMock(return_value=thumb)
        hub.session.get_photo_images = AsyncMock(return_value=full_jpeg)
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        _tasks = []
        hub.hass.async_create_task = lambda coro: _tasks.append(coro)

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.fetch_latest_thumbnail(installation, device)
            for task in _tasks:
                await task

        signal_names = [c[1] for c in calls]
        assert SIGNAL_FULL_IMAGE_UPDATE in signal_names
        key = f"{installation.number}_{device.zone_id}"
        assert hub._full_images[key] == full_jpeg

    async def test_full_image_not_stored_when_not_jpeg(self):
        """When get_photo_images returns non-JPEG bytes, the full image is not stored."""
        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        non_jpeg = b"\x89PNG\r\n\x1a\nfakedata"
        baseline = make_thumbnail(id_signal="sig1", timestamp="2026-03-11 10:00:00")
        new_thumb = make_thumbnail(
            id_signal="sig2",
            image="base64data",
            timestamp="2026-03-11 10:01:00",
            signal_type="16",
        )
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
        )
        hub.session.get_photo_images = AsyncMock(return_value=non_jpeg)
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        _tasks = []
        hub.hass.async_create_task = lambda coro: _tasks.append(coro)

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)
            for task in _tasks:
                await task

        key = f"{installation.number}_{device.zone_id}"
        assert key not in hub._full_images
        signal_names = [c[1] for c in calls]
        assert SIGNAL_FULL_IMAGE_UPDATE not in signal_names

    async def test_full_image_not_stored_when_get_photo_images_returns_none(self):
        """When get_photo_images returns None, the full image is not stored."""
        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        baseline = make_thumbnail(id_signal="sig1", timestamp="2026-03-11 10:00:00")
        new_thumb = make_thumbnail(
            id_signal="sig2",
            image="base64data",
            timestamp="2026-03-11 10:01:00",
            signal_type="16",
        )
        hub.session.get_thumbnail = AsyncMock(side_effect=[baseline, new_thumb])
        hub.session.request_images = AsyncMock(return_value="ref-001")
        hub.session.check_request_images_status = AsyncMock(
            return_value={"res": "OK", "msg": "alarm-manager.photo-request.success"}
        )
        hub.session.get_photo_images = AsyncMock(return_value=None)
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        _tasks = []
        hub.hass.async_create_task = lambda coro: _tasks.append(coro)

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)
            for task in _tasks:
                await task

        key = f"{installation.number}_{device.zone_id}"
        assert key not in hub._full_images
        signal_names = [c[1] for c in calls]
        assert SIGNAL_FULL_IMAGE_UPDATE not in signal_names
