"""Tests for DataUpdateCoordinators — alarm, sentinel, lock, camera."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.securitas.coordinators import (
    AlarmCoordinator,
    AlarmStatusData,
    CameraCoordinator,
    CameraData,
    LockCoordinator,
    LockData,
    SentinelCoordinator,
    SentinelData,
)
from custom_components.securitas.api_queue import ApiQueue
from custom_components.securitas.securitas_direct_new_api.client import SecuritasClient
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
    SessionExpiredError,
    WAFBlockedError,
)
from custom_components.securitas.securitas_direct_new_api.models import (
    AirQuality,
    CameraDevice,
    Installation,
    Sentinel,
    Service,
    SmartLockMode,
    SStatus,
    ThumbnailResponse,
)

from .conftest import make_installation


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_hass() -> MagicMock:
    """Create a minimal mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    return hass


def _make_client() -> AsyncMock:
    """Create a mock SecuritasClient with async methods."""
    client = AsyncMock(spec=SecuritasClient)
    client.protom_response = ""
    return client


def _make_queue() -> AsyncMock:
    """Create a mock ApiQueue whose submit awaits the async function."""
    queue = AsyncMock(spec=ApiQueue)

    async def _submit(fn, *a, **kw):
        return await fn(*a)

    queue.submit = AsyncMock(side_effect=_submit)
    return queue


def _make_installation() -> Installation:
    return make_installation()


# ── AlarmCoordinator ─────────────────────────────────────────────────────────


class TestAlarmCoordinator:
    """Tests for AlarmCoordinator."""

    def _make_coordinator(
        self,
        hass: MagicMock,
        client: AsyncMock,
        queue: AsyncMock,
        installation: Installation,
    ) -> AlarmCoordinator:
        return AlarmCoordinator(
            hass,
            client,
            queue,
            installation,
            update_interval=timedelta(seconds=30),
        )

    @pytest.mark.asyncio
    async def test_successful_update(self):
        """Successful update returns AlarmStatusData with status and protom_response."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        status = SStatus(status="0", timestamp_update="2024-01-01", wifi_connected=True)
        client.get_general_status.return_value = status
        client.protom_response = "D"

        coord = self._make_coordinator(hass, client, queue, installation)
        result = await coord._async_update_data()

        assert isinstance(result, AlarmStatusData)
        assert result.status is status
        assert result.protom_response == "D"
        queue.submit.assert_called_once()

    @pytest.mark.asyncio
    async def test_waf_blocked_raises_update_failed(self):
        """WAFBlockedError raises UpdateFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        client.get_general_status.side_effect = WAFBlockedError("blocked")

        coord = self._make_coordinator(hass, client, queue, installation)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_session_expired_retries_login_then_auth_failed(self):
        """SessionExpiredError retries login; if login fails, raises ConfigEntryAuthFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        client.get_general_status.side_effect = SessionExpiredError("expired")
        client.login.side_effect = SecuritasDirectError("login failed")

        coord = self._make_coordinator(hass, client, queue, installation)
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

        client.login.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_expired_retry_succeeds(self):
        """SessionExpiredError retries login; if login succeeds, retries the API call."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        status = SStatus(status="0")
        client.get_general_status.side_effect = [
            SessionExpiredError("expired"),
            status,
        ]
        client.login.return_value = None
        client.protom_response = "T"

        coord = self._make_coordinator(hass, client, queue, installation)
        result = await coord._async_update_data()

        assert result.status is status
        assert result.protom_response == "T"
        client.login.assert_awaited_once()
        assert queue.submit.call_count == 2

    @pytest.mark.asyncio
    async def test_generic_error_raises_update_failed(self):
        """Generic SecuritasDirectError raises UpdateFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        client.get_general_status.side_effect = SecuritasDirectError("some error")

        coord = self._make_coordinator(hass, client, queue, installation)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ── SentinelCoordinator ──────────────────────────────────────────────────────


class TestSentinelCoordinator:
    """Tests for SentinelCoordinator."""

    def _make_coordinator(
        self,
        hass: MagicMock,
        client: AsyncMock,
        queue: AsyncMock,
        installation: Installation,
        service: Service | None = None,
        zone: str = "1",
    ) -> SentinelCoordinator:
        if service is None:
            service = Service(id=1, active=True)
        return SentinelCoordinator(
            hass,
            client,
            queue,
            installation,
            service=service,
            zone=zone,
        )

    @pytest.mark.asyncio
    async def test_successful_update_both(self):
        """Successful update with both sentinel and air quality data."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        sentinel = Sentinel(
            alias="Living Room", air_quality="good", humidity=50, temperature=22
        )
        air_quality = AirQuality(value=42, status_current=1)
        client.get_sentinel_data.return_value = sentinel
        client.get_air_quality_data.return_value = air_quality

        coord = self._make_coordinator(hass, client, queue, installation)
        result = await coord._async_update_data()

        assert isinstance(result, SentinelData)
        assert result.sentinel is sentinel
        assert result.air_quality is air_quality

    @pytest.mark.asyncio
    async def test_air_quality_none_is_ok(self):
        """Air quality returning None still gives valid SentinelData."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        sentinel = Sentinel(
            alias="Living Room", air_quality="good", humidity=50, temperature=22
        )
        client.get_sentinel_data.return_value = sentinel
        client.get_air_quality_data.return_value = None

        coord = self._make_coordinator(hass, client, queue, installation)
        result = await coord._async_update_data()

        assert result.sentinel is sentinel
        assert result.air_quality is None

    @pytest.mark.asyncio
    async def test_session_expired_retries(self):
        """SessionExpiredError retries login then retries the data fetch."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        sentinel = Sentinel(
            alias="Living Room", air_quality="good", humidity=50, temperature=22
        )
        client.get_sentinel_data.side_effect = [
            SessionExpiredError("expired"),
            sentinel,
        ]
        client.get_air_quality_data.return_value = None
        client.login.return_value = None

        coord = self._make_coordinator(hass, client, queue, installation)
        result = await coord._async_update_data()

        assert result.sentinel is sentinel
        client.login.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_waf_blocked_raises_update_failed(self):
        """WAFBlockedError raises UpdateFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        client.get_sentinel_data.side_effect = WAFBlockedError("blocked")

        coord = self._make_coordinator(hass, client, queue, installation)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_generic_error_raises_update_failed(self):
        """Generic SecuritasDirectError raises UpdateFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        client.get_sentinel_data.side_effect = SecuritasDirectError("error")

        coord = self._make_coordinator(hass, client, queue, installation)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ── LockCoordinator ──────────────────────────────────────────────────────────


