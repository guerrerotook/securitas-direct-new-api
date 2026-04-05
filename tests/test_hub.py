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
    """Create a SecuritasHub with a real ApiQueue and mocked client."""
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
    hub.client = MagicMock()
    hub.client.poll_delay = 0.01
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

        # Expire the cache
        hub._api_cache_time["key1"] = time.monotonic() - API_CACHE_TTL - 1

        result = await hub._cached_api_call("key1", api_fn, "arg1")

        assert result == "result_b"
        api_fn.assert_awaited_once()

    async def test_none_result_not_cached(self):
        """None results should not be cached."""
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
    """Tests for change_lock_mode.

    The hub delegates to client.change_lock_mode which handles all
    submit/check/poll internally. Hub tests verify delegation and cache
    invalidation.
    """

    async def test_delegates_to_client(self):
        """Hub calls client.change_lock_mode via the queue."""
        hub = make_hub()
        installation = make_installation()
        hub.client.change_lock_mode = AsyncMock()

        await hub.change_lock_mode(installation, True, "device-1")

        hub.client.change_lock_mode.assert_awaited_once_with(
            installation, True, "device-1"
        )

    async def test_cache_invalidated_after_change(self):
        """Lock modes cache is invalidated after a change."""
        hub = make_hub()
        installation = make_installation()
        hub._lock_modes_time[installation.number] = 12345.0
        hub._lock_modes[installation.number] = ["stale"]
        hub.client.change_lock_mode = AsyncMock()

        await hub.change_lock_mode(installation, True, "device-1")

        assert installation.number not in hub._lock_modes_time

    async def test_error_propagates(self):
        """SecuritasDirectError from client propagates to caller."""
        hub = make_hub()
        installation = make_installation()
        hub.client.change_lock_mode = AsyncMock(
            side_effect=SecuritasDirectError("lock error")
        )

        with pytest.raises(SecuritasDirectError, match="lock error"):
            await hub.change_lock_mode(installation, False, "device-1")


# ── refresh_alarm_status tests ──────────────────────────────────────────────


class TestRefreshAlarmStatus:
    """Tests for refresh_alarm_status.

    The hub delegates to client.check_alarm which handles all polling
    internally and returns OperationStatus.
    """

    async def test_returns_operation_status(self):
        """Returns the OperationStatus from client.check_alarm."""
        hub = make_hub()
        installation = make_installation()
        status = OperationStatus(protom_response="ARM1")
        hub.client.check_alarm = AsyncMock(return_value=status)

        result = await hub.refresh_alarm_status(installation)

        assert result is status
        assert result.protom_response == "ARM1"
        hub.client.check_alarm.assert_awaited_once_with(installation)

    async def test_error_propagates(self):
        """SecuritasDirectError from client propagates."""
        hub = make_hub()
        installation = make_installation()
        hub.client.check_alarm = AsyncMock(side_effect=SecuritasDirectError("timeout"))

        with pytest.raises(SecuritasDirectError, match="timeout"):
            await hub.refresh_alarm_status(installation)


# ── get_lock_modes tests ────────────────────────────────────────────────────


