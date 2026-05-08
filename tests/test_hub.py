"""Tests for VerisureHub orchestration methods."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import CONF_PASSWORD

from custom_components.verisure_owa.api_queue import ApiQueue
from custom_components.verisure_owa.const import (
    API_CACHE_TTL,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    SIGNAL_CAMERA_STATE,
)
from custom_components.verisure_owa.hub import VerisureHub
from custom_components.verisure_owa.verisure_owa_api import (
    AuthenticationError,
    VerisureOwaError,
)
from custom_components.verisure_owa.verisure_owa_api.models import (
    CameraDevice,
    ThumbnailResponse,
)

from .conftest import make_installation


def make_hub(*, mock_client: bool = True, **config_overrides) -> VerisureHub:
    """Create a VerisureHub with a real ApiQueue and (by default) a mocked client.

    Set mock_client=False to keep the real VerisureOwaClient — useful when the
    test is exercising the constructor's client-wiring contract directly.
    """
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
        **config_overrides,
    }
    hub = VerisureHub(config, config_entry=None, http_client=MagicMock(), hass=hass)
    hub._api_queue = ApiQueue(interval=0)
    if mock_client:
        hub.client = MagicMock()
        hub.client.poll_delay = 0.01
    return hub


# ── Construction tests ──────────────────────────────────────────────────────


class TestConstruction:
    """Tests for VerisureHub.__init__."""

    def test_refresh_token_from_config_prefills_client(self):
        """A persisted refresh token in domain_config flows into the real client."""
        hub = make_hub(
            mock_client=False, **{CONF_REFRESH_TOKEN: "persisted-refresh-token"}
        )
        assert hub.client.refresh_token_value == "persisted-refresh-token"

    def test_get_refresh_token_returns_clients_refresh_token_value(self):
        """The hub-level getter mirrors get_authentication_token."""
        hub = make_hub()
        hub.client.refresh_token_value = "current-refresh-token"
        assert hub.get_refresh_token() == "current-refresh-token"


class TestRefreshTokenPersistence:
    """Tests that rotated refresh tokens get written to entry.data."""

    @staticmethod
    def _hub_with_entry(entry_data: dict) -> tuple[VerisureHub, MagicMock]:
        hass = MagicMock()
        hass.data = {}
        config_entry = MagicMock()
        config_entry.data = entry_data
        hub = make_hub()
        hub.config_entry = config_entry
        hub.hass = hass
        return hub, config_entry

    def test_persists_rotated_token_to_entry_data(self):
        """A token rotation must propagate into entry.data via async_update_entry."""
        hub, config_entry = self._hub_with_entry(
            {"username": "test@example.com", CONF_REFRESH_TOKEN: "old-token"}
        )

        hub._persist_refresh_token("rotated-token")

        hub.hass.config_entries.async_update_entry.assert_called_once()
        call = hub.hass.config_entries.async_update_entry.call_args
        assert call.args[0] is config_entry
        assert call.kwargs["data"][CONF_REFRESH_TOKEN] == "rotated-token"

    def test_strips_legacy_password_on_first_capture(self):
        """First refresh-token capture on a legacy entry must drop CONF_PASSWORD.

        Pre-migration users have password-shape entries on disk. Capturing a
        refresh token on the first post-upgrade setup is the natural moment
        to scrub the password from persisted data.
        """
        hub, _ = self._hub_with_entry(
            {"username": "test@example.com", CONF_PASSWORD: "legacy-password"}
        )

        hub._persist_refresh_token("first-refresh-token")

        new_data = hub.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert new_data[CONF_REFRESH_TOKEN] == "first-refresh-token"
        assert CONF_PASSWORD not in new_data

    def test_skips_write_when_token_unchanged_and_no_password(self):
        """No-op rotations must not trigger redundant entry-store writes."""
        hub, _ = self._hub_with_entry(
            {"username": "test@example.com", CONF_REFRESH_TOKEN: "same-token"}
        )

        hub._persist_refresh_token("same-token")

        hub.hass.config_entries.async_update_entry.assert_not_called()

    def test_writes_when_token_unchanged_but_legacy_password_present(self):
        """Same-token rotation must still scrub a lingering CONF_PASSWORD."""
        hub, _ = self._hub_with_entry(
            {
                "username": "test@example.com",
                CONF_REFRESH_TOKEN: "same-token",
                CONF_PASSWORD: "legacy-password",
            }
        )

        hub._persist_refresh_token("same-token")

        new_data = hub.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        assert CONF_PASSWORD not in new_data
        assert new_data[CONF_REFRESH_TOKEN] == "same-token"

    def test_no_config_entry_skips_persistence(self):
        """Without a config entry (config-flow path), rotation must not crash."""
        hub = make_hub()  # config_entry=None
        hub._persist_refresh_token("anything")
        hub.hass.config_entries.async_update_entry.assert_not_called()


class TestLogin:
    """Tests for hub.login()."""

    async def test_uses_refresh_when_token_present(self):
        """With a refresh token in hand, hub.login() must NOT do a password login.

        On reload of a refresh-token-shape entry the password is gone; calling
        client.login() would send an empty password to Verisure.
        """
        hub = make_hub()
        hub.client.refresh_token_value = "persisted-refresh-token"
        hub.client.refresh_token = AsyncMock(return_value=True)
        hub.client.login = AsyncMock()

        await hub.login()

        hub.client.refresh_token.assert_awaited_once()
        hub.client.login.assert_not_awaited()

    async def test_falls_back_to_login_without_refresh_token(self):
        """No refresh token → fresh password login (the original code path)."""
        hub = make_hub()
        hub.client.refresh_token_value = ""
        hub.client.refresh_token = AsyncMock()
        hub.client.login = AsyncMock()

        await hub.login()

        hub.client.login.assert_awaited_once()
        hub.client.refresh_token.assert_not_awaited()

    async def test_refresh_failure_with_no_password_raises_auth_error(self):
        """Refresh token rejected and no password to fall back on → AuthenticationError.

        This is the trigger for HA's reauth flow on long-idle installs whose
        180-day refresh token has finally expired or been server-revoked.
        Sending an empty password to the API would just waste a round trip.
        """
        hub = make_hub()
        hub.client.refresh_token_value = "expired-refresh-token"
        hub.client.password = ""
        hub.client.refresh_token = AsyncMock(return_value=False)
        hub.client.login = AsyncMock()

        with pytest.raises(AuthenticationError):
            await hub.login()

        hub.client.login.assert_not_awaited()


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
        """VerisureOwaError from client propagates to caller."""
        hub = make_hub()
        installation = make_installation()
        hub.client.change_lock_mode = AsyncMock(
            side_effect=VerisureOwaError("lock error")
        )

        with pytest.raises(VerisureOwaError, match="lock error"):
            await hub.change_lock_mode(installation, False, "device-1")


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
        """VerisureOwaError is caught and returns an empty list."""
        hub = make_hub()
        installation = make_installation()
        hub.client.get_lock_modes = AsyncMock(
            side_effect=VerisureOwaError("API failure", http_status=500)
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

        with patch("custom_components.verisure_owa.hub.async_dispatcher_send"):
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
            "custom_components.verisure_owa.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)

        # First dispatch must be SIGNAL_CAMERA_STATE
        assert calls[0][1] == SIGNAL_CAMERA_STATE

    async def test_coordinator_updated_on_successful_capture(self):
        """Camera coordinator is updated when a new image is captured."""
        from custom_components.verisure_owa.coordinators import CameraData

        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        _setup_capture(hub)

        # Set up a mock config entry with entry_id
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry"
        hub.config_entry = mock_entry

        # Set up a mock camera coordinator in entry_data
        mock_coord = MagicMock()
        mock_coord.data = CameraData(thumbnails={}, full_images={})
        mock_coord.async_set_updated_data = MagicMock()
        hub.hass.data = {DOMAIN: {"test_entry": {"camera_coordinator": mock_coord}}}

        with patch(
            "custom_components.verisure_owa.hub.async_dispatcher_send",
        ):
            await hub.capture_image(installation, device)

        mock_coord.async_set_updated_data.assert_called_once()
        new_data = mock_coord.async_set_updated_data.call_args[0][0]
        assert device.zone_id in new_data.thumbnails

    async def test_camera_state_signal_dispatched_when_no_image(self):
        """SIGNAL_CAMERA_STATE is dispatched when no image arrives."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        _setup_capture(hub)
        # Simulate validate returning None (no valid JPEG)
        hub._validate_and_store_image = MagicMock(return_value=None)

        calls = []
        with patch(
            "custom_components.verisure_owa.hub.async_dispatcher_send",
            side_effect=lambda *a: calls.append(a),
        ):
            await hub.capture_image(installation, device)

        # All dispatched signals should be SIGNAL_CAMERA_STATE
        signal_names = [c[1] for c in calls]
        assert all(s == SIGNAL_CAMERA_STATE for s in signal_names)
        # Last signal should be SIGNAL_CAMERA_STATE to clear the spinner
        assert calls[-1][1] == SIGNAL_CAMERA_STATE

    async def test_delegates_to_client_capture_image(self):
        """Hub passes correct arguments to client.capture_image."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        _setup_capture(hub)

        with patch("custom_components.verisure_owa.hub.async_dispatcher_send"):
            await hub.capture_image(installation, device)

        hub.client.capture_image.assert_awaited_once_with(
            installation,
            device.code,
            device.device_type,
            device.zone_id,
        )

    async def test_capturing_flag_cleared_on_error(self):
        """The capturing flag is cleared even when the client raises."""
        hub = make_hub()
        installation = make_installation()
        device = make_camera_device()
        hub.client.capture_image = AsyncMock(
            side_effect=VerisureOwaError("capture error")
        )

        with (
            patch("custom_components.verisure_owa.hub.async_dispatcher_send"),
            pytest.raises(VerisureOwaError),
        ):
            await hub.capture_image(installation, device)

        # Flag is cleared in finally block even on error
        assert not hub.is_capturing(installation.number, device.zone_id)


class TestFullImageCapture:
    """Tests for full-resolution image fetching and storage in the hub."""

    async def test_fetch_full_image_coalesces_concurrent_requests(self):
        """Two concurrent fetch_full_image calls for the same signal share one API call."""
        hub = make_hub()
        installation = make_installation()

        api_call_count = 0
        api_can_finish = asyncio.Event()

        async def slow_get_full_image(*_args, **_kwargs):
            nonlocal api_call_count
            api_call_count += 1
            await api_can_finish.wait()
            return b"\xff\xd8full-bytes"

        hub.client.get_full_image = AsyncMock(side_effect=slow_get_full_image)

        task1 = asyncio.create_task(hub.fetch_full_image(installation, "sig-A", "16"))
        task2 = asyncio.create_task(hub.fetch_full_image(installation, "sig-A", "16"))

        # Yield until both tasks have entered fetch_full_image and the first
        # has reached the slow API call.
        for _ in range(10):
            await asyncio.sleep(0)
            if api_call_count >= 1:
                break

        api_can_finish.set()
        r1, r2 = await asyncio.gather(task1, task2)

        assert r1 == b"\xff\xd8full-bytes"
        assert r2 == b"\xff\xd8full-bytes"
        assert api_call_count == 1

    async def test_capture_updates_coordinator_full_image(self):
        """Camera coordinator is updated with full image after capture."""
        from custom_components.verisure_owa.coordinators import CameraData

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

        # Set up mock coordinator
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry"
        hub.config_entry = mock_entry

        mock_coord = MagicMock()
        mock_coord.data = CameraData(thumbnails={}, full_images={})
        mock_coord.async_set_updated_data = MagicMock()
        hub.hass.data = {DOMAIN: {"test_entry": {"camera_coordinator": mock_coord}}}

        _tasks = []
        hub.hass.async_create_task = lambda coro: _tasks.append(coro)

        with patch(
            "custom_components.verisure_owa.hub.async_dispatcher_send",
        ):
            await hub.capture_image(installation, device)
            for task in _tasks:
                await task

        # Coordinator should have been updated twice: once for thumbnail, once for full image
        assert mock_coord.async_set_updated_data.call_count == 2
        # Last call should contain the full image
        last_data = mock_coord.async_set_updated_data.call_args_list[-1][0][0]
        assert device.zone_id in last_data.full_images
        assert last_data.full_images[device.zone_id] == full_jpeg

    async def test_capture_skips_full_image_when_id_signal_is_none(self):
        """PIR cameras (idSignal=None) do not trigger a get_full_image call."""
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

        with patch(
            "custom_components.verisure_owa.hub.async_dispatcher_send",
        ):
            await hub.capture_image(installation, device)

        hub.client.get_full_image.assert_not_called()

    async def test_full_image_not_stored_when_not_jpeg(self):
        """When get_full_image returns non-JPEG bytes, the coordinator is not updated."""
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
        hub._update_camera_coordinator_full_image = MagicMock()

        _tasks = []
        hub.hass.async_create_task = lambda coro: _tasks.append(coro)

        with patch(
            "custom_components.verisure_owa.hub.async_dispatcher_send",
        ):
            await hub.capture_image(installation, device)
            for task in _tasks:
                await task

        hub._update_camera_coordinator_full_image.assert_not_called()

    async def test_full_image_not_stored_when_get_full_image_returns_none(self):
        """When get_full_image returns None, the coordinator is not updated."""
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
        hub._update_camera_coordinator_full_image = MagicMock()

        _tasks = []
        hub.hass.async_create_task = lambda coro: _tasks.append(coro)

        with patch(
            "custom_components.verisure_owa.hub.async_dispatcher_send",
        ):
            await hub.capture_image(installation, device)
            for task in _tasks:
                await task

        hub._update_camera_coordinator_full_image.assert_not_called()


class TestGetServicesPartitionsCache:
    """get_services must preserve the alarm_partitions side-effect across
    cache hits — Italian SDVECU peri detection reads it.
    """

    async def test_get_services_restores_partitions_on_cache_hit(self):
        """Second call with a fresh Installation must end up with partitions
        populated, even though the cache hit short-circuits the network call.
        """
        hub = make_hub()
        partitions = [{"id": "02", "enterStates": ["01"], "leaveStates": ["01"]}]

        async def fake_client_get_services(install):
            install.alarm_partitions = partitions
            return ["service-list-marker"]

        hub.client.get_services = AsyncMock(side_effect=fake_client_get_services)

        # First call populates the cache and the passed installation.
        first = make_installation(number="2654190")
        services = await hub.get_services(first)
        assert services == ["service-list-marker"]
        assert first.alarm_partitions == partitions

        # Second call with a NEW Installation instance — alarm_partitions
        # starts empty.  Cache hit must still surface the partitions.
        second = make_installation(number="2654190")
        assert second.alarm_partitions == []  # fresh default
        services = await hub.get_services(second)
        assert services == ["service-list-marker"]
        assert second.alarm_partitions == partitions
        # Underlying client.get_services must NOT have been called again.
        assert hub.client.get_services.await_count == 1