class TestLockCoordinator:
    """Tests for LockCoordinator."""

    def _make_coordinator(
        self,
        hass: MagicMock,
        client: AsyncMock,
        queue: AsyncMock,
        installation: Installation,
    ) -> LockCoordinator:
        return LockCoordinator(
            hass,
            client,
            queue,
            installation,
            update_interval=timedelta(seconds=60),
        )

    @pytest.mark.asyncio
    async def test_successful_update(self):
        """Successful update returns LockData with modes list."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        modes = [
            SmartLockMode(lock_status="locked", device_id="lock1"),
            SmartLockMode(lock_status="unlocked", device_id="lock2"),
        ]
        client.get_lock_modes.return_value = modes

        coord = self._make_coordinator(hass, client, queue, installation)
        result = await coord._async_update_data()

        assert isinstance(result, LockData)
        assert result.modes == modes

    @pytest.mark.asyncio
    async def test_waf_blocked_raises_update_failed(self):
        """WAFBlockedError raises UpdateFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        client.get_lock_modes.side_effect = WAFBlockedError("blocked")

        coord = self._make_coordinator(hass, client, queue, installation)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_session_expired_retries_login_then_auth_failed(self):
        """SessionExpiredError retries login; login failure raises ConfigEntryAuthFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        client.get_lock_modes.side_effect = SessionExpiredError("expired")
        client.login.side_effect = SecuritasDirectError("login failed")

        coord = self._make_coordinator(hass, client, queue, installation)
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_generic_error_raises_update_failed(self):
        """Generic SecuritasDirectError raises UpdateFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()

        client.get_lock_modes.side_effect = SecuritasDirectError("error")

        coord = self._make_coordinator(hass, client, queue, installation)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ── CameraCoordinator ────────────────────────────────────────────────────────