class TestGetLockModes:
    """Tests for get_lock_modes with TTL cache."""

    async def test_cache_miss_calls_api(self):
        """First call fetches from API and caches the result."""
        hub = make_hub()
        installation = make_installation()
        modes = [{"id": "lock-1", "mode": "locked"}]
        hub.client.get_lock_modes = AsyncMock(return_value=modes)

        result = await hub.get_lock_modes(installation)

        assert result == modes
        hub.client.get_lock_modes.assert_awaited_once_with(installation)
        assert hub._lock_modes[installation.number] == modes

    async def test_cache_hit_skips_api(self):
        """Second call within TTL returns cached value."""
        hub = make_hub()
        installation = make_installation()
        modes = [{"id": "lock-1", "mode": "locked"}]
        hub.client.get_lock_modes = AsyncMock(return_value=modes)

        await hub.get_lock_modes(installation)
        hub.client.get_lock_modes.reset_mock()

        result = await hub.get_lock_modes(installation)

        assert result == modes
        hub.client.get_lock_modes.assert_not_awaited()

    async def test_cache_expired_calls_api_again(self):
        """After TTL expires, API is called again."""
        hub = make_hub()
        installation = make_installation()
        hub.client.get_lock_modes = AsyncMock(return_value=["old"])

        await hub.get_lock_modes(installation)
        hub.client.get_lock_modes.reset_mock()
        hub.client.get_lock_modes.return_value = ["new"]

        hub._lock_modes_time[installation.number] = time.monotonic() - API_CACHE_TTL - 1

        result = await hub.get_lock_modes(installation)

        assert result == ["new"]
        hub.client.get_lock_modes.assert_awaited_once()

    async def test_securitas_error_returns_empty_list(self):
        """SecuritasDirectError is caught and returns an empty list."""
        hub = make_hub()
        installation = make_installation()
        hub.client.get_lock_modes = AsyncMock(
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


def _setup_capture(hub, *, new_image=b"\xff\xd8"):
    """Wire client mocks for a standard successful capture."""
    new_thumb = make_thumbnail(
        id_signal="sig2", image="base64data", timestamp="2026-03-11 10:01:00"
    )
    hub.client.capture_image = AsyncMock(return_value=new_thumb)
    hub._validate_and_store_image = MagicMock(return_value=new_image)
    return new_thumb


class TestCaptureImage:
    """Tests for capture_image hub method.

    The client handles all capture polling internally. The hub's job is:
    - Set/clear the capturing flag
    - Dispatch signals
    - Validate and store the image
    - Trigger full image fetch
    """

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

    async def test_delegates_to_client_capture_image(self):
        """Hub passes correct arguments to client.capture_image."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        _setup_capture(hub)

        with patch("custom_components.securitas.hub.async_dispatcher_send"):
            await hub.capture_image(installation, device)

        hub.client.capture_image.assert_awaited_once_with(
            installation,
            device.code,
            device.device_type,
            device.zone_id,
        )

    async def test_capturing_flag_set_during_error(self):
        """The capturing flag stays set when the client raises (no try/finally)."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        hub.client.capture_image = AsyncMock(
            side_effect=SecuritasDirectError("capture error")
        )

        with (
            patch("custom_components.securitas.hub.async_dispatcher_send"),
            pytest.raises(SecuritasDirectError),
        ):
            await hub.capture_image(installation, device)

        # Flag stays set because queue.submit raises before cleanup
        assert hub.is_capturing(installation.number, device.zone_id)


class TestFullImageCapture:
    """Tests for full-resolution image fetching and storage in the hub."""

    async def test_capture_stores_full_image(self):
        """After a successful capture, the full image is stored in _full_images."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        full_jpeg = b"\xff\xd8\xff\xe0full"
        new_thumb = make_thumbnail(
            id_signal="sig2",
            image="base64data",
            timestamp="2026-03-11 10:01:00",
            signal_type="16",
        )
        hub.client.capture_image = AsyncMock(return_value=new_thumb)
        hub.client.get_full_image = AsyncMock(return_value=full_jpeg)
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
        new_thumb = make_thumbnail(
            id_signal="sig2",
            image="base64data",
            timestamp="2026-03-11 10:01:00",
            signal_type="16",
        )
        hub.client.capture_image = AsyncMock(return_value=new_thumb)
        hub.client.get_full_image = AsyncMock(return_value=full_jpeg)
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
        """PIR cameras (idSignal=None) do not trigger a get_full_image call."""
        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        new_thumb = make_thumbnail(
            id_signal=None,
            image="newbase64",
            timestamp="2026-03-11 10:01:00",
        )
        hub.client.capture_image = AsyncMock(return_value=new_thumb)
        hub.client.get_full_image = AsyncMock()
        hub._validate_and_store_image = MagicMock(return_value=b"\xff\xd8")

        calls = []
        with patch(
            "custom_components.securitas.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)

        hub.client.get_full_image.assert_not_called()
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
        hub.client.get_thumbnail = AsyncMock(return_value=thumb)
        hub.client.get_full_image = AsyncMock(return_value=full_jpeg)
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
        """When get_full_image returns non-JPEG bytes, the full image is not stored."""
        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        non_jpeg = b"\x89PNG\r\n\x1a\nfakedata"
        new_thumb = make_thumbnail(
            id_signal="sig2",
            image="base64data",
            timestamp="2026-03-11 10:01:00",
            signal_type="16",
        )
        hub.client.capture_image = AsyncMock(return_value=new_thumb)
        hub.client.get_full_image = AsyncMock(return_value=non_jpeg)
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

    async def test_full_image_not_stored_when_get_full_image_returns_none(self):
        """When get_full_image returns None, the full image is not stored."""
        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()

        new_thumb = make_thumbnail(
            id_signal="sig2",
            image="base64data",
            timestamp="2026-03-11 10:01:00",
            signal_type="16",
        )
        hub.client.capture_image = AsyncMock(return_value=new_thumb)
        hub.client.get_full_image = AsyncMock(return_value=None)
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
