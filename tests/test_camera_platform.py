"""Tests for camera platform entities."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    CameraDevice,
)
from custom_components.securitas.securitas_direct_new_api import Installation
from custom_components.securitas import DOMAIN
from custom_components.securitas.entity import camera_device_info


class TestCameraDeviceInfo:
    def test_identifiers_include_zone_id(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info[
            "identifiers"
        ]

    def test_name_is_camera_device_name(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["name"] == "Salon"

    def test_manufacturer(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["manufacturer"] == "Securitas Direct"

    def test_model(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["model"] == "Camera"

    def test_via_device_points_to_installation(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["via_device"] == (DOMAIN, "v4_securitas_direct.2654190")


@pytest.fixture
def installation():
    return Installation(number="2654190", panel="SDVECU", alias="Casa")


@pytest.fixture
def camera_device():
    return CameraDevice(
        id="11",
        code=10,
        zone_id="QR10",
        name="Salon",
        device_type="QR",
        serial_number="36NEYYER",
    )


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.camera_images = {}
    hub.get_camera_image = MagicMock(return_value=None)
    hub.fetch_latest_thumbnail = AsyncMock()
    return hub


class TestSecuritasCamera:
    def test_unique_id(self, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        assert cam.unique_id == "v4_2654190_camera_QR10"

    def test_has_entity_name(self, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        assert cam._attr_has_entity_name is True

    def test_no_entity_name_suffix(self, mock_hub, installation, camera_device):
        """Camera is the primary entity of its device — no name suffix is set."""
        from homeassistant.helpers.entity import UNDEFINED
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        assert cam.name is UNDEFINED

    def test_should_not_poll(self, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        assert cam.should_poll is False

    @pytest.mark.asyncio
    async def test_camera_image_returns_stored_bytes(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        image_bytes = b"\xff\xd8\xff\xe0fake_jpeg"
        mock_hub.get_camera_image.return_value = image_bytes
        cam = SecuritasCamera(mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == image_bytes
        mock_hub.get_camera_image.assert_called_once_with("2654190", "QR10")

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_empty(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import (
            SecuritasCamera,
            _PLACEHOLDER_IMAGE,
        )

        mock_hub.get_camera_image.return_value = None
        cam = SecuritasCamera(mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == _PLACEHOLDER_IMAGE

    @pytest.mark.asyncio
    async def test_camera_image_calls_fetch_on_first_call(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        mock_hub.get_camera_image.return_value = b"\xff\xd8"
        cam = SecuritasCamera(mock_hub, installation, camera_device)
        assert cam._initial_fetch_done is False

        await cam.async_camera_image()

        mock_hub.fetch_latest_thumbnail.assert_awaited_once_with(
            installation, camera_device
        )
        assert cam._initial_fetch_done is True

    @pytest.mark.asyncio
    async def test_camera_image_skips_fetch_on_subsequent_calls(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        mock_hub.get_camera_image.return_value = b"\xff\xd8"
        cam = SecuritasCamera(mock_hub, installation, camera_device)

        # First call — triggers the lazy fetch
        await cam.async_camera_image()
        assert mock_hub.fetch_latest_thumbnail.await_count == 1

        # Second call — must NOT trigger fetch again
        await cam.async_camera_image()
        assert mock_hub.fetch_latest_thumbnail.await_count == 1

    def test_device_info_uses_camera_sub_device(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera
        from custom_components.securitas import DOMAIN

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        info = cam.device_info
        assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info[
            "identifiers"
        ]
        assert info.get("via_device") == (DOMAIN, "v4_securitas_direct.2654190")

    @pytest.mark.asyncio
    async def test_async_added_to_hass_registers_interval(
        self, mock_hub, installation, camera_device
    ):
        from unittest.mock import MagicMock, patch
        from custom_components.securitas.camera import SecuritasCamera, SCAN_INTERVAL

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        mock_hass = MagicMock()
        mock_hass.async_create_task = MagicMock()
        cam.hass = mock_hass

        unsubscribe = MagicMock()
        with patch(
            "custom_components.securitas.camera.async_track_time_interval",
            return_value=unsubscribe,
        ) as mock_track:
            with patch(
                "custom_components.securitas.camera.async_dispatcher_connect",
                return_value=MagicMock(),
            ):
                await cam.async_added_to_hass()

        mock_track.assert_called_once()
        args = mock_track.call_args
        assert args[0][0] is mock_hass  # hass
        assert args[0][2] == SCAN_INTERVAL  # interval

        # Invoke the callback and confirm it calls fetch_latest_thumbnail
        callback_fn = args[0][1]
        from datetime import datetime

        await callback_fn(datetime.now())
        mock_hub.fetch_latest_thumbnail.assert_called_once_with(
            installation, camera_device
        )


class TestSecuritasCaptureButton:
    def test_unique_id(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton

        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        assert btn.unique_id == "v4_2654190_capture_QR10"

    def test_has_entity_name(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton

        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        assert btn._attr_has_entity_name is True

    def test_name_is_capture(self, mock_hub, installation, camera_device):
        """Button name is the entity-specific suffix; device name is prepended by HA."""
        from custom_components.securitas.button import SecuritasCaptureButton

        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        assert btn.name == "Capture"

    def test_icon(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton

        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        assert btn.icon == "mdi:camera"

    @pytest.mark.asyncio
    async def test_press_calls_capture(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton

        mock_hub.capture_image = AsyncMock(return_value=b"\xff\xd8")
        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        await btn.async_press()
        mock_hub.capture_image.assert_called_once_with(installation, camera_device)

    @pytest.mark.asyncio
    async def test_press_handles_error(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton
        from custom_components.securitas.securitas_direct_new_api.exceptions import (
            SecuritasDirectError,
        )

        mock_hub.capture_image = AsyncMock(side_effect=SecuritasDirectError("fail"))
        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        # Should not raise
        await btn.async_press()

    def test_device_info_uses_camera_sub_device(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.button import SecuritasCaptureButton
        from custom_components.securitas import DOMAIN

        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        info = btn.device_info
        assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info[
            "identifiers"
        ]
        assert info.get("via_device") == (DOMAIN, "v4_securitas_direct.2654190")


@pytest.fixture
def mock_hub_full():
    hub = MagicMock()
    hub.get_full_image = MagicMock(return_value=None)
    hub.get_full_timestamp = MagicMock(return_value=None)
    return hub


class TestSecuritasCameraFull:
    """Tests for the SecuritasCameraFull entity."""

    def test_unique_id(self, mock_hub_full, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        assert cam.unique_id == "v4_2654190_camera_full_QR10"

    def test_has_entity_name(self, mock_hub_full, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        assert cam._attr_has_entity_name is True

    def test_name_is_full_image(self, mock_hub_full, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        assert cam.name == "Full Image"

    def test_should_not_poll(self, mock_hub_full, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        assert cam.should_poll is False

    @pytest.mark.asyncio
    async def test_camera_image_returns_stored_bytes(
        self, mock_hub_full, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCameraFull

        image_bytes = b"\xff\xd8\xff\xe0full_jpeg"
        mock_hub_full.get_full_image.return_value = image_bytes
        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == image_bytes
        mock_hub_full.get_full_image.assert_called_once_with("2654190", "QR10")

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_empty(
        self, mock_hub_full, installation, camera_device
    ):
        from custom_components.securitas.camera import (
            SecuritasCameraFull,
            _PLACEHOLDER_IMAGE,
        )

        mock_hub_full.get_full_image.return_value = None
        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == _PLACEHOLDER_IMAGE

    def test_device_info_matches_thumbnail_entity(
        self, mock_hub_full, installation, camera_device
    ):
        """Both camera entities must share the same HA device (same identifiers)."""
        from custom_components.securitas.camera import (
            SecuritasCamera,
            SecuritasCameraFull,
        )
        from custom_components.securitas import DOMAIN

        thumb_cam = SecuritasCamera(MagicMock(), installation, camera_device)
        full_cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)

        assert (
            thumb_cam.device_info["identifiers"] == full_cam.device_info["identifiers"]
        )
        assert (
            DOMAIN,
            "v4_securitas_direct.2654190_camera_QR10",
        ) in full_cam.device_info["identifiers"]

    @pytest.mark.asyncio
    async def test_async_added_to_hass_subscribes_to_signal(
        self, mock_hub_full, installation, camera_device
    ):
        from unittest.mock import patch, MagicMock
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        cam.hass = MagicMock()

        connected_signal = {}

        def _capture_connect(hass, signal, callback):
            connected_signal[signal] = callback
            return MagicMock()

        with patch(
            "custom_components.securitas.camera.async_dispatcher_connect",
            side_effect=_capture_connect,
        ):
            await cam.async_added_to_hass()

        from custom_components.securitas.const import SIGNAL_FULL_IMAGE_UPDATE

        assert SIGNAL_FULL_IMAGE_UPDATE in connected_signal

    @pytest.mark.asyncio
    async def test_token_rotates_on_signal(
        self, mock_hub_full, installation, camera_device
    ):
        """When SIGNAL_FULL_IMAGE_UPDATE fires for this entity, the token rotates."""
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        cam.async_update_token = MagicMock()
        cam.async_write_ha_state = MagicMock()

        # Signal for this camera
        cam._handle_full_update("2654190", "QR10")
        cam.async_update_token.assert_called_once()
        cam.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_does_not_rotate_for_other_camera(
        self, mock_hub_full, installation, camera_device
    ):
        """Signal for a different zone_id must not affect this entity."""
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(mock_hub_full, installation, camera_device)
        cam.async_update_token = MagicMock()
        cam.async_write_ha_state = MagicMock()

        # Signal for a different camera
        cam._handle_full_update("2654190", "QR11")
        cam.async_update_token.assert_not_called()
        cam.async_write_ha_state.assert_not_called()