class TestCameraCoordinator:
    """Tests for CameraCoordinator."""

    def _make_cameras(self, count: int = 2) -> list[CameraDevice]:
        return [
            CameraDevice(
                id=f"cam{i}",
                zone_id=f"zone{i}",
                device_type="QR",
                name=f"Camera {i}",
            )
            for i in range(count)
        ]

    def _make_coordinator(
        self,
        hass: MagicMock,
        client: AsyncMock,
        queue: AsyncMock,
        installation: Installation,
        cameras: list[CameraDevice] | None = None,
    ) -> CameraCoordinator:
        if cameras is None:
            cameras = self._make_cameras()
        return CameraCoordinator(
            hass,
            client,
            queue,
            installation,
            cameras=cameras,
        )

    @pytest.mark.asyncio
    async def test_successful_update(self):
        """Successful update returns CameraData with thumbnails."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()
        cameras = self._make_cameras(2)

        thumb0 = ThumbnailResponse(image="base64data0")
        thumb1 = ThumbnailResponse(image="base64data1")
        client.get_thumbnail.side_effect = [thumb0, thumb1]

        coord = self._make_coordinator(hass, client, queue, installation, cameras)
        result = await coord._async_update_data()

        assert isinstance(result, CameraData)
        assert result.thumbnails["zone0"] is thumb0
        assert result.thumbnails["zone1"] is thumb1
        assert result.full_images == {}

    @pytest.mark.asyncio
    async def test_single_camera_failure_doesnt_fail_update(self):
        """Single camera failure doesn't fail the whole update."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()
        cameras = self._make_cameras(2)

        thumb1 = ThumbnailResponse(image="base64data1")
        client.get_thumbnail.side_effect = [
            SecuritasDirectError("camera error"),
            thumb1,
        ]

        coord = self._make_coordinator(hass, client, queue, installation, cameras)
        result = await coord._async_update_data()

        # First camera failed, second succeeded
        assert "zone0" not in result.thumbnails
        assert result.thumbnails["zone1"] is thumb1

    @pytest.mark.asyncio
    async def test_previous_thumbnail_preserved_on_failure(self):
        """Previous thumbnail is preserved when a camera fails on refresh."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()
        cameras = self._make_cameras(2)

        thumb0 = ThumbnailResponse(image="base64data0")
        thumb1 = ThumbnailResponse(image="base64data1")
        client.get_thumbnail.side_effect = [thumb0, thumb1]

        coord = self._make_coordinator(hass, client, queue, installation, cameras)
        # First fetch — both succeed
        result1 = await coord._async_update_data()
        assert result1.thumbnails["zone0"] is thumb0

        # Store result as current data (simulating what HA does)
        coord.data = result1

        # Second fetch — first camera fails, second succeeds
        thumb1_new = ThumbnailResponse(image="base64data1_new")
        client.get_thumbnail.side_effect = [
            SecuritasDirectError("camera error"),
            thumb1_new,
        ]

        result2 = await coord._async_update_data()

        # First camera: previous thumbnail preserved
        assert result2.thumbnails["zone0"] is thumb0
        # Second camera: updated
        assert result2.thumbnails["zone1"] is thumb1_new

    @pytest.mark.asyncio
    async def test_full_images_preserved_across_refreshes(self):
        """Full images from previous data are preserved across refreshes."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()
        cameras = self._make_cameras(1)

        thumb = ThumbnailResponse(image="base64data")
        client.get_thumbnail.return_value = thumb

        coord = self._make_coordinator(hass, client, queue, installation, cameras)
        result1 = await coord._async_update_data()

        # Simulate that full_images was populated externally
        result1.full_images["zone0"] = b"full-image-bytes"
        coord.data = result1

        # Next refresh
        thumb_new = ThumbnailResponse(image="base64data_new")
        client.get_thumbnail.return_value = thumb_new

        result2 = await coord._async_update_data()
        assert result2.full_images["zone0"] == b"full-image-bytes"
        assert result2.thumbnails["zone0"] is thumb_new

    @pytest.mark.asyncio
    async def test_session_expired_retries(self):
        """SessionExpiredError retries login then retries."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()
        cameras = self._make_cameras(1)

        thumb = ThumbnailResponse(image="data")
        # First call to get_thumbnail raises SessionExpiredError
        # The whole _async_update_data is retried after login
        client.get_thumbnail.side_effect = [
            SessionExpiredError("expired"),
            thumb,
        ]
        client.login.return_value = None

        coord = self._make_coordinator(hass, client, queue, installation, cameras)
        result = await coord._async_update_data()

        assert result.thumbnails["zone0"] is thumb
        client.login.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_waf_blocked_raises_update_failed(self):
        """WAFBlockedError raises UpdateFailed."""
        hass = _make_hass()
        client = _make_client()
        queue = _make_queue()
        installation = _make_installation()
        cameras = self._make_cameras(1)

        client.get_thumbnail.side_effect = WAFBlockedError("blocked")

        coord = self._make_coordinator(hass, client, queue, installation, cameras)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
