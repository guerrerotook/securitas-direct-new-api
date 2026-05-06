"""Tests for camera platform entities."""

import base64

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.securitas.securitas_direct_new_api.models import (
    CameraDevice,
    ThumbnailResponse,
)
from custom_components.securitas.securitas_direct_new_api import Installation
from custom_components.securitas import DOMAIN
from custom_components.securitas.coordinators import CameraCoordinator, CameraData
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
    hub.is_capturing = MagicMock(return_value=False)
    hub.fetch_latest_thumbnail = AsyncMock()
    return hub


@pytest.fixture
def mock_coordinator():
    """Create a mock CameraCoordinator with sensible defaults."""
    coord = MagicMock(spec=CameraCoordinator)
    coord.data = CameraData(thumbnails={}, full_images={})
    # CoordinatorEntity expects these
    coord.async_request_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=MagicMock())
    return coord


@pytest.fixture
def jpeg_thumbnail():
    """Return a ThumbnailResponse with valid JPEG base64 data."""
    jpeg_bytes = b"\xff\xd8\xff\xe0fake_jpeg"
    return ThumbnailResponse(
        image=base64.b64encode(jpeg_bytes).decode(),
        timestamp="2026-03-09T12:00:00Z",
    )


class TestSecuritasCamera:
    def test_unique_id(self, mock_coordinator, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert cam.unique_id == "v4_2654190_camera_QR10"

    def test_has_entity_name(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert cam._attr_has_entity_name is True

    def test_no_entity_name_suffix(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """Camera is the primary entity of its device -- no name suffix is set."""
        from homeassistant.helpers.entity import UNDEFINED
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert cam.name is UNDEFINED

    def test_should_not_poll(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert cam.should_poll is False

    @pytest.mark.asyncio
    async def test_camera_image_returns_stored_bytes(
        self, mock_coordinator, mock_hub, installation, camera_device, jpeg_thumbnail
    ):
        from custom_components.securitas.camera import SecuritasCamera

        mock_coordinator.data = CameraData(
            thumbnails={"QR10": jpeg_thumbnail}, full_images={}
        )
        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == base64.b64decode(jpeg_thumbnail.image)

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_empty(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import (
            SecuritasCamera,
            _PLACEHOLDER_IMAGE,
        )

        mock_coordinator.data = CameraData(thumbnails={}, full_images={})
        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == _PLACEHOLDER_IMAGE

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_no_data(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import (
            SecuritasCamera,
            _PLACEHOLDER_IMAGE,
        )

        mock_coordinator.data = None
        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == _PLACEHOLDER_IMAGE

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_for_non_jpeg(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import (
            SecuritasCamera,
            _PLACEHOLDER_IMAGE,
        )

        # Non-JPEG data (e.g. a file path encoded as base64)
        non_jpeg = ThumbnailResponse(
            image=base64.b64encode(b"not_jpeg_data").decode(),
        )
        mock_coordinator.data = CameraData(
            thumbnails={"QR10": non_jpeg}, full_images={}
        )
        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == _PLACEHOLDER_IMAGE

    def test_device_info_uses_camera_sub_device(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera
        from custom_components.securitas import DOMAIN

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        info = cam.device_info
        assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info[
            "identifiers"
        ]
        assert info.get("via_device") == (DOMAIN, "v4_securitas_direct.2654190")

    def test_extra_state_attributes_timestamp(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        jpeg_thumbnail,
    ):
        from custom_components.securitas.camera import SecuritasCamera

        mock_coordinator.data = CameraData(
            thumbnails={"QR10": jpeg_thumbnail}, full_images={}
        )
        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        attrs = cam.extra_state_attributes
        assert attrs["image_timestamp"] == "2026-03-09T12:00:00Z"
        assert attrs["capturing"] is False

    def test_extra_state_attributes_no_data(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        mock_coordinator.data = None
        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        attrs = cam.extra_state_attributes
        assert attrs["image_timestamp"] is None

    def test_handle_coordinator_update_rotates_token(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        cam.async_update_token = MagicMock()
        cam.async_write_ha_state = MagicMock()

        cam._handle_coordinator_update()
        cam.async_update_token.assert_called_once()
        cam.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_added_to_hass_subscribes_to_state_signal(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        mock_hass = MagicMock()
        cam.hass = mock_hass

        connected_signal = {}

        def _capture_connect(hass, signal, callback):
            connected_signal[signal] = callback
            return MagicMock()

        with patch(
            "custom_components.securitas.camera.async_dispatcher_connect",
            side_effect=_capture_connect,
        ):
            await cam.async_added_to_hass()

        from custom_components.securitas.const import SIGNAL_CAMERA_STATE

        assert SIGNAL_CAMERA_STATE in connected_signal

    def test_handle_state_writes_for_matching_camera(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        cam.async_write_ha_state = MagicMock()

        cam._handle_state("2654190", "QR10")
        cam.async_write_ha_state.assert_called_once()

    def test_handle_state_ignores_other_camera(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_coordinator, mock_hub, installation, camera_device)
        cam.async_write_ha_state = MagicMock()

        cam._handle_state("2654190", "QR11")
        cam.async_write_ha_state.assert_not_called()


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

        mock_hub.capture_image = AsyncMock(return_value=(b"\xff\xd8", None))
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


class TestSecuritasCameraFull:
    """Tests for the SecuritasCameraFull entity."""

    def test_unique_id(self, mock_coordinator, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert cam.unique_id == "v4_2654190_camera_full_QR10"

    def test_has_entity_name(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert cam._attr_has_entity_name is True

    def test_name_is_full_image(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert cam.name == "Full Image"

    def test_should_not_poll(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert cam.should_poll is False

    @pytest.mark.asyncio
    async def test_camera_image_returns_stored_bytes(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCameraFull

        image_bytes = b"\xff\xd8\xff\xe0full_jpeg"
        mock_coordinator.data = CameraData(
            thumbnails={}, full_images={"QR10": image_bytes}
        )
        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        result = await cam.async_camera_image()
        assert result == image_bytes

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_empty(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import (
            SecuritasCameraFull,
            _PLACEHOLDER_IMAGE,
        )

        mock_coordinator.data = CameraData(thumbnails={}, full_images={})
        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        result = await cam.async_camera_image()
        assert result == _PLACEHOLDER_IMAGE

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_no_data(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import (
            SecuritasCameraFull,
            _PLACEHOLDER_IMAGE,
        )

        mock_coordinator.data = None
        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        result = await cam.async_camera_image()
        assert result == _PLACEHOLDER_IMAGE

    def test_device_info_matches_thumbnail_entity(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """Both camera entities must share the same HA device (same identifiers)."""
        from custom_components.securitas.camera import (
            SecuritasCamera,
            SecuritasCameraFull,
        )
        from custom_components.securitas import DOMAIN

        thumb_cam = SecuritasCamera(
            mock_coordinator, mock_hub, installation, camera_device
        )
        full_cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )

        assert (
            thumb_cam.device_info["identifiers"] == full_cam.device_info["identifiers"]
        )
        assert (
            DOMAIN,
            "v4_securitas_direct.2654190_camera_QR10",
        ) in full_cam.device_info["identifiers"]

    def test_handle_coordinator_update_rotates_token(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCameraFull

        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        cam.async_update_token = MagicMock()
        cam.async_write_ha_state = MagicMock()

        cam._handle_coordinator_update()
        cam.async_update_token.assert_called_once()
        cam.async_write_ha_state.assert_called_once()

    def test_extra_state_attributes_timestamp(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        jpeg_thumbnail,
    ):
        from custom_components.securitas.camera import SecuritasCameraFull

        mock_coordinator.data = CameraData(
            thumbnails={"QR10": jpeg_thumbnail}, full_images={}
        )
        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        attrs = cam.extra_state_attributes
        assert attrs["image_timestamp"] == "2026-03-09T12:00:00Z"

    def test_extra_state_attributes_no_data(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCameraFull

        mock_coordinator.data = None
        cam = SecuritasCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        attrs = cam.extra_state_attributes
        assert attrs["image_timestamp"] is None
